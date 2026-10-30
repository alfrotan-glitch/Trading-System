# Windows native test — adaptive branch (START HERE)
Branch: `independent/adaptive-robot-20261030` (do NOT test main:
main lacks the fix-branch gate, the router hardening, SMC, and scalp).
Base: main `6c8f786` + fix `5fc0929` + router/SMC + scalp.
Symbol: WMMarkets XAUUSD@. Tester model 4 (every tick based on real
ticks). Deposit $3,000, leverage 1:100, currency USD.
LIVE REMAINS LOCKED. This is Strategy Tester simulation only.

## Step 0 — compile first, nothing else counts without it
1. Open MetaEditor, compile `gold_robot/mt5_robot/QTS_Gold_Robot.mq5`.
2. If compilation fails, STOP and send the exact compiler errors
   back. Do not edit thresholds to make it compile; a compile fix
   that changes a frozen parameter restarts the unseen-window clock.
3. Confirm the compiled EA reports EntryStyle up to 9 (SMC=8,
   M1 scalp=9) and refuses Style 9 unless SignalTimeframe=M1 and
   MaxPositionMinutes=15.

## Step 1 — choose and record the validation window BEFORE running
- A fresh, previously unseen period AFTER 2026-10-30, at least
  3 months long, that does not overlap Jan–Feb 2026 or any period
  already used to judge Styles 0–7.
- Write the chosen FromDate/ToDate (format `yyyy.MM.dd`) into the
  run record BEFORE launching any test. Changing the window after
  seeing results invalidates the run.
- Each candidate needs >=100 closed trades, >=40 active days,
  >=20 trade days in that window before any positive screen.

## Step 2 — styles 0–8 on M15 (safety_on only)
1. Generate presets:
   `gold_robot/research/MakeTesterPresets.ps1` (creates
   `safety_on` presets with TesterIgnoreDailyAndPeakStops=false,
   RiskPerTradePct=0.50).
2. Run all nine styles (0–8):
   `gold_robot/research/RunAutomaticTester.ps1 -FromDate <from> -ToDate <to>`
   Do NOT use the script's default last-6-months window for the
   validation run; pass the preregistered window explicitly.
   Census presets (TesterIgnoreDailyAndPeakStops=true) are discovery
   only and may never support a claim.
3. For each style, verify the style in the report: the report must
   identify its EntryStyle (see `RunAutomaticTester.ps1`'s
   all-styles-identified check). A report that cannot be tied to a
   style is evidence-gap, not a result.

## Step 3 — Style 9 M1 scalp, manual run (the auto-runner is M15-only)
The auto-runner does not cover Style 9. Run it manually in the
Strategy Tester with exactly these settings, in addition to the
safety_on defaults:
- Expert: QTS_Gold_Robot.ex5, Symbol: XAUUSD@, Period: M1,
  Model: 4 (every tick based on real ticks),
  FromDate/ToDate: the SAME preregistered window as Step 2,
  Deposit: 3000, Currency: USD, Leverage: 1:100.
- Inputs: EntryStyle=9, SignalTimeframe=1 (PERIOD_M1),
  MaxPositionMinutes=15, TesterIgnoreDailyAndPeakStops=false,
  RiskPerTradePct=0.50, EnableDemoOrders=true,
  EnableDemoForwardOrders=false, EnableEntryDiagnostics=true.
- Any other timeframe, time cap, or safety_off setting is a
  different hypothesis, not Style 9.

## Step 4 — export and send back (all of it, unmodified)
For every style (0–9):
- The native MT5 HTML report (`.htm`, created by the tester itself).
- The forensic CSV for that style (`QTS_FORENSIC_STYLE_<n>` output
  via `gold_robot/research/BuildTradeForensics.ps1`).
- Equity (not closed-only) drawdown, losing streak, fill / expiry /
  rejection counts, and the outlier sensitivity (median and
  ex-top-2-winners net) from the forensic output.
- The broker cost basis: WMMarkets commission/swap/spread from an
  account statement, labelled MEASURED, with statement date; if no
  statement exists, label costs ASSUMED ($10/lot, $0.10 slip) and
  the run can at most be RESEARCH_POSITIVE_NOT_VALIDATED.
- Missing ledger = EVIDENCE_GAPS_NO_GO. Agent logs are never HTML
  reports (a file named `QTS_0.htm` that is actually a log is not a
  report).

## Step 5 — evaluate the exported ledgers (on Linux, after receipt)
Convert each style's completed trades to the edge_gate CSV format
(trade_id, date, gross_usd, commission_usd, slippage_usd,
swap_charge_usd, broker_fee_usd, plus decision-time regime where
available) and run, per style:
- `gold_robot/research/edge_gate.py <ledger.csv> --active-days <n>
  --gross-basis PRE_SLIPPAGE_REFERENCE --trials-tested <declared>
  --stress-extra-usd-per-trade <value> --provenance BROKER_NATIVE`
  (provenance BROKER_NATIVE only if the ledger is native; simulated
  ledgers stay SIMULATED and cannot pass.)
- `gold_robot/research/evaluate_ledger.py <ledger.csv>
  --active-days <n> --trials-tested <declared>
  --stress-extra-usd-per-trade <value> --provenance BROKER_NATIVE`
  for folds, DSR/Holm, placebo, 2x-cost robustness, per-regime audit.
- Declare trials_tested >= 10 (styles 0–9) plus every robustness
  perturbation actually run. If it exceeds 40, edge_gate lower=None
  is fail-closed; use DSR/Holm over the ledger-counted list.
- Gates (all must pass for a candidate): edge_gate net>0,
  stressed net>0, PF>1.15, bootstrap 99% lower>0; DSR>=0.95,
  alpha_t>=2.5 (DEV); mean walk-forward efficiency>=0.30, mean OOS
  Sharpe>=0.30; beats best static style AND placebo; positive at
  2x costs, 1.5x/2x spread, slippage stress. Any failing gate =
  NO-GO for that candidate, reported with the gate named.

## Step 6 — DEMO-forward (only after a tester pass, and only then)
Do not arm DEMO for Styles 4–9 until a tester pass exists, the
tester-only block change is separately frozen, and the operator
confirms slippage, fill rate, and gap-stop behaviour are consistent
with the tester. DEMO-forward is a separate gate, not a continuation
of the tester run.
