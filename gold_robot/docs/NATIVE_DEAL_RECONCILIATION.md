# QTS Gold | Independent native deal reconciliation

**RESEARCH ONLY — LIVE LOCKED — no trade permission**

This narrow control independently re-sums original broker-authored `QTS_7_trades.csv` deal records and checks the result against both `QTS_TRADE_BY_TRADE.json` and the native UTF-16 MT5 `QTS_7.htm` report. It does **not** resimulate ticks, verify a profitable edge, authenticate WMMarkets tariffs, or change any strategy.

## Input

Use a completed **DUAL_DIRECTIONAL** Style 7 run folder, or the extracted `QTS_2025_TO_DATE_EVIDENCE.zip` folder, containing:

- `OPEN_RESULTS.json`
- `QTS_TRADE_BY_TRADE.json`
- `native/QTS_7_trades.csv`
- `native/QTS_7.htm`

Do not use an unrelated Style 7, Style 1, dual-both, or truncated safety-halted run to validate the published 172 positions. Confirm run dates and tester inputs separately in `OPEN_RESULTS.json` and the native MT5 report.

## Windows PowerShell (no broker login, no orders)

From the `Trading-System-Clean` repository, with the evidence folder already extracted:

```powershell
git pull --ff-only origin main
py -3 .\gold_robot\research\reconcile_native_deals.py "C:\PATH\TO\QTS_2025_TO_DATE_EVIDENCE" --output "C:\PATH\TO\QTS_2025_TO_DATE_EVIDENCE\reconciliation" --expect-positions 172 --expect-net 98.45
```

The output folder contains `QTS_NATIVE_RECONCILIATION.json` and, **only on success**, `QTS_INDEPENDENT_POSITION_LEDGER.csv`.

- `RECONCILED_RESEARCH_ONLY`: broker CSV, existing forensic JSON, native tester trade count, native reported PnL, and profit factor agree. **Not a trading GO.**
- `RECONCILIATION_FAILED_NO_GO`: missing inputs, duplicate/unclosed/wrong-side deals, JSON mismatches, or inconsistent MT5 totals. Read `blocker` in the JSON; exit code 2. A stale generated ledger is removed before each check.
- File SHA-256 checksums are recorded to prevent accidental evidence mixups. Do not alter historical source evidence to force reconciliation.
- All native commissions, swaps and fees on **both entry and exit deals** are counted once. The native MT5 net already includes recorded costs; do not add them again. Zero recorded commissions do not establish zero true broker fees.
- The optional `--contract-size` computes **indicative only** R-multiples. Do not use them as verified risk numbers without broker contract and tick-value evidence.
- This audit cannot establish the entry quote, full order lifecycle, stop displacement, or whether a stopped-out trade later hit its target. Those require broker tick records and tester journals.

## Acceptance

The claimed historical **172 trades / +USD 98.45 / PF 1.10** remain **UNVERIFIED** until this check runs against the actual local native exports and produces a clean report with hash-linked inputs. A passing reconciliation proves accounting consistency, **not independent holdout profitability**.

Regression tests:

```powershell
py -3 -m pytest gold_robot/tests/test_reconcile_native_deals.py -q
```

The test suite uses controlled synthetic deals; passing tests must never be described as auditing the 172 broker trades.
