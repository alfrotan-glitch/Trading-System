# QTS Gold — Prospectively Frozen Champion/Challenger Study (V5)

**2026-11-01 | independent MT5 Strategy Tester research only | LIVE LOCKED**

## Why the old "self-correct after 10 trades" idea was not professional

A review after every ten completed broker positions is useful **for quality
control**, not a statistically defensible trigger to replace a trading rule.
Trading outcomes are noisy and correlated across strategies, regimes and time.
Repeatedly excluding a recently losing style and measuring improvement
against those same 10 losing trades is precisely the kind of in-sample
data snooping that creates fake alpha.

The new engineering boundary is therefore:

- Ten-trade reviews detect **candidate hypotheses** only; no source edits.
- A V5 challenger can test **one** pre-registered veto: when the EXISTING V4
  router selects the frozen strategy in the frozen closed-bar regime,
  **abstain**. Do not search for a substitute signal or change SL, TP,
  lot size, risk limits, fees or pending-order handling.
- The V4 champion and V5 challenger run the **same canonical EA binary
  and broker real-tick test**, exact dates, symbol, risk protections and
  cost stress. Only the V5 veto flag/style/regime differ.
- Freeze a new study **before the first day of its unseen evaluation
  window**, which must also begin after the last originating broker exit.
  Never edit a frozen plan or reuse old months as "unseen" evidence.

## Freeze once, then launch both MT5 arms in one operation

After a genuine V4 native run produced:
`QTS_V4_POSITION_ATTRIBUTION.json` and
`QTS_TEN_TRADE_REFLECTION.json`,
identify a *real* candidate strategy, market regime and checkpoint in
the ten-trade report. These are existing proposal identifiers; do not
invent one after looking at the intended test window.

From the repository root, use the user-friendly Windows commands below
with an **unseen future** month. This is for a planned research period,
not a current claim of tested performance:

```powershell
cd "$env:USERPROFILE\Trading-System-Clean"
python gold_robot\research\v5_study.py freeze `
  --reflection "gold_robot\reports_local\auto_runs\ORIGINAL_RUN\QTS_TEN_TRADE_REFLECTION.json" `
  --style 8 --regime TREND --checkpoint 1 `
  --from-date 2026.12.01 --to-date 2027.01.01 `
  --manifest gold_robot\docs\SOURCE_CHECKSUMS.json `
  --output "gold_robot\reports_local\FROZEN_STUDY.json"
```

The displayed style/period/checkpoint above are **illustrative values only**;
they are NOT recommendations or assertions about an actual native result.
The `freeze` command refuses nonexistent proposed combinations and
periods that already started or contain training exits.

**After the frozen evaluation period actually ends**, one invocation performs
both native MT5 Strategy Tester runs, each with an independent evidence
directory, and an impartial broker-deal/after-cost comparison:

```powershell
.\gold_robot\research\RunNativeV5Challenge.ps1 `
  -PlanPath "gold_robot\reports_local\FROZEN_STUDY.json"
```

Both arms use `RunAutomaticTester.ps1` on the same dates:
`ADAPTIVE_V4` (unchanged champion) and
`ADAPTIVE_V5_VETO` (one precisely frozen selection veto).
The runner archives native MT5 HTML, broker deals, position and stop
forensics, ten-trade review and `OPEN_RESULTS.json`. A new study output
directory is required; old evidence is never overwritten.

## Guardrails in code

V5 is OFF by default and can run only inside the MT5 Strategy Tester,
with EntryStyle=7 (adaptive), M15, confirmed V3 market context and V4 router.
Invalid styles, market regimes, dates, source/plan hashes, real/demo mode
or contaminated champion configurations are rejected.

The immutable self-hashed plan binds the original research report hash,
original attribution hash, original originating broker-exit timestamp,
frozen intervention, future date window, and canonical source-manifest
SHA256. A checksum detects accidental change; it is NOT a digital
signature or proof against someone who deliberately forges all inputs.

The comparator rejects a different broker symbol, deposit, tick model,
timeframe, selected strategy, native variant, future dates, source hash
or altered veto. It independently re-reads the complete per-position
broker-deal attribution for both actual simulations; simply subtracting
the historical PnL of stopped trades from the baseline is prohibited.

Even when the native V5 challenger appears to improve net USD, this is
**descriptive research**, NOT statistical evidence of an economic edge.
It is NOT validated unless an independent professional acceptance audit
examines period-level uncertainty, multiple comparisons, actual spread,
commissions, slippage, unfilled pending orders, floating equity drawdown,
original MT5 HTML, deal/tick provenance and $100/$200 account lot
feasibility. The comparator explicitly reports those gaps and
`auto_promote=false`, `real_orders_permitted=false`, `LIVE LOCKED`.

A low trade count or a veto that never actually selected a matching
candidate gives `NO_GO`. No automatic parameter, strategy or risk
changes can ever be authorized by the study code.
