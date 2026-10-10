# Method survey — applicable techniques from public implementations and papers

**Date:** 2026-10-10 · **Prereg:** `LH-XAUUSD-D1-2026-10-10`
**Scope:** what was studied, what was adopted, what was adapted, and what was rejected. Code was read from shallow clones at the commits listed. No code was copied from GPL projects.

## 1. Reference implementations studied

| Project | Licence | Read | Used as |
|---|---|---|---|
| QuantConnect LEAN (`QuantConnect/Lean`) | Apache-2.0 | slippage models (`ConstantSlippageModel`, `VolumeShareSlippageModel`), fee models (`ConstantFeeModel`, `InteractiveBrokersFeeModel`, `FxcmFeeModel`) | cost-model structure, fill convention |
| Microsoft Qlib (`microsoft/qlib`) | MIT | `contrib/evaluate.py` `risk_analysis`; `workflow/task/gen.py` `RollingGen` (with `trunc_days`); `TopkDropoutStrategy` | walk-forward design, annualisation conventions |
| Freqtrade (`freqtrade/freqtrade`) | **GPL-3.0** | `optimize/analysis/lookahead*.py` and `recursive*.py`, plus the user docs | **concept only**; the two bias checks were re-implemented independently in `checks.py` |

## 2. Techniques adopted

| Technique | Source | Where in QTS | Why |
|---|---|---|---|
| **Next-open execution**: a signal at close `t` fills at open `t+1`. Market-on-open convention. | LEAN `ConstantSlippageModel` ("market on open orders fill at the bar open"); standard practice | `engine.py` step 2 | Removes the most common same-bar fill bias |
| **Fee and slippage as separate, named models**, every component tagged with its basis (ASSUMED/MEASURED) | LEAN fee/slippage split | `engine.CostModel`, `protocol.COST_BASE` | Lets measured broker costs replace assumptions without changing the engine |
| **Volume- or size-dependent slippage** (considered) | LEAN `VolumeShareSlippageModel` (impact ∝ (order/volume)²) | not used | Gold tick volume is not traded volume. Impact is unmeasurable here, so a flat multiplier stress (2×, 3×) is used instead |
| **Causality check**: truncate the data and require identical signals at every earlier bar | Freqtrade `lookahead-analysis` (concept) | `checks.truncation_check`; 26/26 candidates pass | Detects use of future bars; tested on a deliberately leaky signal, which is caught |
| **Warm-up / start-point invariance check** for recursive indicators | Freqtrade `recursive-analysis` (concept) | `checks.warmup_check` on ATR and RSI | Confirms EWM indicators converge, so results do not depend on the arbitrary start |
| **Truncate training data at the window boundary** so the test window never sees later data | Qlib `RollingGen(trunc_days)` | `runner.select_per_group` and `window_positions` | Same idea: nothing after the boundary is visible during selection |
| **Annualised Sharpe on daily returns with flat days included**; drawdown from the equity peak | Qlib `risk_analysis` (sum mode, `max_drawdown`) | `stats.sharpe`, `stats.max_drawdown` | Qlib's `sum` mode was chosen over `product` for the daily Sharpe. Both are documented in the code |
| **Deflated Sharpe Ratio** with the number of trials `N` | Bailey & López de Prado (2014) | reuses `qts.validation.metrics.deflated_sharpe_ratio` | Corrects for selection among 26 configurations |
| **Holm step-down** across hypothesis families | Holm (1979); existing `impulse/statistics.py` | `stats.holm` | Family-wise error control across six groups |
| **Stationary/circular block bootstrap** for Sharpe intervals and mean-return p-values | Politis & Romano (1994), standard | `stats.circular_block_bootstrap` | Keeps short-range dependence in daily returns |

## 3. Techniques considered and rejected for this study

| Technique | Source | Reason rejected |
|---|---|---|
| Cross-sectional TopK-dropout portfolio | Qlib `TopkDropoutStrategy` | Needs many instruments. XAUUSD alone is a single series |
| Probability of Backtest Overfitting (CSCV) | Bailey, Borwein, López de Prado, Zhu (2015/2017) | Useful, but needs a complete trial matrix across many sub-samples. Deferred. DSR with `N` is used instead |
| Hansen SPA / White's Reality Check | existing `qts/research/statistical.py` | Available, but the Holm + DSR + holdout design is already stricter for six pre-registered hypotheses. Not added to avoid redundant gates |
| Intraday stop simulation | — | Needs intraday stop-path data we do not have; daily high/low stops are stated as a limit |
| Leverage above 1× | — | Would change the risk profile. Position cap is 1.0× equity |

## 4. Applicable research mechanisms (from the literature)

- **Time-series momentum** across asset classes, persistence of 1–12 months, partial reversal beyond that (Moskowitz, Ooi & Pedersen 2012, *Journal of Financial Economics* 104(2), 228–250). Basis for the `tsmom` group.
- **Trend following over a century and 67 markets**, with a simple moving-average or breakout rule that did not depend on one era (Hurst, Ooi & Pedersen 2017, *Journal of Portfolio Management* 44(1), 15–29). The 2017 paper, not the 2012 summary, is the basis for trend-family expectations.
- **Moving-average and trading-range breakout rules** showed predictive power on the Dow Jones 1897–1986 with bootstrap tests (Brock, Lakonishok & LeBaron 1992, *Journal of Finance* 47, 1731–1764). Later replications show the effect is unstable (Sullivan, Timmermann & White 1999 is the canonical data-snooping study). Basis for `ma_cross` and `donchian`.
- **Commodity momentum** in futures: momentum profits exist across commodity futures, and they buy backwardated and sell contangoed contracts (Miffre & Rallis 2007, *Journal of Banking & Finance* 31(6), 1863–1886). Gold is a commodity but spot XAUUSD has no futures term structure here, so the carry component is not testable.
- **Selection bias and non-normal returns**: the Deflated Sharpe Ratio (Bailey & López de Prado 2014, SSRN 2460551). Applied with `N = 26`.

Public evidence supports the mechanisms, not this implementation. Each family therefore has to clear the gates in the prereg against assumed costs.

## 5. Gaps this study does not close

- Measured broker costs and spreads (none exist in this repo; MT5 depth is still UNKNOWN).
- An independent second price source for 2004–2025 (see the provenance document).
- Intraday order-of-events, so stops are approximated on daily ranges.
- Carry or term structure for gold.

## 6. References

- Bailey, D. H., & López de Prado, M. (2014). The deflated Sharpe ratio: correcting for selection bias, backtest overfitting and non-normality. *Journal of Portfolio Management*, 40(5), 94–107. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics*, 6, 65–70.
- Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap. *Journal of the American Statistical Association*, 89, 1303–1313.
- Sullivan, R., Timmermann, A., & White, H. (1999). Data-snooping, technical trading rule performance, and the bootstrap. *Journal of Finance*, 54, 1647–1691.
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2015). The probability of backtest overfitting. https://www.semanticscholar.org/paper/The-Probability-of-Backtest-Overfitting-Bailey-Borwein/b1233b4f5384f003e85c2e0eec1a2dfc08f624c5
- Brock, W., Lakonishok, J., & LeBaron, B. (1992). Simple technical trading rules and the stochastic properties of stock returns. *Journal of Finance*, 47, 1731–1764.
- Hurst, B., Ooi, Y. H., & Pedersen, L. H. (2017). A century of evidence on trend-following investing. *Journal of Portfolio Management*, 44(1), 15–29.
- Miffre, J., & Rallis, G. (2007). Momentum strategies in commodity futures markets. *Journal of Banking & Finance*, 31(6), 1863–1886.
- Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). Time series momentum. *Journal of Financial Economics*, 104(2), 228–250. https://doi.org/10.1016/j.jfineco.2011.11.003
- QuantConnect LEAN, Apache-2.0. https://github.com/QuantConnect/Lean (fee and slippage models studied)
- Microsoft Qlib, MIT. https://github.com/microsoft/qlib (`risk_analysis`, `RollingGen`)
- Freqtrade, GPL-3.0. https://github.com/freqtrade/freqtrade (lookahead and recursive analysis, concept only)

*Verification note: Holm (1979), Politis & Romano (1994) and Sullivan, Timmermann & White (1999) were cited from the literature as known to the author and were not re-fetched in this session. The Moskowitz et al., Brock et al., Hurst et al., Miffre & Rallis, and Bailey & López de Prado entries were checked against search results.*
