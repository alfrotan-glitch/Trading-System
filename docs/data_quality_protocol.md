# Data Quality Protocol
Version: 0.1.0

## Checks (12, fail-closed)
`src/qts/data/quality.py` `validate_bars`:
1. monotonic_time (strictly increasing open_time)
2. tz_aware (all tz-aware UTC)
3. no_future (close_time ≤ now)
4. ohlc_invariants (high ≥ all, low ≤ all, high ≥ low)
5. positive_prices (>0)
6. abnormal_spreads (>10% range in >5% bars)
7. no_duplicates (symbol, open_time)
8. single_symbol (one instrument/venue)
9. no_missing_bars (unexpected missing intervals >2% of the active expected span fail; recognized weekend closures are reported separately; unknown holidays remain unexpected)
10. session_boundaries (bar duration integrity: close-open >0 and <2 days; this is not a broker-session calendar)
11. no_broker_artifacts (placeholder, future MT5 artifacts)
12. volume_non_negative

Overall `passed` true only if all PASS; otherwise `store.write_bars` raises `ValueError` (fail-closed).

## Gap semantics

`qts.data.quality.analyze_gap_semantics` is the single gap model used by
validation, manifests and inventory. It reports distinct populations:

- `gap_events`: observed-bar transitions with one or more nominal cadence slots absent;
- `calendar_span_missing_intervals`: all nominal slots absent between the first and last observed bar, including closures;
- `closure_intervals`: slots classified by the explicit schedule policy (the default only recognizes Friday-to-weekend boundaries);
- `unexpected_missing_intervals`: all remaining absent slots, including unknown holidays or unexplained data holes;
- `active_span_expected_intervals`: observed bars plus unexpected missing intervals;
- `active_span_missing_fraction`: unrounded unexpected missing intervals divided by `active_span_expected_intervals`;
- `active_span_missing_pct`: presentation-only percentage of that fraction;
- `max_unexpected_gap_duration_s`: the longest consecutive unexpected missing duration.

The blocking rule is `active_span_missing_fraction <= 0.02`. The implementation
compares the unrounded fraction (equivalently, the integer-derived counts),
not the rounded `active_span_missing_pct`; 2.004% cannot pass as displayed
2.00%. Empty input has no active span and fails closed.

The legacy keys `gap_count`, `missing`, `missing_pct`, `expected`, and `actual`
remain only as compatibility aliases. New reports must use the explicit names.
A low event count cannot pass a high-duration missing block: the quality gate
fails when the unrounded `active_span_missing_fraction` exceeds 0.02. A
broker/session calendar is not inferred from OHLC; explicit schedule evidence is
required to classify non-weekend closures.

## Stress testing and adversarial coverage

The focused gap/provenance tests are in
`tests/unit/test_gap_semantics.py` and `tests/unit/test_provenance_roles.py`.
They cover:

- one long missing block despite a low event count;
- many short missing intervals where event count and duration differ, including
  102 isolated omissions across 5,000 nominal slots;
- legitimate weekend closures excluded from unexpected missingness;
- mixed closure and unexpected gaps spanning a session boundary;
- explicit non-weekend schedule evidence;
- calendar-span versus active-span coverage;
- exact 2% and below-2% PASS fixtures;
- above-2% FAIL even when percentage display rounding could hide the excess;
- zero-coverage/empty input FAIL and full coverage PASS;
- low event count/high duration, ambiguous source, Dukascopy/MT5 role
  separation, and legacy-manifest compatibility.

The broader suite also exercises duplicates, timestamp/timezone errors,
future leakage, OHLC invariants, source labeling, broker boundaries and
synthetic/DEMO/REAL safety boundaries. Corrupted data must fail closed —
`validate_bars` returns `passed=False`, ingestion raises, and no manifest is
created.

## Versioning / Locking
Every dataset immutable: `store.write_bars` creates new `version` checksum,
`schema_version`, `preprocessing_version`, `timezone`, `symbol_mapping`,
`quality_report` stored. Changing preprocessing → new version, not mutate.
Research evidence always identifies exact `checksum`. Locked tests remain
inaccessible during discovery via `LockedTestPartitioner` frozen.

## Machine Evidence
`data/evidence/data_quality_summary.json` is a historical derived export with
per-dataset quality reports. Current audit status and artifact classification
are in `data/evidence/research_integrity_audit.json`.
