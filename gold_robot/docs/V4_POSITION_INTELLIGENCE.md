# QTS Gold — Per-position evidence that a trader and strategy designer can trust

**2026-11-01 | Strategy Tester research only | LIVE LOCKED | profitable edge NOT validated.**

## What the operator needs

When the adaptive router chooses SMC instead of a retest, the final
position's native broker history must reveal **which strategy and
which already-confirmed market regime** triggered the pending order.
An aggregate `EntryStyle=7` MT5 report is not enough: without attribution
one profitable sub-strategy can conceal several losing ones.

V4 now writes a short broker order identity **before `OrderCheck`**:

`QTSV4-S8-R2` = the completed-bar V4 router chose native strategy 8
(SMC FVG/OB) while the confirmed regime was 2 (TREND).

Styles supported: 0 former-stop, 1 retest, 2 break/retest, 3 sweep/reclaim,
4 trend impulse, 5 range rejection, 6 inside breakout, 8 SMC.
Regimes are 0 RANGE, 1 TRANSITION and 2 TREND. Router 7 is **not** an
entry strategy; separate M1 scalp 9 is **not** disguised as an M15 candidate.

The broker can edit order comments. Therefore **only an exact original
order tag counts**. No tag, unknown strategy/regime, truncated comment or
unreconciled broker deal means *incomplete evidence*. We do not infer
the sub-strategy from the outcome, a visually similar chart or a
contemporaneous indicator recomputed after the trade.

## Automatic workflow

When `RunAutomaticTester.ps1 -OnlyStyles 7 -ResearchVariant ADAPTIVE_V4`
completes native MT5 real-tick research, it obtains `QTS_TRADE_BY_TRADE.json`
from the original broker deals via `BuildTradeForensics.ps1`, then
automatically invokes `v4_position_attribution.py`. This needs Python 3
on the Windows research machine and creates:

`QTS_V4_POSITION_ATTRIBUTION.json`

Any missing attribution causes the research runner to fail as incomplete,
rather than counting a style-7 PnL report as independently validated.
No broker order is submitted by the Python or PowerShell analysis.

## Per-trade facts, and what they cannot tell us

Each eligible completed broker position preserves original strategy ID,
regime, side, broker position ID, entry/exit timestamps, entry, initial
SL/TP, lot, exit reason, native gross PnL, fees, swap/commission,
net PnL and exact exit-deal identity. Multiple exit legs can be accepted
only if broker volumes reconcile and the forensics labels
`COMPLETE_MULTI_EXIT`; incomplete/reversed or ambiguous histories
cause an evidence gap.

The report gives independent per-strategy and per-regime totals:
closed positions, net broker PnL, costs, win/loss after an **additional
hypothetical $10 per lot**, stop-vs-target counts and mean stressed net
per position. It also reports the maximum **closed-deal realised PnL
drawdown**, expressly **not intratrade equity drawdown**.

A stop loss **does not by itself identify a bad signal**. A profitable TP
**does not prove a good signal**. An original stop/target can change;
a `DEAL_REASON_SL` does not reveal the entire bid/ask path.
The existing independent post-stop tick-replay research is still
required before saying a stopped trade recovered to its original TP.
When full bid/ask ticks are missing, post-stop recovery and MAE/MFE
are explicitly `UNKNOWN`. Never manufacture this information from
M15 OHLC highs/lows.

## Strategy-designer decision rules

Use this audit to form **preregistered hypotheses**, not self-tuning:
identify losing regime/style combinations; check actual initial stop
room, spread, latency and slippage; evaluate whether a rejected setup
would have met its limit fill; compare cohorts on unseen complete months,
not cherry-picked trades. A change in risk thresholds, candidate
ranking or stop mechanics starts a new independent holdout clock.

Don't automatically disable a strategy merely because it had a short
run of losses: small samples produce unstable estimates. Don't
automatically increase lot after wins or stops. Use identical
WMMarkets tick contracts, deposit, model and fees before attributing
an advantage to the router rather than execution circumstances.

## Acceptance and mandatory limits

These are immutable research facts, NOT any of the following:
- A guaranteed profit, win probability, or calibrated score.
- An independently validated positive after-cost trading edge.
- Proof of the native Windows EX5 compile, real-world WMMarkets order
  execution costs, broker identity or unmodified unattended operation.
- Permission to send real-money orders.

The EA's default remains OFF; V4 is tester-only. Python-generated
reports set `live=LOCKED`, `edge_validated=false`, and
`can_autotune_or_promote=false`. The next critical stage is an actual
native Windows MetaEditor compile, same-period baseline/V4 real-tick
run and post-stop bid/ask reconciliation at the target broker.
