# Long-history XAUUSD data — provenance, coverage and limits

**Date:** 2026-10-10 · **Prereg:** `LH-XAUUSD-D1-2026-10-10`
**Machine evidence:** `data/evidence/longhistory/source_manifest.json`, `data/evidence/longhistory/data_quality.json` (no prices).
**Reproduce:** `python scripts/fetch_longhistory_sources.py` then `python scripts/build_longhistory_dataset.py`.

Nothing here is fabricated. Every bar is a bar a named public source published. Gaps stay gaps: no interpolation, forward-fill, repair or synthetic bar. Each source was fetched at a pinned Git commit with per-file SHA-256 checks (fail closed).

## 1. Sources

| ID | Repository @ commit | Content | Stamp basis | Licence (per repo) | Status here |
|---|---|---|---|---|---|
| `basemax_xauusd_15m` | BaseMax/XAUUSD-LSTM @ `43f4177` | 480,717 XAUUSD 15m bars, 2004-06-11 → 2025-09-30 | broker server clock (GMT+2/+3, US DST), converted | MIT (repo). CSV says derived from Kaggle `novandraanugrah/xauusd-gold-price-historical-data-2004-2024`; vendor and Kaggle terms **not verified** | **Research series** (2004-06-11 → 2025-02-28) |
| `ejtraderlabs_xauusd_m15_d1` | ejtraderLabs/historical-data @ `fbd29b3` | M15 230,400 bars 2012-05 → 2022-03; D1 | same as BaseMax; prices ×100 (points) | Apache-2.0 (repo). Upstream source not stated | **Provenance check only**: identical to BaseMax after ÷100 |
| `yuan_public_xauusd_15m` | No-Trade-No-Life/Yuan-Public-Data @ `b7ff758` | PT15M 50,000 bars 2022-03-09 → 2024-04-19, 16 chunks | **explicit UTC** (RFC3339 `Z`) | MIT (repo). README: "no guarantee of accuracy or completeness" | **Clock and price cross-check** (UTC reference) |
| `dukascopy_mirror_xauusd_15m` | vudo805/forex-price-simulator @ `4d6f155` | 26,038 15m mid bars 2025-08-06 → 2026-09-16, from Dukascopy bid/ask ticks | UTC | **No LICENSE** in upstream. Internal research use only; no redistribution | **Replicate** (not untouched: used by `walkforward_findings_2026-10-09.md`) |

The Dukascopy bars are the same dataset registered in `data/evidence/xauusd_dukascopy_acquisition.json`. The parquet hashes match the acquisition pins. The 15m CSV rebuilt here reproduces the pinned 26,038-bar export.

## 2. Clock: how BaseMax stamps were converted

Raw BaseMax stamps have no Sunday bars and do not match UTC. Correlating 15-minute log returns with the explicit-UTC Yuan series over five windows (`clock_by_window` in the evidence file):

| Window | Best raw shift (hours) | Correlation after conversion at shift 0 |
|---|---|---|
| 2022-03-10 → 2022-09-30 (US DST) | −3 | 0.927 |
| 2022-10-01 → 2023-03-15 (standard) | −2 | 0.895 |
| 2023-03-20 → 2023-10-25 (US DST) | −3 | 0.917 |
| 2023-10-30 → 2024-03-20 (standard) | −2 | 0.899 |
| 2024-03-25 → 2024-04-19 (US DST) | −3 | 0.904 |

Conversion rule (`server_gmt23_to_utc`): stamp = UTC + 3h while US Eastern DST is in effect, otherwise UTC + 2h. This is the usual GMT+2/GMT+3 broker convention. After conversion every window peaks at zero shift, and the correlation rises from ~0.60 (raw, pooled) to ~0.89–0.93.

Known limit: the spring switch hour is ambiguous on a dense grid. Real BaseMax stamps skip that hour and show no duplicates after conversion. A source that does not skip would be flagged by `quality_report` (duplicate or backward steps), not silently repaired.

## 3. Structure and coverage

| Series | Rows | Duplicates | OHLC violations | Non-positive | NaN | Off-grid | Notes |
|---|---|---|---|---|---|---|---|
| BaseMax (raw stamps) | 480,717 | 0 | 0 | 0 | 0 | 0 | 21 years; **2025 partial**: Mar 1,380, Apr 368, Jun 920, Jul 752, Aug 0, Sep 2 bars |
| BaseMax (UTC, research window) | 475,286 | 0 | 0 | 0 | 0 | 0 | to 2025-02-28 |
| ejtraderLabs M15 (÷100) | 230,400 | 0 | 0 | 0 | 0 | 0 | 2012-05-15 → 2022-03-04 |
| Yuan PT15M | 50,000 | 0 (after identical-duplicate check) | 0 | 0 | 0 | 0 | 2022-03-09 → 2024-04-19 |
| Dukascopy (UTC) | 26,038 | 0 | 0 | 0 | 0 | 0 | 2025-08-06 → 2026-09-16 |

Daily (trading day rolls at 22:00 UTC; a day with fewer than 40 bars is partial and excluded):

- Research: 5,336 days in total, 5,281 complete, 55 partial (1.0%). Median 92 bars per complete day.
- Replicate: 289 days, 288 complete, 1 partial.

## 4. Cross-source agreement (what it does and does not show)

| Pair | Overlap | Result | Interpretation |
|---|---|---|---|
| BaseMax vs ejtraderLabs | 230,398 bars | 99.996% of closes identical after ÷100 | **Same series.** Not independent. |
| BaseMax vs Yuan (UTC) | 49,820 bars | median |Δclose| $0.03; p90 $0.15; p99 $5.41 | **Same quotes, different export.** Agreement to cents, with a tail where bars differ. Not independent. |
| BaseMax vs Dukascopy | 0 usable bars | — | No overlap. Dukascopy cannot be cross-checked against BaseMax. |

Conclusion: the research series reflects **one underlying quote stream** that three public exports reproduce. Their agreement validates the export and clock handling. It does **not** validate the prices against a second, independently sourced market. Only the Dukascopy period is a separately sourced feed, and it lies entirely after the research window. That is why it is used as a replicate.

## 5. Claim status

- Provenance class: **third-party, unverified upstream**. Not `REAL` by the project's own evidence standard, which requires a verified source. It is not `BROKER-DERIVED` and not `MEASURED`.
- Costs: **ASSUMED** everywhere. No MT5 bar depth or broker cost has been measured. The MT5 history depth is still UNKNOWN; `qts data mt5-depth` must run on the Windows terminal.
- `CLAIM_ELIGIBLE_BASES = {MEASURED}` (`src/qts/research/costs.py`). Under the existing rule, no economic-edge claim can be made from this data.

## 6. Limits to carry into every result

1. The price history for 2004–2025 is one unverified third-party quote stream.
2. Costs are assumed. Stress at 2× and 3× plus a break-even multiplier is reported.
3. Volume is a tick count, not traded volume.
4. Partial days are excluded. Holidays and session breaks are therefore not modelled as bars.
5. The daily signal uses the 22:00 UTC roll. Stops are checked on daily ranges, so intraday order of events is unknown.
6. Dukascopy data has no licence and was already used for earlier research.
