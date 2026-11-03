# QTS Gold — Historical M15 Tail Coverage Correction (2026-11-03)

**RESEARCH ONLY / LIVE LOCKED / NO VALIDATED EDGE**

## Reproduced root cause

The preserved, private 2025-to-date evidence archive has SHA-256:
`88e9f2d3e20dce58e916aa8d0bc4ee34c3849d626a7eb308e69e240de4fa2656`.

The old archived summary read `HISTORICAL_EVIDENCE_INVALID_NO_GO` and cited an outside-period signal. The underlying opportunity ledger contains exactly two identical-time, zero-signal warmup rows at `2024-12-31 20:45`, legitimately preceding the requested 2025-01-01 start.

A byte-for-byte reproduction of the then-current canonical source, Git blob `ccf9b6f49a099d74fac16e385b66cc8238922e3e`, correctly excluded those two rows but **incorrectly promoted** the 2025-01-01 through exclusive 2026-11-03 history to `HISTORICAL_RESEARCH_COMPLETE_NOT_LIVE_APPROVED`. Its 14-day endpoint tolerance failed to detect a missing final Monday session.

## Verified correction

The canonical `gold_robot/research/summarize_2025_history.py` now fails closed if a recent broker-server weekday lacks M15 closed-bar evidence, and requires a conservative final-day observation at or after 18:00 broker-server time. This heuristic does **not** independently verify broker tick coverage or holiday schedules. A documented broker closure must be established before relaxing a coverage failure.

Re-running the fixed script, Git blob `8e9f48ae2f266953f2c2d14d31a9c34294f3e063`, against the **unchanged** nine source files yields:

- `status: HISTORICAL_MARKET_DATA_COVERAGE_NO_GO` (expected process exit code **2**)
- `trailing_weekdays_without_closed_bars: ["2026-11-02"]`
- `last_observed_bar_server: 2026.10.30 22:30:00`
- `excluded_prestart_warmup_rows: 2`
- `native_m15_closed_bars: 43312`
- `native_completed_positions: 172`, `native_positions_net_usd: 98.45`
- `market_data_window_coverage_checked: false`

The regenerated summary's SHA-256 is `d8e2513110126d39f91acb27f4d6f567eccd4694e3d477e4de6e85afee4cb44a`. It is deliberately separate from the original invalid summary, which must remain immutable. The source/EX5/.set binaries, actual fee terms, intratrade ticks and Journal were **not** in this evidence archive and were **not** fabricated.

## Verification and limitations

Ten local tests passed, including the exact historical archive, missing Monday, weekend, truncated weekday, and empty bar series. GitHub Research Safety at the updated source manifest recorded **564 passing tests and two pre-existing unrelated failing assertions** (dual opportunity message text and MT5 installer include-contract test); the checksum manifest mismatch was resolved by refreshing the 179-file source index. The full CI is not green and must not be reported as such.

No strategy parameters were tuned, no broker orders were submitted, and the original 172-deal history is not an untouched holdout. **LIVE remains LOCKED.**
