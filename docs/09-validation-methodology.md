# 9 — Validation Methodology

**Principle:** A strategy that survives only one backtest is not validated. We actively try to falsify.

## 9.1 Validation Pipeline (Strict, Ordered)

Every `Experiment` produces a `ValidationReport` by running:

```
1. Data Integrity    (schema, leakage, timestamp)
2. In-Sample Fit     (train metrics, not promotion)
3. Out-of-Sample     (holdout, never seen during tuning)
4. Walk-Forward      (anchored or rolling)
5. Regime-Conditioned (per regime)
6. Parameter Perturbation
7. Transaction-Cost Stress
8. Slippage / Latency / Spread Stress
9. Missing-Data Stress
10. Monte Carlo / Bootstrap
11. Statistical Tests (DSR, PSR, PBO)
12. Adversarial Suite
```

All steps emit artifacts; report aggregates `checks: [{name, passed, metric, threshold, details, status: IMPLEMENTED|NOT_IMPLEMENTED}]`. Promotion requires all `required=True` checks pass and no `status==NOT_IMPLEMENTED`. Validation CLI (`qts validate`) orchestrates real evidence: walk-forward splits + `run_stress` + perturbation re-runs + CPCV. Fallback PF multiplication is rejected (treated as NOT_IMPLEMENTED).

## 9.2 Splits

- **Train / Validation / Holdout** — e.g. 60/20/20 time-ordered. Validation for tuning, holdout untouched until final gate.
- **Purging & Embargo:** When label horizon = `h`, purge train samples within `h` of test start, embargo `h` after test start (Lopez de Prado). Prevents leakage via overlapping labels.

## 9.3 Walk-Forward

- **Rolling** (fixed train window) and **Anchored** (expanding) both supported.
- Common XAUUSD setting: train 12m, test 3m, step 3m → yields ~N folds. WFA efficiency = OOS / IS.
- Metrics per fold + stitched OOS equity curve. OOS Sharpe, max DD, win rate, profit factor.
- Walk-forward efficiency thresholds: >0.5 good, <0.3 heavy overfit (quanthop). But always check absolute OOS, not just ratio.

## 9.4 Regime-Conditioned

- Label each bar via `RegimeDetector` (e.g. vol quantile, trend). Compute metrics per regime. If edge exists only in one regime, strategy must declare regime filter and be tested conditional.

## 9.5 Parameter Perturbation

- Grid ±10%, ±20% around optimal. Stability = Sharpe drop < 30%, no sign flip. Fragile thresholds → reject.

## 9.6 Cost Stresses

| Stress | Levels | Pass Criterion |
|--------|--------|----------------|
| Commission | 1×, 2×, 3× | Sharpe >0 at 2× |
| Spread | historical, 1.5×, 2× | PF >1.0 at 1.5× |
| Slippage | 0, 2bps, 5bps, 10bps | No collapse |
| Latency | 0ms, 500ms, 2000ms | Stable |
| Missing data | random 1%, 5% drop | Graceful, NO_TRADE not crash |

If strategy is spread-sensitive (XAUUSD often is), it fails this gate — correctly.

## 9.7 Monte Carlo / Bootstrap

- **Trade reshuffle:** Randomize trade order 1000×, compute drawdown distribution; if observed DD is tail event → fragile.
- **Bootstrap returns:** Resample returns with replacement, compute Sharpe distribution (PSR).
- **Block bootstrap** for autocorrelated returns (circular block length ~20).
- **Monte Carlo price paths** (optional): simulate GBM with fitted vol, test strategy not just lucky path.

## 9.8 Statistical Tests — Implemented (Phase 1, Bailey/LdP, No Heuristic)

- **Probabilistic Sharpe Ratio (PSR, Bailey & Lopez de Prado 2012):** `PSR(SR*) = Φ[(SR̂ - SR*) / σ̂_SR]` where `σ̂_SR = sqrt((1 - γ̂1*SR̂ + (γ̂2-1)/4 * SR̂²)/(T-1))`, `γ̂1`=skew, `γ̂2`=kurtosis raw, `T=n`. Probability true Sharpe > benchmark. `n = len(returns)` (auto).
- **Deflated Sharpe Ratio (DSR, Bailey & Lopez de Prado 2014):** `DSR = PSR(SR0)` with `SR0 = E[max SR̂ under null across N trials]`. `E[max] = (1-γ)Φ⁻¹(1-1/N) + γΦ⁻¹(1-1/(Ne))`, `γ≈0.5772`. N = trials tracked in `ExperimentStore.count_trials()` (including discarded). DSR==PSR(0) when N=1, DSR ↓ as N↑, DSR<P SR for N>1. No 0.15 factor; benchmark unscaled (conservative, documented in `src/qts/validation/metrics.py`).
- **Probability of Backtest Overfitting (PBO, Lopez de Prado 2018, CPCV):** `PBO = #{best IS test Sharpe < median test Sharpe} / #CPCV folds`. CPCV via `ValidatorPipeline.cpcv_splits(n, n_groups, n_test)`: partition bars into groups, enumerate `C(n_groups, n_test)` combos; each fold records `{best_is_trial, best_is_test_sharpe, median_test_sharpe}` across trials (e.g. fast=5/10/15). Requires `>=5` folds else `NOT_IMPLEMENTED → BLOCKS` (`max_pbo=0.5`). PBO reported in `ValidationReport.metrics["pbo"]`.

Assumptions: IID violation acknowledged, stationarity not assumed, DSR optimistic lower bound; skew/kurtosis are sample estimates; annualization `sqrt(252*24)` consistent for SR and benchmark.

## 9.9 Adversarial Suite

Every promising strategy is attacked for:

- Look-ahead (feature uses `close` of same bar to trade same bar)
- Survivorship/selection bias (only favorable period)
- Data snooping (many trials)
- Leakage via normalization (fit on full data)
- Regime dependence (only bull)
- Unstable params / thresholds
- Cost/spread/slippage sensitivity
- Timestamp / timezone off-by-one
- Broker artifacts (tick vs bar alignment)
- Unrealistic fills (fill at high/low without spread)
- Sample selection (cherry-picked timerange)
- Multiple testing (Harvey et al. urgency: higher Sharpe threshold when N large)

Each check is an automated validator; findings go to `AdversarialFindings` and block promotion.

## 9.10 Thresholds (Defaults, Tunable per Instrument) — Enforced Pipeline

```yaml
validation:
  required:  # any NOT_IMPLEMENTED blocks passed=False
    walk_forward_real:
      min_folds: 5        # len(walk_forward_folds) required, each {is_sharpe, oos_sharpe} from independent backtests
      min_wfe: 0.3
      min_oos_sharpe: 0.0  # demo relaxed to -1.0 for synthetic
    pbo_cpcv:
      min_combos: 5
      max_pbo: 0.5
    perturbation:
      min_variants: 7     # ±5/10/20% around baseline, re-run Sharpe per variant
      max_sharpe_drop: 0.3 # (baseline - worst)/|baseline| ≤30%, sign flip fails
    stress_spread:
      re_run: true        # must be from BacktestEngine.run_stress(multipliers 1.0/1.5/2.0) not PF*m
      spread_1_5x_pf: 1.0 # PF at 1.5× ≥1.0
    dsr:
      min_prob: 0.95      # informational unless trials>5 & n>30
```

Tunable per `instrument` and `timeframe`; defaults conservative for XAUUSD.

## 9.11 Holdout Discipline

- Holdout is never used for tuning. If WFA fails and hypothesis tweaked, holdout remains untouched. Only final gate reads holdout.
- If holdout peeked during development, experiment marked `CONTAMINATED`, new holdout required.

## 9.12 Reporting

`ValidationReport` includes: equity curves (IS/OOS/WFA stitched), per-fold metrics, per-regime, perturbation heatmap, stress table, Monte Carlo drawdown histogram, DSR/PSR/PBO numbers, leakage checklist, and `passed: bool` with reasons.

## 9.13 Example Report Snippet

```
Walk-forward (12m/3m, 8 folds): IS Sharpe 1.8, OOS 1.1, WFE 0.61 PASS
PBO (CPCV 12 groups): 0.38 PASS
DSR (N=45 trials, len=1200): observed 1.1 → DSR prob 0.87 FAIL (need 0.95)
Stress spread 1.5×: PF 0.9 FAIL
→ Overall: FAIL, reasons: [DSR, spread stress]
→ Action: RESEARCH (needs stronger edge or lower cost sensitivity)
```
