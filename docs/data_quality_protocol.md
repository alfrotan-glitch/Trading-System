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
9. no_missing_bars (abnormal intraday gaps >1.5×common and <1 day, >2% abnormal fails)
10. session_boundaries (close-open >0 and <2 days)
11. no_broker_artifacts (placeholder, future MT5 artifacts)
12. volume_non_negative

Overall `passed` true only if all PASS; otherwise `store.write_bars` raises `ValueError` (fail-closed).

## Stress Testing
`src/qts/data/quality_protocol` via adversarial `tests/test_data_quality_stress.py` (12 adversarial):
- missing bars (remove 5% → `no_missing_bars` FAIL)
- duplicate ticks (add duplicate → `no_duplicates` FAIL)
- timestamp shifts (shift 1h → monotonic or gap FAIL)
- timezone errors (naive → tz_aware FAIL)
- bid/ask inversion (ask < bid → Tick validation FAIL)
- zero/negative price (close 0 → positive_prices FAIL)
- impossible spread (high-low 20% → abnormal_spreads FAIL)
- stale ticks (event_time age >60s → MarketDataProvider stale FAIL)
- out-of-order ticks (shuffle → monotonic FAIL)
- session contamination (weekend bar included → session FAIL if real)
- future timestamp leakage (future bar → no_future FAIL)
- symbol remapping (mix XAUUSD/EURUSD → single_symbol FAIL)
- partial historical coverage (1 bar → coverage FAIL)

Corrupted dataset must fail closed — `validate_bars` returns `passed=False`, ingestion raises, no manifest created.

## Versioning / Locking
Every dataset immutable: `store.write_bars` creates new `version` checksum, `schema_version`, `preprocessing_version`, `timezone`, `symbol_mapping`, `quality_report` stored. Changing preprocessing → new version, not mutate. Research evidence always identifies exact `checksum`. Locked tests remain inaccessible during discovery via `LockedTestPartitioner` frozen.

## Machine Evidence
`data/evidence/data_quality_summary.json` with per-dataset quality reports.

