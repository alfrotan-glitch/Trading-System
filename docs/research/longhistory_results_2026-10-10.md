# Long-history XAUUSD research — results and verdict

**Date:** 2026-10-10 · **Prereg:** `LH-XAUUSD-D1-2026-10-10` (`preregistration_longhistory_2026-10-10.md`, committed before the final stage)
**Tables (generated from the result record):** `longhistory_results_tables_2026-10-10.md`
**Evidence:** `data/evidence/longhistory/research_final.json`, `data_quality.json`, `source_manifest.json`
**Data:** `longhistory_data_provenance_2026-10-10.md` · **Method survey:** `longhistory_method_survey_2026-10-10.md`

---

## Verdict

**NO_VALIDATED_EDGE.** No candidate passes all seven gates (G1–G7). Claim: **none**.

Two further points bind the verdict:

1. Costs are **ASSUMED**. Nothing in this repository is measured, so even a passing result would be a candidate for forward observation, not an edge claim (`CLAIM_ELIGIBLE_BASES = {MEASURED}`).
2. **Buy-and-hold beat every candidate** on the holdout and in the walk-forward years. The strategies were mostly out of the market during the 2020–2025 gold rally.

Nothing was promoted, and no order path, DEMO/LIVE state, risk limit or authorization was changed.

## What was tested

- **Data:** 5,281 complete daily bars, 2004-06-11 → 2025-02-28, from the BaseMax 15-minute export, converted to UTC. This is one third-party quote stream. Yuan, ejtraderLabs and BaseMax agree to cents, so they cannot corroborate prices independently (`longhistory_data_provenance_2026-10-10.md` §4).
- **Candidates:** 25 configurations in six family groups, plus one Bollinger control. All 26 count as trials (N = 26) for the Deflated Sharpe Ratio.
- **Protocol:** walk-forward over 2010–2019 with per-year selection; an untouched holdout 2020-01 → 2025-02 with selection frozen at 2019-12-31; cost stress at 2× and 3×; break-even cost; Holm correction across the six groups; mechanical regimes; a Dukascopy replicate (2025-08 → 2026-09).
- **Execution:** next-open fills, protective stops on daily ranges, no leverage, costs of about 6 bps per round turn (3 bps spread, 1 bp slippage per side, USD 7 per lot per side). All of these are assumptions.

## Result 1 — the holdout (2020-01 → 2025-02)

| Group | Selected | Net USD | Sharpe | 95% CI | Round turns | Net @2× | Net @3× | Break-even cost× |
|---|---|---:|---:|---|---:|---:|---:|---|
| volatility_expansion | rexp_k10_h3 | +673 | 0.39 | [−0.49, 1.24] | 134 | +381 | +97 | 3.3 |
| ma_cross | ma_20_100_atr3 | +530 | 0.30 | [−0.55, 1.16] | 14 | +506 | +482 | 23.7 |
| donchian | donchian_55_20_atr2 | +160 | 0.09 | [−0.75, 0.93] | 19 | +117 | +75 | 4.8 |
| trend_gated | gated_er60_025 | −320 | −0.28 | [−0.96, 0.49] | 9 | −333 | −346 | negative at zero cost |
| tsmom | tsmom_L126 | −379 | −0.01 | [−0.81, 0.86] | 13 | −448 | −517 | negative at zero cost |
| mean_reversion | rsi2_t10_sma200 | −841 | −0.40 | [−1.07, 0.39] | 47 | −1,010 | −1,175 | negative at zero cost |
| **buy_and_hold_long** (reference) | 1.0× long | **+8,796** | **0.86** | — | 1 | +8,785 | — | — |

Every Holm-adjusted p-value is 1.00. The best one-sided bootstrap p-value for a positive mean daily return is 0.19 (`rexp_k10_h3`). Every 95% Sharpe interval contains zero.

## Result 2 — walk-forward 2010–2019

Each row is the selected candidate in each year, chained across the ten years.

| Group | WF Sharpe | Positive years | Chained return |
|---|---:|---:|---:|
| ma_cross | 0.17 | 6/10 | +5.9% |
| donchian | 0.14 | 5/10 | +5.7% |
| volatility_expansion | 0.01 | 5/10 | −0.1% |
| tsmom | −0.07 | 3/10 | −10.9% |
| mean_reversion | −0.33 | 5/10 | −11.2% |
| trend_gated | 0.54 | 2/10 (2 years traded) | +2.8% |
| **buy_and_hold_long** | **0.27** | — | **+34.4%** |

Buy-and-hold's walk-forward Sharpe (0.27) is exceeded only by `trend_gated` (0.54), which traded in two of ten years. Its chained return is about six times that of the best-returning strategy (`ma_cross`, +5.9%).

## Result 3 — gates

| Group | G1 holdout + | G2 2× cost + | G3 WF Sharpe & years | G4 Holm p | G5 DSR ≥ 0.95 | G6 ≥ 100 OOS turns | G7 regimes | Passes |
|---|---|---|---|---|---|---|---|---|
| ma_cross (`ma_20_100_atr3`) | PASS | PASS | PASS | FAIL | FAIL (0.12) | FAIL (61) | PASS | no |
| volatility_expansion (`rexp_k10_h3`) | PASS | PASS | FAIL | FAIL | FAIL (0.07) | PASS (375) | PASS | no |
| donchian (`donchian_55_20_atr2`) | PASS | PASS | FAIL | FAIL | FAIL (0.06) | FAIL (69) | FAIL | no |
| tsmom, trend_gated, mean_reversion | FAIL | FAIL | FAIL | FAIL | FAIL | mixed | FAIL | no |

## Strongest candidates and their blockers

**1. `ma_20_100_atr3` (SMA 20/100 stop-and-reverse, 3-ATR stop).** Passes four of seven gates, including the holdout, double cost, walk-forward and regime gates. Blockers:

- **G5, DSR 0.12.** After deflating for 26 trials, a holdout Sharpe of 0.30 (walk-forward 0.17) is consistent with selection noise.
- **G6, power.** Only 61 out-of-sample round turns in roughly 15 years. The rule cannot be tested with confidence.
- **G4.** Its bootstrap p-value is not significant after Holm correction.
- **Opportunity cost.** It returned +$530 on the holdout against +$8,796 for buy-and-hold.

**2. `rexp_k10_h3` (volatility expansion: body > 1.0 × ATR20, 3-bar hold).** Passes four gates: holdout, double cost, regimes and trade count. It has the most trades (375 out-of-sample), the largest holdout net (+$673), and the best holdout Sharpe (0.39). Blockers:

- **G3, walk-forward.** Only five of ten years were positive, against a required six.
- **G5, DSR 0.07.**
- **G4.** Not significant.
- **Cost sensitivity.** Break-even cost is 3.3× assumed. At 3× it is +$97, so the margin is thin, and the costs are unmeasured.
- **Replicate.** On the Dukascopy series it made +$335 on 26 round turns. That is one year, a single candidate chosen after the fact, and the replicate cannot rescue a failed gate. It is recorded as a watch item only.

**3. `donchian_55_20_atr2`.** Passes holdout gates only. Its UP_HIVOL regime lost −$1,717 out of sample, so the trend-breakout edge is concentrated in low-volatility uptrends.

## What the regime attribution shows

Out-of-sample net P&L by mechanical regime (`longhistory_results_tables_2026-10-10.md`):

- Five of six groups made money in UP_LOWVOL, and four of six lost money in UP_HIVOL. Donchian lost −$1,717 in UP_HIVOL and made +$2,290 in UP_LOWVOL. `ma_cross` and `mean_reversion` are the exceptions, with gains in UP_HIVOL.
- The volatility-expansion family is the exception: it was positive in three of four regimes, but its UP_HIVOL loss is −$828.
- Mean reversion lost in UP_LOWVOL (−$1,142) and DOWN_LOWVOL (−$713), so it is not a regime-robust reversal rule on this sample.

## Why buy-and-hold wins here

Gold closed at $1,529 on the first holdout day and at $2,859 on the last (2020-01 → 2025-02). Zero-cost buy-and-hold made +88%. The strategies are timing overlays with exposure from 13% (`mean_reversion`) to 98% (`tsmom`). The best-performing holdout candidate, `rexp_k10_h3`, was 35% exposed. Costs were a large share of its gross P&L: $290 of $963 gross. I did not decompose the gap further. The candidates' exposure alone does not explain it, since `tsmom` was 98% exposed and still lost. Stop-outs, whipsaws and costs are the plausible remaining causes, and each would need its own test.

This is not a verdict that gold is a good investment. It is a verdict that these rules, on this sample, do not add timing value over holding gold, and that the strategies' costs and stop-outs cost more than they gained.

## Replicate (Dukascopy, 2025-08 → 2026-09, informational)

| Group | Candidate | Net USD | Sharpe | Round turns |
|---|---|---:|---:|---:|
| volatility_expansion | rexp_k10_h3 | +335 | 0.70 | 26 |
| mean_reversion | rsi2_t10_sma200 | +16 | 0.09 | 4 |
| donchian | donchian_55_20_atr2 | −297 | −1.33 | 3 |
| trend_gated | gated_er60_025 | −159 | −0.95 | 2 |
| ma_cross, tsmom | — | not evaluable under the pre-registered warm-up rule (first valid signal after 25% of the window) | — | — |
| **buy_and_hold_long** | 1.0× long | **+2,647** | **0.90** | 1 |

The replicate is one year and includes a strong gold move, so it is not a fresh test. It does not change the verdict. `ma_cross` and `tsmom` were not evaluable under the pre-registered rule, because their first valid signal falls after 25% of the replicate window.

## Integrity checks performed

- **Causality.** Every candidate's signals at bar `t` are identical when computed on data truncated after `t`, at five cut points (26/26 pass). A deliberately leaky signal is caught.
- **Warm-up.** ATR and RSI(2) converge regardless of where the history starts.
- **Accounting.** For every candidate and window, the trade ledger sums exactly to the change in equity (maximum difference 0.0 USD).
- **Reproducibility.** The final stage ran twice; the strategy and gate sections are identical between runs. The runner, protocol and processed-data hashes are recorded.
- **Clock.** After the GMT+2/+3 conversion, BaseMax peaks at zero shift against the UTC Yuan series in every window.

## Limits

1. The 2004–2025 prices are one unverified third-party quote stream. The upstream vendor and the Kaggle licence could not be checked from this sandbox.
2. All costs are assumed. Break-even multiples are the only sensitivity offered, and they do not replace a measured cost.
3. Daily bars, with stops on daily ranges. Intraday order of events is unknown.
4. The replicate is the Dukascopy series, which earlier research already used and which has no upstream licence.
5. The strategies are long/short with no leverage. Gold may reward a different exposure profile, which this study did not test.
6. Findings are for XAUUSD over this sample. They do not generalise to other instruments.

## Impact on the product and the DEMO policy

- **Nothing was integrated into the execution path.** The research package is tooling only.
- The DEMO policy `DEMO-XAUUSD-TREND-TSMOM-V1` (registered 2026-10-07) runs an EMA 12/48 signal on 15-minute bars. This study tested daily SMA, Donchian and momentum rules, not that policy. Its economics are not confirmed or refuted here. It remains `ELIGIBLE_DIAGNOSTIC` and is not promoted.
- Nothing here justifies changing a risk limit or enabling LIVE. `LIVE_LOCKED` and `DEMO_EXECUTION` are unchanged.

## Blockers to a claim

| Blocker | What resolves it | Who / where |
|---|---|---|
| Broker M15 bar depth is UNKNOWN; MT5 Python package is Windows-only | `qts data mt5-depth --json-out data\evidence\mt5_depth_probe.json` on the Windows terminal | Operator, Windows host |
| Broker costs are ASSUMED | `qts demo cost-check --record` on the Windows terminal, then rerun this study with measured costs | Operator, Windows host |
| No second, licensed, independent price history for 2004–2025 | A licensed vendor feed with a verifiable licence. None is legally available from this sandbox | Operator decision |
| Upstream licence of the Dukascopy mirror is absent | Confirm the licence or obtain the feed directly | Operator decision |
| G6 (trade count) limits daily strategies | Test intraday families on the 15-minute history in a new preregistration (for example, the DEMO EMA 12/48 policy) | Next research cycle |

## Reproduce

```bash
python scripts/fetch_longhistory_sources.py          # pinned, SHA-256-verified fetch (github.com only)
python scripts/build_longhistory_dataset.py          # UTC normalisation, quality evidence
python scripts/run_longhistory_research.py --stage final
pytest tests/unit/test_longhistory_research.py -q
```
