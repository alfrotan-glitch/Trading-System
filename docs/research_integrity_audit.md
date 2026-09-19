# P0 Research-Integrity Audit and Reconciliation

**Status:** `AUDIT_COMPLETE_NO_RESEARCH_RERUN`
**Baseline HEAD:** `a0ff165` (`audit: reconcile research integrity and gap semantics`)
**Branch:** `arena/01a0b574-trading-system`
**Current posture:** research-first / fail-closed / `NO_TRADE`
**Machine result:** [`data/evidence/research_integrity_audit.json`](../data/evidence/research_integrity_audit.json)
**Completeness disposition:** [`docs/data_completeness_disposition.md`](data_completeness_disposition.md)
**Disposition evidence:** [`data/evidence/xauusd_completeness_disposition.json`](../data/evidence/xauusd_completeness_disposition.json)

This audit checks the data-quality, provenance, derived-evidence and research
boundary semantics. It does not acquire data, rerun the impulse study, start
MT5 observation, search strategies, or change execution permission.

## 1. Findings

### RI-001 — P0 — duration-blind missing-bar gate

- **Files:** `src/qts/data/quality.py`, historical REAL quality evidence,
  `data/evidence/data_inventory.json`.
- **Observed behavior:** `validate_bars()` previously failed only when the
  number of short abnormal gap events exceeded 2% of rows and ignored gaps of
  a day or more. A single very large missing block could therefore pass with
  one gap event. The store, manifest, inventory and research artifact also used
  different gap calculations.
- **Why it matters:** gap-event count is not coverage. The frozen inventory
  records 278 legacy gap events and 1,493 legacy unexpected slots, or 5.42%
  under its historical closure heuristic. The independently recomputed current
  conservative model has 279 gap events and 1,785 unexpected slots (6.42% of
  the active expected span), because Easter is not silently forgiven without
  explicit schedule evidence.
- **Evidence:** frozen inventory snapshot; independent source reconstruction;
  current adversarial regression tests for one huge block, isolated gaps,
  exact-threshold boundaries, zero coverage and full coverage.
- **Fix:** `analyze_gap_semantics()` is now canonical. `no_missing_bars` uses
  unexpected missing interval fraction, with a 2% fail-closed limit. The store
  and inventory use the same model. The frozen research artifact was not
  rewritten.

### RI-002 — P1 — closure and absence populations were conflated

- **Files:** `src/qts/data/quality.py`, `src/qts/data/store.py`,
  `src/qts/data/inventory.py`, `docs/data_quality_protocol.md`.
- **Observed behavior:** `dataset_missing_stats()` counted calendar-span
  absence, while inventory reported active-span missingness; store
  `session_stats.weekend_gaps` was actually the number of all gap transitions.
- **Why it matters:** readers could interpret `missing`, `gap_count`, or
  `weekend_gaps` as the same population.
- **Fix:** explicit fields now distinguish `gap_events`,
  `calendar_span_missing_intervals`, `closure_intervals`,
  `unexpected_missing_intervals`, active-span percentages and maximum
  unexpected duration. Legacy keys remain only as documented compatibility
  aliases. Unknown holidays are not silently forgiven.

### RI-003 — P1 — timeframe inference used the first delta

- **Files:** `src/qts/data/store.py`.
- **Observed behavior:** `_infer_timeframe()` used the first two bars. If the
  first interval was a missing block, the manifest could receive a non-timeframe
  cadence and downstream calculations could disagree.
- **Fix:** timeframe inference now uses the modal positive open-time delta,
  consistent with gap analysis.

### RI-004 — P1 — historical research quality status could be mistaken for current

- **Files:** REAL provenance, market observatory, release, timeframe,
  adversarial and current-state documents.
- **Observed behavior:** the frozen REAL run's `12/12` and `READY` wording was
  current-sounding even though it came from the old event-count gate.
- **Fix:** documentation now labels that status as frozen acquisition/research
  lineage and records the current hardened interpretation as gap-completeness
  `FAIL`. No research rerun was performed.

### RI-005 — P2 — source venue and execution namespace were too easy to conflate

- **Files:** `src/qts/data/store.py`, `src/qts/data/inventory.py`,
  `src/qts/data/provenance.py`, acquisition script.
- **Observed behavior:** the legacy manifest `venue: MT5` is a partition and
  instrument namespace, while the actual REAL source is Dukascopy-derived.
  The source label documented this, but the schema did not expose separate
  roles.
- **Fix:** new manifests and inventory rows expose
  `source_provider`, `source_feed`, `source_venue`, `execution_target`,
  `execution_venue`, and `venue_semantics`. Legacy manifests remain readable.
  For the REAL historical dataset, execution target and execution venue are
  `null`; no MT5 broker history is implied.

### RI-006 — P2 — derived artifacts needed an explicit policy

- **Files:** `data/evidence/*.json`, `docs/data_source_audit.md`,
  `docs/market_data_observatory.md`.
- **Observed behavior:** inventory/source-audit/quality/depth/forward JSON files
  were not all equally current or canonical.
- **Fix:** the audit now classifies them as canonical, frozen evidence, derived
  snapshots, historical synthetic-only exports, or current zero-observation
  exports. `data/evidence/research_integrity_audit.json` records the machine
  classification. No immutable research or acquisition artifact was rewritten.

### RI-007 — P2 — test-only forward simulation wording

- **Files:** `docs/data_requirements.md`, `src/qts/regime/observatory.py`.
- **Observed behavior:** a data-requirements row described ten simulated
  ForwardObservatory ticks as if they described current forward availability.
- **Fix:** it now states that the canonical forward store has zero real
  observations and that `simulate_observation` is test-only SYNTHETIC. The
  canonical store remains the source of truth; the committed manifest is a
  derived zero-observation export.

### RI-008 — P2 — licensing boundary was easy to overread in planning material

- **Files:** provider/source comparison documentation and acquisition
  provenance.
- **Observed behavior:** provider catalog rows used shorthand such as “free
  personal” even though they were planning metadata, and the acquired upstream
  repository has no LICENSE file.
- **Fix:** planning catalogs are marked unverified/non-acquired. The acquired
  dataset is restricted to internal research pending legal review; no conclusion
  about redistribution, commercial use or public release is asserted.

### RI-009 — P1 — omitted provenance defaulted domain data to REAL

- **Files:** `src/qts/domain/value_objects.py`, `src/qts/execution/reality.py`.
- **Observed behavior:** a bare `Tick` or `ExecutionObservation` was labelled
  `REAL` when the caller omitted its source. That made ambiguous test/adapter
  records stronger than their evidence and could collapse synthetic, DEMO and
  historical roles.
- **Fix:** defaults are now `UNVERIFIED`; explicit `REAL` remains available
  only to callers with a recorded basis. `DEMO` is accepted as a distinct
  domain label, while the forward collector continues to stamp its canonical
  session provenance explicitly.

## Chain reconciliation

The audited chain is now explicit and fail-closed:

1. **Acquisition:** `scripts/acquire_xauusd_dukascopy.py` records the pinned
   upstream source, transform, checksum, source label and conservative policy
   note. It does not imply an execution venue.
2. **Normalization:** source ticks are converted to UTC, validated into the
   canonical bar schema and labelled as Dukascopy-derived historical mid OHLC;
   bid/ask and spread are not manufactured.
3. **Validation:** `validate_bars(bars, timeframe)` runs the structural checks
   and the canonical gap model. A failed report is rejected by strict ingest.
4. **Ingestion:** `SqliteParquetDataStore.write_bars()` infers cadence from the
   modal observed delta, calls the same validator and computes the same
   explicit gap statistics before creating Parquet/SQLite records.
5. **Manifest:** the immutable manifest persists quality/session statistics and
   separate source-provider/feed/venue and execution-target/venue roles. Legacy
   manifests remain readable with conservative defaults.
6. **Inventory/audit:** `generate_inventory()` delegates to the canonical gap
   model; `audit_data_sources()` exposes those populations and role fields
   without promoting an old snapshot to current evidence.
7. **Research adequacy:** frozen REAL research evidence retains its original
   preregistration, partition, trial ledger and result. Current completeness is
   evaluated separately; the corrected FAIL does not get silently overwritten
   by the historical `12/12` snapshot.

## 2. Gap-model conclusion

**The previous quality gate was not scientifically adequate with respect to
missing intervals and closures.** It could pass a materially incomplete
intraday dataset when the number of gap events was low or when a long gap was
ignored by its duration filter.

The corrected model is conservative:

```text
calendar_span_missing_intervals = all nominal cadence slots absent, including closures
closure_intervals                 = only default weekend or explicit schedule evidence
unexpected_missing_intervals      = all remaining absent slots
active_span_missing_fraction   = unexpected / (observed + unexpected)
active_span_missing_pct         = presentation-only 100 * fraction
quality PASS                    = active_span_missing_fraction <= 0.02 (unrounded)
```

The frozen REAL snapshot retains its historical evidence: 278 gap events, 58
legacy closure events, 1,493 legacy unexpected slots and 5.42% legacy
active-span missingness. The current conservative recomputation recognizes 57
weekend-boundary closure events and finds 1,785 unexpected slots, or 6.42% of
27,823 active expected intervals. The 33.36% calendar-span absence figure is
not used as the quality fraction because it includes closure absence; it remains
visible as a separate calendar metric. The legacy 1,493 count is not rewritten.

The root-cause and recovery disposition is recorded in
`docs/data_completeness_disposition.md`: QTS loss is zero, 140 of 154 upstream
update-loss slots can be materialized from earlier upstream files into a
separate failed candidate, and complete recovery requires a new authoritative
acquisition. This correction does not weaken a gate, alter the hypothesis,
modify the locked partition, reset the trial ledger, or rerun research.

## 3. Evidence inventory

| Artifact | Status | Canonical? | Current? | Action |
|---|---|---:|---:|---|
| `data/evidence/xauusd_dukascopy_acquisition.json` | frozen acquisition provenance | Yes for acquisition lineage | Yes as historical run record | Preserve; do not rewrite bytes or claims |
| `data/evidence/xauusd_completeness_disposition.json` | current P0 completeness disposition | Yes for this disposition | Current audit result | Maintain with the audit commit |
| `data/evidence/xauusd_recovery_candidate_manifest.json` | separate immutable recovery candidate lineage | Yes for candidate provenance | Failed candidate; not research-eligible | Never promote over frozen REAL snapshot |
| `data/evidence/impulse_research_xauusd_dukascopy_15m.json` | frozen REAL research evidence | Yes for that run | Historical research result | Preserve; no rerun in this audit |
| `data/evidence/data_inventory.json` | derived inventory snapshot containing REAL and SYNTHETIC rows | No; manifests/store are primary | Snapshot-time | Preserve for lineage; current code now emits explicit gap roles |
| `data/evidence/data_source_audit.json` | derived acquisition-era source audit | No | Snapshot-time | Preserve; code/doc status now labels it derived |
| `data/evidence/data_quality_summary.json` | derived synthetic-era quality export | No | Historical/test-era only | Preserve; never use as REAL quality evidence |
| `data/evidence/historical_depth.json` | derived synthetic-era depth export | No | Historical/test-era only | Preserve; do not use as REAL depth certification |
| `data/evidence/forward_observation_manifest.json` | derived export from canonical forward SQLite | No | Current zero-observation snapshot | Preserve; regenerate only from the canonical store |
| `data/sqlite/forward_observatory.db` | forward observation store | Yes for observation state | Current store contains zero real sessions/ticks | No session started |
| `data/evidence/research_integrity_audit.json` | this audit's machine result | Yes for this audit | Current audit result | Maintain with the audit commit |

## 4. Provenance conclusion

`REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks` means
provenance-qualified historical XAU/USD mid-price OHLC bars derived upstream
from Dukascopy bid/ask ticks, from the pinned third-party mirror and transform
recorded in the acquisition evidence. It supports historical bar research
within the declared population, subject to its quality, coverage and licensing
limits.

It does **not** mean:

- historical MT5 broker bars;
- MT5 broker session hours or broker-specific spreads;
- continuous executable bid/ask history in the canonical bars;
- broker orders, fills, slippage, latency or realized P&L;
- a DEMO observation or LIVE eligibility.

The legacy manifest `venue: MT5` is retained as a dataset/storage namespace.
New manifest roles make the distinction explicit: `source_venue` describes the
Dukascopy source, while `execution_target` and `execution_venue` are `null` for
this historical dataset.

## 5. Safety confirmation

```text
DEMO_EXECUTION = DISABLED BY POLICY
LIVE = LOCKED
NO_TRADE = unchanged
trial ledger reset = NO
locked partition modified = NO
new strategy search = NO
real MT5 observation session = NOT RUN
research rerun = NOT RUN
```

Event-study outcomes remain event outcomes, not broker trades or fills. Declared
cost assumptions remain assumptions. R5 remains `FAIL / non-blocking`, and the
REAL conclusion remains `REGIME_DEPENDENT / BLOCK` in the frozen evidence.

## 6. Verification performed

Executed during this audit:

- focused gap/adequacy pytest — **22 passed**;
- full `/tmp/qts-venv/bin/python -m pytest -q` — **813 passed, 20 skipped** (833 collected);
- `/tmp/qts-venv/bin/ruff check src tests scripts` — **clean**;
- `node --check` for the two JavaScript views — **clean**;
- `/tmp/qts-venv/bin/python -m compileall -q src tests` — **clean**;
- configured `/tmp/qts-venv/bin/mypy src` — **Success: no issues found in 113 source files**;
- CLI help checks for `qts`, `qts data`, `qts data validate`, and `qts evidence verify` — **all exit 0**;
- `qts data validate --version 20260918-010+feaa0789-572728d9` — **PASS (500 bars; all 12 checks pass)**;
- evidence JSON parse — **clean**;
- Markdown relative-link validation — **clean**;
- `git diff --check` — **clean**.

The full suite emitted only the existing Starlette/httpx and AnyIO deprecation
warnings. Tests that export the derived forward manifest can update its
volatile timestamp/code-version fields; the checked-in derived export was
restored after verification and remains unchanged by this audit.

## 7. Final recommendation

Do not start strategy discovery, paper trading, DEMO execution or LIVE work.
The one next milestone is the separate readiness-gated Windows + MT5
`DEMO_FORWARD` observe-only session with zero orders. It is independent of the
historical REAL completeness disposition, is not started by this audit, and
cannot enable `DEMO_EXECUTION` or unlock `LIVE`.
