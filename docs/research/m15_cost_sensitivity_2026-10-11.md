# M15 cost sensitivity — what measured broker costs could change — 2026-10-11

Status: diagnostic. Read-only from the saved final evidence
(`data/evidence/longhistory/intraday_research_final.json`). No re-selection, no new
holdout run, no tuning. Costs are **ASSUMED** in every number below. No edge is claimed.

## Engine values (holdout 2020-01-01 to 2025-02-28, selected candidates)

| Group | Candidate | Net @ base | Round turns | Break-even cost × (engine) | Zero-cost P&L |
|---|---|---:|---:|---:|---:|
| ma_cross | `ma_32_128_atr3` | +1,092.55 | 1,154 | **1.157×** | +11,454 |
| donchian | `donchian_384_192_atr3` | +288.09 | 231 | **1.215×** | +1,739 |
| session_breakout | `session_brk_b0` | −4,467.03 | 1,265 | **0.163×** | +1,223 |
| volatility_expansion | `rexp_k10_h16` | −9,938.70 | 8,162 | none: negative at zero cost | −3,450 |

Break-even × is the cost multiplier at which holdout net P&L crosses zero. It comes from
the engine's own search (`runner.break_even_multiplier`), which re-runs the path at scaled
costs. Base assumed cost: 6.077 bps per round turn (`cost_base.round_turn_bps_at_1300`),
plus the commission and spread model in `cost_base`.

## What this means

1. **Cost-free P&L is not the base gross.** For `ma_cross` the zero-cost holdout P&L is
   +11,454, while the base "gross" (net + cost) is +8,655. Costs change position sizing
   and stop triggers, so gross is not invariant to cost. A simple gross-minus-cost
   calculation therefore misstates the result. Any cost re-assessment must re-run the
   engine. Do not reconstruct it from the table.
2. **Measured costs can only lower the two candidates that have positive holdout P&L.**
   `ma_cross` and `donchian` break even at about 1.16× and 1.22× the assumed cost. If the
   measured all-in round-turn cost is higher than that, the holdout P&L turns negative. If it
   is lower, the holdout P&L stays positive. Neither outcome validates an edge. The
   walk-forward 2010–2019 result is negative for both (Sharpe −0.717 and −0.247), and both
   pass 2 of 7 gates.
3. **`session_breakout` and `volatility_expansion` are not rescued by cheaper costs.**
   `session_breakout` is already negative at 0.16× the assumed cost, so it would need costs
   about 84% cheaper than assumed. `volatility_expansion` is negative even at zero cost.
4. **Buy-and-hold on the same holdout is +8,795.66** (Sharpe 0.860, max drawdown −21.9%).
   The candidates that survive costs still do not beat it.

## What would be needed to change the verdict

- Measured all-in round-turn costs from the Windows MT5 DEMO terminal
  (`qts demo cost-check --record`, which reads historical deals and commission/swap/fee
  fields; currently blocked, see `m15_second_source_check_2026-10-11.md`).
- Re-run the frozen protocol with those measured costs. That is a new holdout use, so it
  needs a new preregistration. Do not tune on `2020–2025`.
- Fresh data beyond the reused holdout, with an independent source (none verified).

## Not claimed

No validated edge. The verdict `NO_VALIDATED_EDGE` stands for both the daily and the
intraday M15 studies. The measured costs needed to test it have not been obtained.
