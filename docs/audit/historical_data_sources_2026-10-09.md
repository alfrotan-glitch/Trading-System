# Historical data sources for the 15m benchmark — assessment

**Date:** 2026-10-09
**Question:** which legitimate sources can supply genuine XAUUSD 15-minute
data, of sufficient depth, with trustworthy provenance?
**Constraint:** the frozen benchmark's requirements are **not** adjusted to make
any source pass. A source either clears the gate or it does not.

---

## The gate, restated

| Requirement | Minimum |
|:---|:---|
| `B1-REAL-PROVENANCE` | observed data (`REAL`, `BROKER-DERIVED`, or `HISTORICAL`) |
| `B2-TIMEFRAME-MATCH` | `15m` |
| `B3-DEPTH` | 5,000 bars (target 17,520) |
| `B4-REGIME-COVERAGE` | 180 days |
| `B5-TRADE-COUNT` | 100 round turns per candidate, weakest candidate sets the bar |
| `B6-OOS-SIZE` | 500 bars held out |

Five thousand 15m bars is ~76 calendar days; the 180-day span requirement is
therefore the binding one in practice. Two years of 15m is ~47,000 bars.

---

## Source 1 — MT5 terminal bars (`copy_rates_from_pos`) · **BEST PROSPECT**

| | |
|:---|:---|
| Provenance class | `BROKER-DERIVED` — claim-admissible |
| Genuine | yes, read from the trading account itself |
| Broker-compatible | **yes** — same feed, same spread, same session calendar |
| Depth | **UNKNOWN — never measured** |
| Cost | free, already connected |

This is the most promising source and the least investigated. The repository
only ever calls `copy_rates_from_pos` for a handful of bars (warm-up windows).
Nobody has asked how many M15 bars the terminal holds.

Bar history is stored locally in the terminal and is routinely far deeper than
tick history, so the 30-day figure observed for *ticks* says little about
*bars*. A positional read is also not subject to the range-request failure mode
that made the 365-day tick query fail.

**Blocking question:** how many M15 bars does this terminal hold?
**Answer it with:** `qts data mt5-depth` (read-only, seconds, no download).

---

## Source 2 — MT5 terminal ticks, chunked · **ALREADY BUILT**

| | |
|:---|:---|
| Provenance class | `BROKER-DERIVED` — claim-admissible |
| Genuine | yes |
| Broker-compatible | **yes** — bid **and** ask, so true spread is observable |
| Depth | **UNKNOWN — never run** |
| Cost | the acquisition is slow; ticks are large |

`qts.data.mt5_history_acquisition` is already a chunked, interrupt-safe,
restart-safe, verified-on-write acquisition layer: 24h chunks, recursive
halving on failure, per-chunk Parquet parts with a manifest updated after every
commit, and SHA-256 digests. It has never been executed, because no terminal
has been available — its recorded status is `MT5_PACKAGE_UNAVAILABLE`.

Aggregated to 15m this gives the best possible input: broker bid/ask, from
which real spread is measured rather than assumed.

**Blocking question:** how far back do 24h chunks succeed?
**Answer it with:** `qts data mt5-depth` for the cheap probe, then
`scripts/acquire_mt5_history.py` for the real run.

---

## Source 3 — Dukascopy · **DEEP, BUT NOT BROKER-COMPATIBLE**

| | |
|:---|:---|
| Provenance class | `HISTORICAL` (if labelled correctly) — claim-admissible |
| Genuine | yes — a real market feed, already used by this project |
| Broker-compatible | **no** — Dukascopy's feed is not the broker's feed |
| Depth | **sufficient** — the project's own acquisition spans 2025-08 → 2026-03 in monthly Parquet files (~11,000+ 15m bars) |
| Cost | free |
| Licence | **the upstream repository ships NO LICENCE** — internal research use only, no redistribution |

Dukascopy clears depth and span comfortably. What it cannot supply is the
broker's own spread and execution. Applying a spread measured on WMMarkets-Demo
to Dukascopy mid-prices is a **modelled** cost on a **different** feed —
defensible as a sensitivity study, but it is not a measurement of trading this
broker, and the report must say so.

**Labelling matters.** `classify_source("dukascopy")` returns `UNVERIFIED`,
which blocks at `B1`. Ingest it with a `historical_import*` source label
(e.g. `historical_import_dukascopy_xauusd_15m`) so it classifies as
`HISTORICAL`. Do not relabel it `MT5_HISTORY` — that would misstate where it
came from, which is the one thing provenance is for.

---

## Source 4 — Terminal History Centre CSV export · **MANUAL, DEEP**

| | |
|:---|:---|
| Provenance class | `BROKER-DERIVED` — claim-admissible |
| Genuine | yes — exported from the trading terminal |
| Broker-compatible | yes |
| Depth | often years of bars; depends on how long the terminal has been fed |
| Cost | manual operator effort |

Operator exports M15 bars from the terminal's History Centre and ingests them.
Provenance is auditable if the export is checksummed at the time it is made.
Worth doing only if Source 1 comes back short.

---

## Source 5 — Commercial vendors · **NOT PURSUED**

Genuine and deep, but they introduce a licence obligation, and none of them is
broker-specific, so they solve depth at the cost of broker-compatibility —
strictly worse than Source 1 or 2 for this purpose. Not investigated further;
no vendor claims are made here because none could be verified from this
environment.

---

## Determination

1. **Sufficiency cannot yet be determined.** It is blocked on one measurement —
   M15 bar depth on the Windows terminal — which takes seconds and has never
   been taken. Sources 1 and 2 are the ones that can satisfy both depth and
   broker-compatibility, and both are currently `UNKNOWN`.

2. **Provenance is trustworthy for Sources 1, 2 and 4** (all `BROKER-DERIVED`,
   read from the trading account), **and for Source 3** (a real feed, but a
   different one).

3. **The previously recorded "30 days" does not support the conclusion that was
   drawn from it.** It was the largest window a *single* request returned. One
   oversized request failing is a request-size limit, not a retention limit.
   The acquisition layer already assumes this by chunking and halving on
   failure. Until `qts data mt5-depth` is run, the honest status is **UNKNOWN**,
   not "insufficient".

4. **No requirement was weakened.** The minimums are unchanged (5,000 bars,
   180 days, 100 round turns per candidate, 500 held out). `qts edge readiness`
   still exits non-zero for every dataset currently available, and the
   repository's synthetic 1H fixture still fails all four blocking checks.

---

## What to run, in order

```bat
:: 1. read-only depth probe — the decisive measurement
qts data mt5-depth --json-out data\evidence\mt5_depth_probe.json

:: 2. if bar depth >= 5000 bars spanning >= 180 days:
qts demo cost-check --record          :: measure costs from existing deals

:: 3. ingest and gate the dataset
qts data ingest --source historical_import_mt5_15m --path <export> \
    --instrument XAUUSD --timeframe 15m --venue MT5
qts edge readiness --data-version <version>     :: must exit 0

:: 4. only then evaluate the frozen candidates
qts edge benchmark --timeframe 15m \
    --spread <measured> --slippage <measured> --swap-per-night <measured> \
    --cost-source "<broker, date, method>"
```

If step 3's readiness gate exits non-zero, the candidates are **not** evaluated
and nothing is concluded. Mechanism evidence only.
