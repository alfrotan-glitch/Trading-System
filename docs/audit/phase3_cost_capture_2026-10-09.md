# Phase 3 — Actual execution cost capture, and the 15m data gate

**Date:** 2026-10-09
**Branch:** `arena/db6f7053-trading-system` → `main` (PR #11)
**Commits:** `6beaba6`, `4dbfd5a`, `b59d85f`, `e5e29e3`
**Mode:** `DEMO_EXECUTION` only. `LIVE_LOCKED`. No live trading enabled. No edge claimed.

---

## 1. What this phase set out to do

Six items, in the order they were asked for:

1. Capture actual DEMO execution costs for `XAUUSD@` — broker-reported spread,
   commission, swap, slippage, requested versus executed prices, volume,
   timestamps, deal/order identifiers — preserving raw evidence and
   distinguishing unavailable fields from zero.
2. Reconcile actual versus modelled costs per fill and per round trip.
3. Make the pipeline restart-safe and auditable; never produce falsely
   favourable results.
4. Test partial fills, rejected orders, duplicate events, delayed swap,
   missing fields, reconnects and reconciliation errors.
5. Run the complete verification suite and document evidence, limitations and
   reproduction commands.
6. Continue the frozen benchmark audit on genuine broker-compatible 15m
   XAUUSD history with measured costs.

Items 1–5 are complete. Item 6 produced a **negative result with a number
attached**, which is recorded in §7.

---

## 2. The defect this phase exists to close

Before this phase, `MT5Adapter.submit()` fetched the broker's deal rows — the
only place commission, swap and fee exist — and threw them away. `last_submission`
carried ids, an executed price and a comment. Every "net of costs" figure in
the system was therefore a **model output compared against nothing**.

The measurements existed for a few microseconds, in a numpy view over terminal
memory, and were then unrecoverable.

---

## 3. What was built

### `src/qts/execution/cost_capture.py` (new, ~1,000 lines)

| Piece | What it guarantees |
|:---|:---|
| `DealEvidence` / `SubmitEvidence` | Raw broker rows preserved verbatim; every field read defensively |
| `CostEvidenceStore` | Append-only JSONL, hash-chained, deduplicated by deal ticket |
| `reconcile_fill()` | One fill: modelled vs observed, signed delta |
| `reconcile_round_trip()` | One position: totals, revision tracking |
| `reconcile_store()` | Whole log, with a conclusion that cannot be over-read |

**Design rules, each one a failure this module exists to prevent:**

- **A field the broker did not send is `None`, never `0`.** A partial total
  would be a smaller number that looks better than the truth.
- **A partial total is never compared.** `reconcile_fill()` refuses to compute
  a delta when any component is missing. (This was a bug found by testing —
  see §6.)
- **A deal with no broker ticket is rejected outright**, not stored under a
  synthetic key. An unticketed deal cannot be proven to be a duplicate, so
  storing it risks recording one fill twice.
- **A replayed event is deduplicated.** A reconnect replays history; one fill
  must not become two.
- **Currency conversion is explicit or it does not happen.** MT5 reports in the
  account deposit currency. Conversion requires both an `fx_rate` and an
  `fx_source`; otherwise the amount is reported unconverted, never as USD.
- **A hash chain proves editing, not truncation.** A truncated tail still
  chains correctly. A sidecar `.head` file records the expected record count to
  close that gap.
- **Completeness is judged on cost-bearing fields only** (volume, price,
  profit, commission, swap, fee). Missing provenance (`entry`, `time_msc`) is
  recorded but does not discard good economics.

Every reconciliation conclusion is exactly one of:

```
NO_EVIDENCE            — nothing was captured
EVIDENCE_UNRELIABLE    — the log failed integrity verification
INCOMPLETE             — required fields unavailable; no conclusion is drawn
MEASURED on N round trip(s) — compares model vs reality;
                              EXPLICITLY NOT evidence of a trading edge
```

### `src/qts/adapters/mt5_adapter.py`

- `_deal_rows_as_dicts()` freezes deal rows (numpy views over terminal memory)
  into plain dicts before they go out of scope. Absent fields stay absent.
- `_quote_snapshot()` captures the pre-trade bid/ask/spread **before the send**,
  so a fill can never be judged against a later, more favourable quote.
- `_account_currency()` returns `None` when unknown rather than assuming USD.
- `submit()` and the close path now attach `deal_rows`, `pre_trade_quote`,
  `account_currency`, `partial_fill` and `captured_at` to `last_submission`.

### `src/qts/execution/demo_session.py`

`cost_evidence_store` (lazily opened) and `capture_broker_cost_evidence()`,
called on the submit success path **while the raw rows still exist**. A store
that cannot be opened degrades to *"no evidence"*, never to *"favourable
evidence"*.

### `src/qts/config/paths.py`

Registers the `cost_evidence` artefact and `QTS_COST_EVIDENCE_PATH` override,
rather than an ad-hoc path.

---

## 4. Reproduction commands

```bash
cd /home/user/Trading-System

# Lint and types
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src

# Fast tests (default selection)
.venv/bin/python -m pytest -q -p no:cacheprovider

# Everything, including integration and research
.venv/bin/python -m pytest -q -p no:cacheprovider --run-integration --run-research

# Just the new cost-capture tests
.venv/bin/python -m pytest -q -p no:cacheprovider \
    tests/execution/test_cost_capture.py \
    tests/execution/test_cost_capture_adapter.py
.venv/bin/python -m pytest -q -p no:cacheprovider --run-integration \
    tests/integration/test_demo_cost_capture.py

# The 15m readiness gate
.venv/bin/python -m qts edge readiness --ceiling-days 30 --source-label MT5_HISTORY
.venv/bin/python -m qts edge readiness            # assess the current dataset

# Desktop UI
npm test
node --check src/qts/desktop/ui/js/*.js
```

> The tree must be clean before a full-suite run: a teardown guard fails any
> test that leaves the working tree dirty.

---

## 5. Test coverage added

| File | Tests | Covers |
|:---|---:|:---|
| `tests/execution/test_cost_capture.py` | 37 | Missing/zero distinction, partial totals, dedupe, tampering, truncation, currency, slippage sign, delayed swap, orphans, conclusions |
| `tests/execution/test_cost_capture_adapter.py` | 16 | Row freezing, quote snapshots, account currency, close attribution, failing terminal |
| `tests/integration/test_demo_cost_capture.py` | 11 | End-to-end DEMO submit: charges captured, rejection writes nothing, missing fields, replay, restart |
| `tests/unit/test_benchmark_readiness.py` | 36 | Provenance classes, all six blocking requirements, ceiling projection arithmetic |
| `tests/test_cli_edge_readiness.py` | 8 | CLI fail-closed exit codes, JSON payload |

**Total: 108 new tests.** Two the required scenarios map as follows:

- *partial fills* — several deals on one order, each its own record, summed
- *rejected orders* — no cost evidence written at all (a rejection is not a
  zero-cost fill)
- *duplicate events* — replay after reconnect is counted, not recorded
- *delayed swap* — a late posting marks the earlier total `revised`
- *missing fields* — each of commission/swap/fee individually blocks the
  measurement
- *reconnects* — the store reopens and extends the chain; replay deduplicates
- *reconciliation errors* — tampering and truncation both detected

---

## 6. Defects found by testing, and fixed

This is the part worth reading. Four defects were found in **my own new code**
by the tests written against it:

1. **A delta was computed from a partial total.** When `reported_charges` was
   unavailable, `observed` totalled only slippage, and the comparison produced
   a confident-looking number biased towards "cheaper than modelled". Fixed:
   no delta unless every component is present.

2. **`per_fill_modelled_cost()` swallowed a `TypeError`**, turning an
   unevaluable cost model into a silently-zero modelled cost — the single most
   dangerous outcome in the module. It now raises, and `reconcile_fill()`
   records the failure as a note.

3. **A converted amount kept its source currency label.** After an explicit FX
   conversion the fill still reported `EUR`. Fixed to `USD`.

4. **Non-cost fields blocked cost measurement.** A deal missing `entry` or
   `time_msc` was marked incomplete, throwing away good economics over
   provenance detail. Completeness is now judged on cost-bearing fields.

And one **pre-existing defect in the repository**, described in §7.

---

## 7. Item 6 — the 15m data question, answered with numbers

**No genuine broker-compatible 15m XAUUSD history could be obtained in this
environment, and — this is the substantive finding — it could not be obtained
from this broker in sufficient quantity either.**

### 7.1 It is not available here

`MetaTrader5` is not installable on this Linux sandbox; the package is
Windows-only and requires a running terminal. The repository already records
this:

```
data/evidence/mt5_history_acquisition.json
  status = "MT5_PACKAGE_UNAVAILABLE"
  detail = "Windows + MT5 terminal required"
```

`qts edge benchmark --timeframe 15m` was run and **fails closed**:

```
ValueError: dataset manifest does not match requested instrument/timeframe:
manifest=XAUUSD/1H, requested=XAUUSD/15m
```

It does not silently fall back to 1H. The only canonical dataset in the
repository is a **synthetic 1H fixture** (500 bars, 2020-01-01 → 2020-01-21).

### 7.2 It is not obtainable in sufficient quantity from the broker either

The operator's earlier probe (`data/evidence/mt5_history_capability_report.json`)
established the terminal's retention ceiling: 1/7/30-day windows return bid/ask
ticks; **365 days fails** with `(-1, 'Terminal: Call failed')`.

`qts edge readiness --ceiling-days 30` converts that ceiling into bars:

| Requirement | Minimum | 30-day ceiling | Result |
|:---|:---|:---|:---|
| `B1-REAL-PROVENANCE` | observed data | `BROKER-DERIVED` | PASS |
| `B2-TIMEFRAME-MATCH` | `15m` | `15m` | PASS |
| `B3-DEPTH` | 5,000 bars | **1,971 bars** | **FAIL** |
| `B4-REGIME-COVERAGE` | 180 days | **30 days** | **FAIL** |

```
  30d ->   1,971 bars  FAIL |   30.0 days FAIL
  90d ->   5,914 bars  PASS |   90.0 days FAIL
 180d ->  11,828 bars  PASS |  180.0 days PASS
```

At 65.7 fifteen-minute bars per calendar day (23h sessions, 5 days/week),
reaching the 5,000-bar minimum needs **~76 calendar days** of history; the
target of 17,520 bars needs **~267 days**. The broker serves 30.

So the blocker is not only that this sandbox lacks a terminal. Even on the
operator's machine, broker 15m history is short of the blocking minimum by
**~2.5× on depth and ~6× on span**. Thirty days is one calendar month: one
regime, not an out-of-sample test.

**Therefore the three preregistered candidates were not evaluated on 15m data
this phase.** Their definitions were not touched.

### 7.3 A defect that would have blocked item 6 permanently

`classify_source()` names genuine broker history `BROKER-DERIVED`, not `REAL`.
The impulse adequacy gate required `data_class == "REAL"`. An MT5 history
export — **the exact data the gate exists to admit** — was therefore refused as
if it were synthetic:

```
MT5_HISTORY -> BROKER-DERIVED -> R1 passed: False
```

Both gates now share `CLAIM_ADMISSIBLE_CLASSES = {REAL, BROKER-DERIVED,
HISTORICAL}`, with a stated reason for every refusal. Admissible and
inadmissible classes are each pinned by tests. Widening that set widens every
claim gate in the system, so it is documented as a deliberate, non-local
decision.

### 7.4 What would unblock item 6

In order of preference:

1. **A deeper broker-history source.** Prove the 365-day request can succeed
   (chunked requests, or the terminal's own history centre export), then run
   `scripts/acquire_mt5_history.py` on the Windows host.
2. **A non-broker 15m source**, ingested with `MT5_HISTORY`/`BROKER-DERIVED`
   provenance — noting it is *not* broker-compatible, so measured broker costs
   would not be the right costs to apply to it.
3. **Accept mechanism-only status** and record, permanently, that no
   claim-eligible 15m evaluation is possible with the data available.

Then:

```bash
qts edge readiness --ceiling-days <N> --source-label MT5_HISTORY   # must exit 0
qts edge bootstrap --timeframe 15m
qts edge benchmark --timeframe 15m \
    --spread <measured> --slippage <measured> --swap-per-night <measured> \
    --cost-source "<broker, date, method>"
```

---

## 8. Limitations — stated plainly

- **No actual costs have been measured yet.** The capture pipeline is built,
  tested and wired, but it has only ever run against a simulated terminal. The
  measurement requires a live DEMO session on the operator's machine. Until
  then, `MEASURED` appears nowhere in a cost basis and nothing is
  claim-eligible.
- **The fake terminal's figures are not evidence.** The integration tests use a
  simulated venue; the charges they capture are test fixtures and prove the
  plumbing, not the cost of trading XAUUSD.
- **The evidence log is machine-local and deliberately gitignored.** Committing
  a log that looks like it came from a broker, when it came from a simulation,
  would be worse than having no log.
- **The 15m projection assumes session hours** (23h/day, 5 days/week). Real
  broker 15m series contain gaps, halts and rollover breaks; the achievable
  count is an upper bound.
- **Trade-count requirements are unmeasured for 15m.** The round-turn minimum
  (100 per candidate) has never been evaluated on 15m bars, because no 15m data
  exists here. It may prove unreachable even with sufficient history.

---

## 9. Verification results

Run on a clean tree at commit `e5e29e3`.

| Check | Command | Result |
|:---|:---|:---|
| Default suite | `pytest -q -p no:cacheprovider` | **1314 passed, 341 skipped** — exit 0 |
| Extended suite | `pytest -q -p no:cacheprovider --run-integration --run-research` | **1652 passed, 3 skipped** — exit 0 |
| CI's extended job | `pytest -q --run-integration --run-research tests/integration tests/research` | **338 passed** — exit 0 |
| Collection | `pytest --collect-only` | **1654 tests** (1546 before this phase: **+108**) |
| Lint | `ruff check src/ tests/` | All checks passed |
| Types | `mypy src` | No issues, 169 source files |
| Security | `bandit -q -r src` | 0 issues |
| UI tests | `npm test` | **48 passed** |
| UI syntax | `node --check` on every `src/qts/desktop/ui/js/*.js` | clean |

**CI (run 37898646502, PR #11): `fast` PASS · `extended` PASS.**
PR #11 — `OPEN`, `MERGEABLE`, `mergeStateStatus CLEAN`, base `main`,
head `arena/db6f7053-trading-system`.

### A pre-existing flake, found during verification

Two consecutive CI runs failed in *different* jobs, which pointed at flakiness
rather than a regression. Reproduced locally: 1 of 2 full extended runs failed.

`tests/test_tick_timestamp_contract.py::test_offset_recovered_exactly_across_bar_phases_and_zones`
captured `now = time.time()` once and then looped over 5 offsets × 4 bar phases,
while the adapter re-read `time.time()` on every call. At `bar_phase=59` the
forming bar sits one second from the previous minute, so a single elapsed second
pushed it over and the recovered offset came back 60s low:

```
AssertionError: (10800, 59, 10740.0)
```

It passed only when the loop finished inside one second. **The product code was
correct** — the adapter must measure against the current clock. The test now
freezes the clock with `monkeypatch`, so it tests the same arithmetic
deterministically. The assertion is unchanged and is not weakened; it now holds
for every phase rather than only for phases that run fast enough.

Fixed in `e5e29e3`. No product code touched.

---

## 10. Standing position

Unchanged from previous phases:

- `DEMO_EXECUTION` only; `LIVE_LOCKED` intact; risk limits and all safety gates
  preserved.
- `edge_validation.json` remains `BLOCKED_INSUFFICIENT_DATA`.
- `NO_VALIDATED_EDGE`. `REAL_CAPITAL_EXPOSURE = 0`.
- Nothing was promoted. The frozen candidate set verifies intact
  (`current_status()["frozen_set_intact"] is True`).
- No order was submitted to any venue.

The capture pipeline built here is the instrument that will eventually replace
the assumed cost numbers with measured ones. It has not done so yet, and
nothing in this document should be read as though it has.
