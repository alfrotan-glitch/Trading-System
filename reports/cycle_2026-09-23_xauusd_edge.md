# Cycle report — XAUUSD edge discovery

**Generated:** 2026-09-23T07:40:00Z
**Branch:** `arena/01a0c9cc-trading-system`
**Decision:** `INCONCLUSIVE`

No repeatable, executable, statistically defensible XAUUSD edge was demonstrated. None was rejected. The canonical archive was verified and inventoried. Discovery hypotheses were not tested.

Safety was not changed. `confirm_live` is false. Execution mode is `backtest`. `demo_forward_enabled` is false. `DEMO_EXECUTION` remains disabled. LIVE remains locked.

## Data

| Fact | Status |
| --- | --- |
| Release | `dataset-xauusd-730d-20260919` |
| Asset | `XAUUSD_730d_20260919T114013Z.zip` |
| Expected SHA-256 | `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723` |
| Verified SHA-256 | match, measured on a GitHub-hosted runner |
| Bytes in this runtime | 0 |
| Bytes measured | 1,019,727,380 |
| Rows | 139,930,971 |
| Dataset digest | `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789` |
| Edge claim | `NOT ESTABLISHED` |

The runner report is `reports/canonical_zip_inventory.json`, commit `dc7d36c`, code `4901224655040cbb6cf0f61bd61c2daa969358a4`. Integrity passed: ledger rows, manifest row count, and parquet row count are all 139,930,971. Part hashes match. The dataset digest matches the previously published gap-report digest. That match identifies the extracted dataset. It is not a substitute for the zip hash. The zip hash was checked separately and matched.

This runtime did not download the Release CDN and does not hold the zip.

Defects, classified and not repaired:

- `ZIP_PATH_SEPARATOR`: 734 members are named with backslashes. They were read at the POSIX path. Member bytes were not changed. An earlier runner report counted 0 rows because it did not do this mapping. That zero is a reader failure, not a property of the archive. It remains in commit `0afb19b`.
- `TIMESTAMP_BASIS_UNVERIFIED`: `time_msc` was not converted. Session labels and timezone are `UNAVAILABLE`.

If the stored stamps are UTC, the span is 2024-09-19T11:40:13.452Z through 2026-09-18T23:58:59.790Z. That rendering is provisional. It is not confirmation.

Measured, not repaired:

- `time_msc` is monotonic in the streamed order. Non-monotonic count is 0.
- Adjacent same-millisecond excess rows: 6,071,793. Duplicate scope is adjacent only. Rows were not globally deduplicated.
- Consecutive identical quote rows: 74.
- Invalid bid, invalid ask, ask below bid, zero spread, and negative spread: 0.
- Spread in bps: min 0.374, mean 0.720, max 7.788. Exact median is `UNAVAILABLE`. The diagnostic count above 100 bps is 0. Rows were not removed.
- Gaps of at least 1s / 60s / 1h / 24h: 7,697,251 / 784 / 515 / 108. The 108 gaps of at least 24h match the count in the earlier gap disposition. They stay `UNCLASSIFIED_SPACING`. They were not resolved.
- Span-average tick rate is 2.22 rows per second. That is not a session rate.

`repairs_applied` is empty. `decision_supported` is false.

## Discovery

Not started. Preregistered H-MS-01, H-MS-02, and H-TOD-01 remain `NOT TESTED`. The preregistration file was not edited after this inventory.

H-TOD-01 stays blocked. The clock is not confirmed. A provisional UTC label is not permission to test clock windows.

The locked validation window, the last 40 percent of the raw `time_msc` span, was not used as a strategy sample. Whole-archive inventory was allowed and is not a fit.

## Validation

Not run. There is no out-of-sample result and no cost result. A profitable backtest was not produced and would not be `VALIDATED`.

## Execution

Not entered. Demo readiness is `NOT ESTABLISHED`. No Demo execution was enabled.

## Engineering

`uuid7()` was not changed. It remains `uuid.uuid4().hex`, not RFC 9562.

The runner job is `.github/workflows/canonical-xauusd-zip-inventory.yml`. An invalid permission-probe workflow was removed. The research sandbox did not download the release asset.

Executed and passed before the reader fix: `tests/test_canonical_zip_inventory.py` (8), `tests/test_github_runner_inventory_support.py` (2), and five acquisition integrity tests named in the commit. The full suite was not run.

## Decision

`INCONCLUSIVE`

The archive identity is established. An edge is not.
