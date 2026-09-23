# Cycle report — XAUUSD edge discovery

**Generated:** 2026-09-23T07:27:37Z
**Branch:** `arena/01a0c9cc-trading-system`
**Decision:** `INCONCLUSIVE`

No repeatable, executable, statistically defensible XAUUSD edge was demonstrated. None was rejected. The canonical tick archive is not in this runtime, so discovery has not started.

Safety was not changed. `confirm_live` is false. `load_settings()` reports execution mode `backtest` and `demo_forward_enabled` false. `DEMO_EXECUTION` remains disabled by policy. LIVE remains locked. No real-money order path was enabled.

## Data

| Fact | Status |
| --- | --- |
| Release | `dataset-xauusd-730d-20260919` |
| Asset | `XAUUSD_730d_20260919T114013Z.zip` |
| Expected SHA-256 | `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723` |
| Verified SHA-256 | not verified in this runtime |
| Bytes in this runtime | 0 |

The release lists the asset: 1,019,727,380 bytes, id 582342011, updated 2026-09-22T22:05:56Z. Listing is not possession. This runtime still has 0 zip bytes and did not download the Release CDN.

A GitHub-hosted runner verified SHA-256 `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723` and committed `reports/canonical_zip_inventory.json` at `0afb19b`. That report's `row_count` of 0 is not a measurement of the ticks. The zip members are named `parts\\part-000000.parquet`. The extractor treated the backslash as a literal character, so the ledger paths `parts/part-000000.parquet` were absent. Integrity also reported a vacuous hash pass because missing files were skipped. Manifest ledger arithmetic in that report is 139,930,971 rows and dataset digest `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`, which matches the previously published gap-report digest. That is ledger consistency, not a row measurement. Timestamp basis remains unconfirmed. No rows were repaired.

The reader now maps safe backslash member names to POSIX paths without changing member bytes, records `ZIP_PATH_SEPARATOR`, and fails a hash check when a ledgered part file is absent. A corrected runner inventory has not returned. Time range, timezone, duplicates, gaps, tick frequency, bid/ask, spread, and session/calendar remain `UNAVAILABLE` until that report is reviewed.

The machine-readable access record is `reports/dataset_access_xauusd_730d.json`.

## Discovery

Not started. No hypothesis was tested. Preregistered H-MS-01, H-MS-02, and H-TOD-01 remain `NOT TESTED`. No substitute dataset was analyzed as the canonical archive.

## Validation

Not run. There is no out-of-sample result and no cost result. A profitable backtest was not produced and would not be `VALIDATED` if it had been.

`configs/dev.yaml` sets `min_oos_sharpe: 0.0`. The code floor in `ValidationConfig` remains `0.30`. That floor was not applied to a candidate because no candidate was formed.

## Execution

Not entered. Demo readiness is `NOT ESTABLISHED`. No Demo execution was enabled.

## Engineering

`uuid7()` on this tree is `uuid.uuid4().hex`. It is not RFC 9562 UUIDv7. The format was not changed. An earlier report paragraph that called it a real UUIDv7, and a 101-test pass, described a dirty tree that is not this HEAD. Those tests were not re-executed for this report and are not cited as passing.

The inventory module still extracts only after the expected SHA-256 matches. It now maps safe backslash member names to POSIX paths and does not rewrite member bytes. A missing ledgered part no longer passes the hash check. Executed before this commit, and passed: `tests/test_canonical_zip_inventory.py` (8 tests, including the backslash and missing-part cases), `tests/test_github_runner_inventory_support.py` (2 tests), `tests/test_mt5_history_acquisition.py::test_integrity_validation_detects_tampering`, `test_in_progress_dataset_is_not_valid_complete_evidence`, `test_empty_response_is_empty_complete_not_data`, `test_crash_mid_chunk_orphan_part_is_discarded_on_resume`, and `test_acquisition_manifest_required_metadata`. The full suite was not run.

An invalid permission-probe workflow was created and is removed in this change. It is not a data path.

## Decision

`INCONCLUSIVE`

Discovery stays blocked until the runner report shows the expected SHA-256 and an unrepaired inventory. A checksum match on the runner is not, by itself, an edge.
