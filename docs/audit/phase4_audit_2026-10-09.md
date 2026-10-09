# Phase 4 — Independent verification, MT5 compatibility, and the depth question

**Date:** 2026-10-09
**Branch:** `arena/db6f7053-trading-system` → `main` (PR #11)
**Commits this phase:** `c992a77`, `816cc8f`, `8bb1fe4`
**Mode:** `DEMO_EXECUTION` only. `LIVE_LOCKED`. Nothing promoted. No edge claimed.

---

## 1. Independent verification of the pushed state

Checked from scratch rather than taken from the previous report.

| Item | Result |
|:---|:---|
| Branch | `arena/db6f7053-trading-system` |
| HEAD | `8bb1fe4` — local `==` `origin/arena/…` |
| Working tree | clean (`git status --porcelain` empty) |
| Ahead/behind `origin/main` (`54cbd9f`) | 11 ahead, **0 behind** |
| PR #11 | **OPEN**, `mergedAt: null` (**unmerged**), not draft |
| PR base / head | `main` ← `arena/db6f7053-trading-system` |
| Mergeable | `MERGEABLE`, `mergeStateStatus: CLEAN` |
| CI on head `8bb1fe4` | `fast` **pass**, `extended` **pass** |
| CI on `816cc8f` (previous head) | `fast` **pass**, `extended` **FAILURE — unresolved** |

### 1.1 The `816cc8f` CI failure

Not taken on trust from the previous report, and **not** reproducible.

The `extended` job on `816cc8f` (run 37902391224) failed at step 5
(`Integration + research only`), 08:01:40Z → 08:02:04Z — i.e. it ran the suite
for its full ~24s and exited 1, rather than dying early.

**What was ruled out:**

* **Not the warmup 15-minute-bucket race.** `WarmupTerminal` builds its bars at
  construction and the loader judges "forming" from its own `time.time()`, so
  they can disagree across a quarter-hour boundary. But no boundary falls in
  the failure window (08:00 and 08:15), so this is not it. The race is real and
  still worth fixing separately, but it did not cause this.
* **Not a dependency-version difference.** A fresh venv built from the current
  `pyproject.toml` at that exact commit runs the job clean.
* **Not CPU count or xdist distribution.** The sandbox is 2-core UTC, matching
  `ubuntu-latest`; `addopts` is `-n auto --dist loadscope` in both.
* **Not the sandbox timezone.** Both are UTC.

**Evidence:** 17 consecutive clean runs of the exact CI command at `816cc8f`
(12 in one batch, plus 5 earlier), and 1 with a freshly-installed dependency
set. All 338 passed.

**Conclusion: a nondeterministic flake, not a regression.** `8bb1fe4` — which
changes only the new depth module, the readiness `limit_kind`, and docs —
passes. CI log download is blocked in this environment
(`results-receiver.actions.githubusercontent.com`), and the check-run
annotations carry only "Process completed with exit code 1", so the failing
test could not be identified from the outside. **This is the one item the
operator cannot resolve from here** and it should be chased the next time it
recurs, from the log.

The previous phase's claims about cost capture and the readiness gate were
re-derived, not assumed: both modules are committed (`cost_capture.py` 1140
lines, `benchmark_readiness.py` 351 lines), and the 15m arithmetic reproduces.

---

## 2. Real MT5 compatibility — two defects found and fixed

Reviewing the capture against the actual MetaTrader5 API rather than the test
doubles found two defects of the same class, one new and one pre-existing.

### 2.1 Server-basis timestamps were called UTC

MT5 stamps deals in **server** time. `MT5Adapter.ticks()` already subtracts the
measured offset (`fromtimestamp(base - offset, tz=UTC)`) — that correction
exists because this repository's own evidence records the WMMarkets-Demo server
stamping UTC+3, and treating a server stamp as UTC once made every live tick
look three hours old in the future
(`tests/test_tick_timestamp_contract.py`).

`cost_capture` did no such correction. `poll_fills` did not either, and its
`fill["time"]` becomes `Fill.event_time` (`engine.py:1082`), feeding the
portfolio and round-turn pairing — so hold duration, overnight counting and any
"fill from the future" check were all exposed.

`DealEvidence` now carries `time_iso` (true UTC, only when the measured offset
was supplied), `time_iso_broker` (always, always labelled) and `time_basis`, so
a server stamp can never be mistaken for a UTC one. The session resolves the
offset via `adapter.server_utc_offset()` and passes it down; when it cannot be
measured the evidence is still captured, labelled `broker-basis-only`.

### 2.2 `profit` was a blocking required field

MQL5 defines `DEAL_PROFIT`, but the MetaTrader5 Python package's deal record
does not reliably expose it. Because completeness gates the measurement, a
terminal without it would have marked **every** deal incomplete — silencing the
one measurement that does work. Net P&L is not what this module measures; the
charges are. `profit` is now recorded when present and no longer gates.

### 2.3 numpy scalars

`numpy.int64` is **not** a subclass of Python `int`. Any `isinstance(value, int)`
check would silently report a broker field as missing — which for a charge
reads as "the broker charged nothing", the most dangerous possible misread. The
extractors use `int()` / `Decimal(str())` and are unaffected; that is now
pinned by 17 tests built from numpy scalars and a real MT5 field set.

---

## 3. Windows DEMO runbook, and proving capture before ordering

`docs/windows_demo_runbook.md` is the operator runbook. Every step before
ordering is read-only; nothing submits automatically; each failure message is
documented with its action.

New **`qts demo cost-check`** (read-only, submits nothing) lets an operator
learn whether cost capture works *before* risking a fill to find out:

| Check | Blocks | Why |
|:---|:---|:---|
| `terminal-reachable` | yes | — |
| `account-is-demo` | yes | `None` means UNKNOWN and fails closed |
| `deposit-currency-known` | yes | MT5 reports money in the deposit currency; USD must never be assumed |
| `server-offset-measured` | yes | must be MEASURED, not `assumed-utc-fallback` |
| `evidence-chain-verifies` | yes | a log failing integrity is not evidence |
| `evidence-store-writable` | yes | proven with a throwaway probe file that is then deleted |
| `deal-history-readable` | no | informational |
| `cost-fields-present` | no | informational |

Writability is proven with a throwaway file **that is then deleted** — proving
the store works must not itself write evidence.

`--record` (opt-in, default off) backfills historical deals, tagged
`source=mt5.history_deals_get.backfill`. **This is the cheapest honest way to
measure what a broker charges: read deals the account already made rather than
placing a trade to find out.**

---

## 4. The historical-data blocker — corrected, not resolved

New **`qts data mt5-depth`** (read-only, no orders) measures what has never
been measured:

* **M15 bar depth**, read positionally via `copy_rates_from_pos`. Bars are what
  the frozen candidates need, and this has never been measured on any terminal
  — the repo only asks for a handful of bars for warm-up. Bar history is stored
  locally and is routinely far deeper than tick history.
* **tick depth**, probed as several small one-hour windows at increasing age.

### The correction

The previous report treated "30 days" as a **proven retention ceiling** and
concluded broker history could not be obtained in sufficient quantity. That
conclusion was **too strong**.

The figure came from *one* `copy_ticks_range` call per window (1/7/30/365
days); the 365-day call failed with `(-1, 'Terminal: Call failed')`. An
oversized request failing is what a **request-size limit** looks like. It is
not a retention limit — and the evidence file says so itself: *"not the maximum
retention boundary"*. The acquisition layer already assumes the difference: it
chunks at 24h and recursively halves on failure, a design that only makes sense
if a big request can fail where small ones succeed.

`assess_acquisition_ceiling()` now takes `limit_kind`
(`"proven-retention"` | `"single-request"`) and reports the second as an
**UNVERIFIED LOWER BOUND**. A test pins that correcting the record does *not*
change the verdict — an inadequate source must not start passing because its
ceiling was reclassified.

**Status: UNKNOWN until `qts data mt5-depth` runs on the Windows terminal.**

### Sources assessed

`docs/audit/historical_data_sources_2026-10-09.md` assesses five sources on
genuineness, depth, provenance and broker-compatibility.

| Source | Provenance | Depth | Broker-compatible |
|:---|:---|:---|:---|
| MT5 bars (`copy_rates_from_pos`) | `BROKER-DERIVED` | **UNKNOWN — never measured** | **yes** |
| MT5 ticks, chunked (already built) | `BROKER-DERIVED` | **UNKNOWN — never run** | **yes** (bid+ask) |
| Dukascopy | `HISTORICAL` if labelled correctly | sufficient | **no** — different feed |
| Terminal History Centre CSV | `BROKER-DERIVED` | often years | yes |
| Commercial vendors | — | deep | no — not pursued |

No requirement was weakened. Dukascopy must be ingested under a
`historical_import*` label: the bare name `dukascopy` classifies `UNVERIFIED`
and blocks, and relabelling it `MT5_HISTORY` would misstate where it came from,
which is the one thing provenance is for.

---

## 5. Verification results

Run on a clean tree at `8bb1fe4`.

| Check | Result |
|:---|:---|
| `pytest` (default) | **1366 passed, 341 skipped** — exit 0 |
| `pytest --run-integration --run-research` | **1704 passed, 3 skipped** — exit 0 |
| CI's extended job | **338 passed** — exit 0 |
| Collection | **1706 tests** (1654 before this phase: **+52**) |
| `ruff check src/ tests/` | All checks passed |
| `mypy src` | No issues, 170 source files |
| `bandit -q -r src` | 0 issues |
| `npm test` | **48 passed** |
| `node --check` (all UI JS) | clean |
| CI on `8bb1fe4` | `fast` **PASS** · `extended` **PASS** |

No regressions. The clock-race flake fixed in `e5e29e3` did not recur across
two full extended runs.

---

## 6. Constraints preserved

* **Frozen candidate set intact** — `verify_frozen()` passes with no problems;
  all three still defined on `15m` with unchanged parameters.
* **`live_locked: True`** throughout the API, CLI and lifecycle layers.
* **`promotion: {"state": "RESEARCH", "advanced": false}`** — nothing promoted.
* **`edge_validation.json` = `BLOCKED_INSUFFICIENT_DATA`**.
* **`CLAIM_ELIGIBLE_BASES = frozenset({MEASURED})`** unchanged.
* **Authorization artifact untouched** — `git diff` against `main` is empty for
  `data/evidence/demo_execution_authorization_2026-09-23.json`.
* No gate weakening in this phase (`git diff d422f5b..HEAD` contains no
  loosening of `max_drawdown`, `risk_ceiling`, or any bypass flag).

---

## 7. Limitations

* **No actual cost has been measured.** The pipeline has only ever run against
  simulated terminals. Nothing is `MEASURED`; nothing is claim-eligible.
* **No real MT5 terminal has been reached from this environment.**
  `MetaTrader5` is Windows-only. All compatibility work here is reasoned from
  the API contract and pinned by tests against numpy-backed rows built to match
  it — not observed on a live terminal.
* **Depth remains UNKNOWN** until the operator runs `qts data mt5-depth`.
* CI logs could not be retrieved in this environment (the blob host is not
  reachable and the check-run annotations carry only the exit code), so CI
  verification is limited to per-job pass/fail and the `816cc8f` flake could
  not be attributed to a specific test.
* The warmup bucket race described in §1.1 is a latent flake that was **not**
  fixed here: it needs a clock-injection seam in the warmup loader, which is a
  change with production reach beyond this phase.

### 7.1 A provenance hazard found and fixed

Running the DEMO commands locally left
`data/evidence/demo_broker_identity_pin.json` untracked — and **not
gitignored**. The pin in it was taken against a *simulated* terminal
("Example Brokers Ltd", login 123456). Committing it would have asserted, in
Git history, that a real broker identity had been confirmed. That is strictly
worse than having no pin at all, and it is the same reason the cost-evidence
log is already ignored. The file is now gitignored, matching the existing rule:
export bounded summaries, never the machine-local artifact.
