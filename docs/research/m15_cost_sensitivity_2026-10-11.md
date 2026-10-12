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
2. **Proportional (`bps`) vs. fixed-dollar (`$/oz`) spread modeling (`CostModel.from_price_units`).**
   `COST_BASE` specifies `spread_bps = 3.0`, `slippage_bps = 1.0`/side (`2.0 bps` round-turn),
   plus `$7.00/lot/side` (`$0.14/oz` round-turn) ECN commission. At `$2,000–$2,800/oz` during
   the 2020–2025 holdout, `3.0 bps` corresponds to **`$0.60–$0.84/oz` spread** (matching the
   95th-percentile macro-event spike spread `3.037 bps` in Dukascopy CPI/FOMC/NFP ticks),
   whereas the WM Markets 730d MT5 tick archive (`139,930,971` ticks) measures a median spread
   of **`$0.24/oz`** (`0.720 bps` mean; `$0.39/oz` median during the `raw_hour 0..1` reopen hour).
   Re-running the exact engine (`run_plan`) on the 2020–2025 holdout across these cost regimes
   yields:

| Cost Regime | Spread | Slippage / side | Comm / lot / side | `ma_32_128_atr3` Net ($) | `ma_32_128_atr3` Sharpe | `donchian_384_192_atr3` Net ($) | `donchian_384_192_atr3` Sharpe | `session_brk_b0` Net ($) | `rexp_k10_h16` Net ($) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| **1. Protocol `COST_BASE` (`ASSUMED`)** | `3.000 bps` | `1.00 bps` | `$7.00` | +1,092.55 | +0.2136 | +288.09 | +0.1040 | −4,467.03 | −9,938.70 |
| **2. Canonical `xauusd_default` (`ASSUMED`)** | `$0.30/oz` | `$0.10/oz` | `$0.00` | +5,897.62 | +0.7228 | +1,055.95 | +0.2420 | −1,850.87 | −9,210.22 |
| **3. WM Measured Spread + CFD (`MIXED`)** | `$0.24/oz` (`MEASURED`) | `$0.10/oz` (`ASSUMED`) | `$0.00` (`ASSUMED`) | +6,479.89 | +0.7739 | +1,135.72 | +0.2558 | −1,531.76 | −8,981.96 |
| **4. WM Measured Spread + ECN (`MIXED`)** | `$0.24/oz` (`MEASURED`) | `$0.10/oz` (`ASSUMED`) | `$7.00` (`ASSUMED`) | +5,153.13 | +0.6548 | +950.47 | +0.2236 | −2,257.72 | −9,437.02 |
| **5. WM Reopen-Hour Stress (`MIXED`)** | `$0.39/oz` (`MEASURED`) | `$0.15/oz` (`ASSUMED`) | `$7.00` (`ASSUMED`) | +3,043.86 | +0.4426 | +627.28 | +0.1662 | −3,402.83 | −9,804.54 |
| **6. Dukascopy Event p50 (`MIXED`)** | `1.732 bps` (`MEASURED`) | `1.00 bps` (`ASSUMED`) | `$7.00` (`ASSUMED`) | +2,836.45 | +0.4199 | +592.89 | +0.1599 | −3,528.72 | −9,827.50 |
| **7. Dukascopy Event p95 (`MIXED`)** | `3.037 bps` (`MEASURED`) | `1.00 bps` (`ASSUMED`) | `$7.00` (`ASSUMED`) | +1,045.39 | +0.2076 | +279.32 | +0.1024 | −4,492.27 | −9,940.52 |

3. **Even under tighter measured spreads, no candidate validates an edge.**
   `ma_cross` and `donchian` break even at about 1.16× and 1.22× `COST_BASE`. Under the
   WM Markets measured median spread (`$0.24/oz` + `$0.10/oz` assumed slippage), `ma_32_128_atr3`
   rises to `+$6,479.89` (`Sharpe +0.7739`) with `$0` commission or `+$5,153.13` (`Sharpe +0.6548`)
   with `$7/lot/side` commission, but **still trails passive buy-and-hold (`+$8,795.66`,
   `Sharpe +0.8597`, max drawdown `−21.91%` vs. `−31.64%`)**, and its 2010–2019 walk-forward
   composite remains negative (Sharpe −0.717 and −0.247; both pass only 2 of 7 gates).
4. **`session_breakout` and `volatility_expansion` are not rescued by cheaper costs.**
   `session_breakout` is already negative at 0.16× `COST_BASE` (and remains `−$1,531.76` under
   Regime 3). `volatility_expansion` is negative even at zero cost (`−$3,450`).
5. **Buy-and-hold on the same holdout is +8,795.66** (Sharpe 0.860, max drawdown −21.9%).
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
