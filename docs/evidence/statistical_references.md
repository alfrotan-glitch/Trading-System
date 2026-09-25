# Statistical References
Version: 0.1.0

## Retained Gates
- Walk-forward (WFE >0.3, OOS Sharpe >0.3) — Rolling/expanding, 5 folds.
- CPCV/CSCV (PBO <0.5) — 6 groups, purging/embargo, Lopez de Prado.
- PSR (P(SR >0) >0.95) — Bailey & López de Prado 2012, uses n, skewness, kurtosis, periods_per_year.
- DSR (deflated for N trials >0.95) — Bailey et al. 2014, E[max Sharpe] = f(N).
- Perturbation (±15% param <20% drop)
- Regime (trend/range/high_vol each stable)
- Null/placebo (random timing, shuffled labels, placebo strategies)
- Cost stress (1.0/1.5/2.0× spread)
- Expectancy, economic edge (remaining >0 and >20% cost)
- Forward, shadow/paper

## Extensions
| Method | Purpose | Assumptions | Inputs | Limitations | Reference | Unit Test | Failure Modes |
|--------|---------|-------------|--------|-------------|-----------|-----------|---------------|
| White Reality Check | Control data snooping max Sharpe across trials | Stationary bootstrap, null no edge | returns, benchmark, n_bootstrap | Needs large T, assumes i.i.d. | White 1996 | `test_white_reality_check` | Underestimates dependence if returns autocorrelated |
| Hansen SPA | Superior predictive ability improved White | Bootstrap, null best not better | returns_list, benchmark | Bootstrap assumes no temporal dependence | Hansen 2005 | `test_hansen_spa` | Fails if returns non-stationary |
| Permutation test | Sharpe significance via label shuffle | Exchangeability under null | returns, n_perm | Assumes i.i.d. | Fisher | `test_permutation` | Fails with serial correlation |
| Minimum backtest length | Track-record requirement for PSR target | PSR formula inversion | sharpe, target_psr, skew/kurt | Approx, ignores non-normal | Bailey 2012 | `test_min_backtest_length` | Over-optimistic if skew/kurt misestimated |
| Drawdown distribution | Expected shortfall, tail diagnostics | Bootstrap equity paths | equity, n_bootstrap | Assumes returns stationary | — | `test_drawdown_dist` | Fails if regime shift |
| Parameter surface | Detect isolated spike overfit | Mean/std of param Sharpes | param_sharpes dict | Needs dense grid | — | `test_param_surface` | Fails if grid sparse |

## Implementation
`src/qts/research/statistical.py` provides each with docstring purpose/assumptions/inputs/limitations, reference implementation using `scipy.stats.norm`, numpy, unit tests in `tests/test_statistical_extensions.py`, failure modes documented.

## For Every Method
As required: document purpose, assumptions, inputs, limitations, reference implementation, unit tests, known failure modes — all present.

## Do Not Add Sophistication for Its Own Sake
Each added only where appropriate to attack overfitting false discoveries, not to hide failures.

## Evidence
Machine-readable `data/evidence/statistical_extensions.json` (example bootstrap p-values).

## Statistical Hostility
More complexity → more trials → stronger DSR penalty. No free advantage.
