# QTS Gold | Frozen Dual-Strategy Research Selection Protocol

**Status: RESEARCH ONLY. LIVE LOCKED. NO PROFITABLE EDGE APPROVAL.**

## Scope

Compare independent broker-native MT5 M15 real-tick Strategy Tester runs on
XAUUSD@ at the same simulated equity, source, terminal, signal timeframe,
fees, tick history and test dates.

- `DUAL_BOTH`, mode 1: Retest/Sweep, both sides, abstain on two eligible candidates.
- `DUAL_DIRECTIONAL`, mode 2: BUY Retest / SELL Sweep, selected after observing
  historical behavior. **October 2026 is NOT an independent holdout.**
- `DUAL_QUALITY`, mode 3: all four style/direction combinations remain eligible.
  For two simultaneously executable **same-side** candidates, compare a frozen,
  non-PnL-derived score and choose only if the score gap is at least 0.15 R
  units; otherwise abstain. For opposing directions always abstain.

Mode 3's fixed score is

```
score = (gross_target_distance - quote_spread - adverse_stop_slip)
        / (initial_stop_distance + quote_spread + adverse_stop_slip)
        - 0.05 * (entry_limit_distance_from_quote_mid / closed_bar_ATR)
```

The score excludes unverified broker commissions and cannot predict fills.
The chosen setup still must satisfy all existing broker, margin, stop/target,
risk, session and exposure validations. No live/demo-forward change is made.

## What actually happened in the already-seen October 2026 sample

Native sample: 2,024 M15 closed bars and 114 raw signals in **each** arm.
Mode 1: 20 completed trades, +USD 58.78; Mode 2: 13, +USD 139.47.
Only TWO closed bars had two executable candidates, whereas SEVEN bars
had simultaneous raw signals. Raw signals are not executable pending orders.
Every recorded charge was zero. A BUY was filled with its originally
assigned SL on the wrong side of entry. These facts require execution
forensics, not parameter-fitting or automatic promotion.

Mode 2 is therefore the **provisional historical leader**, not the
best proven trading strategy. Neither mode has an independently validated edge.

## Frozen selection criteria — no cherry-picking

1. Verify `OPEN_RESULTS.json` declares completed targeted Style 7; its native
   report affirms exact dual mode, real ticks, M15, start/end, and the same
   source, compiled EX5 hash, account deposit and symbol across arms.
2. Verify `QTS_DUAL_OPPORTUNITY_SUMMARY.json` reports two independent style
   observations for every closed bar and no ledger validation gaps.
3. Independently reconcile closed broker deals and original pending-order
   strategy comments. A submitted LIMIT does not imply a fill.
4. Run all preregistered arms over **the same unseen future calendar periods**
   after 2026-11-03. Do not recycle October as an independent holdout.
5. Require at least three nonoverlapping forward periods, at least 100
   completed positions **per arm** across them, and adequate signal/regime
   coverage. These are minimum review gates, not proof by themselves.
6. Prefer positive **after-cost** results and smaller native equity drawdown
   that persist across separate periods. Include conservative slippage,
   commissions, swaps, lot-size changes and execution anomalies, and
   uncertainty intervals for profit factor and returns.
7. Stress-test gaps, abnormal stop fills and exposure concurrency; refuse
   variants whose stops or economics cannot be reconciled. Do not infer
   missed-target outcomes without tick-path/order evidence.
8. If none qualifies, select **NO APPROVED STRATEGY**, not the largest
   in-sample profit or win rate. Manual, independent review is necessary
   before considering any further permission.

The default `TesterDualStrategyMode=0` remains unchanged. No native
research script can enable real-money trading. Demo forward is separately
authorization-gated. Auto-learning from in-sample losses to place real orders
is deliberately NOT implemented.
