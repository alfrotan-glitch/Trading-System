# QTS anticipatory pre-confirmation scalping (2026-10-23)

**Objective:** Detect a potential early setup before a conventional breakout
confirmation, without claiming knowledge of the future low, high, or outcome.

**Research-only candidate:** `qts.research.scalp_regimes.propose_anticipatory_entry`
uses 34 completed M1 mid-close observations. A fixed 20-bar prior range,
recent-versus-earlier absolute change compression, proximity to the still-unbroken
range boundary, and three consecutive directional closes can propose BUY or
SELL **while price remains inside the range**. The movement proxy is observed
range geometry, **not a calibrated probability or expected return**.
No candle-close hindsight from the following minute is used.

**Separation:** The existing confirmed strategy and its semantics are
unchanged. `AnticipatoryScalpProvider` has a distinct strategy identity,
requires a frozen cost-aware exit policy, and is **not** eligible in the
forward-validation registry. No MT5 order paths are unlocked.

**Comparison:** `scripts/run_xauusd_mt5_regime_scalp_replay.py` now runs
confirmed and anticipatory candidates independently on the exact same
manifest-verified MT5 discovery-only interval; entry occurs no earlier than
the next observed minute's executable bid/ask. It accounts for modeled
commission and slippage, intrabar stop uncertainty, and gaps. Compare trade
count, net estimated bps, win rate, and drawdown. Do not select an apparently
better variant and treat the reused historical window as an independent holdout.

**Limits:** Detection of a precursor is not prediction certainty. Early
entries may have a worse hit rate and unfavorable selection, even when the
entry price is nearer a local extreme. The success metric is realized,
cost-adjusted performance, not early timing alone. Raw private MT5 data and
detailed trade ledger stay on the owner machine.
