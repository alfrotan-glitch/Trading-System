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

All steps emit artifacts; report aggregates `checks: [{name, passed, metric, threshold, details}]`. Promotion requires all `required=True` checks pass.

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

## 9.8 Statistical Tests

- **Deflated Sharpe Ratio (DSR, Bailey & Lopez de Prado 2014):** Adjusts Sharpe for non-normality (skew, kurtosis), length, and multiple trials `N`. Reports `Pr[SR > 0]`. Needs `N` = number of strategies tested (including discarded) — tracked in ExperimentStore.
- **Probabilistic Sharpe Ratio (PSR):** `Pr[SR > threshold]` given observed skew/kurtosis/length.
- **Probability of Backtest Overfitting (PBO, Lopez de Prado 2018, CPCV):** Fraction of CPCV paths where IS optimal underperforms median OOS. PBO >0.5 → overfit likely. CPCV generates combinatorial splits for robust estimate.
- **White's Reality Check / Hansen SPA** (future): for multiple-testing correction when comparing many strategies.

Document assumptions: IID violation, stationarity not assumed, reported DSR is optimistic lower bound.

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

## 9.10 Thresholds (Defaults, Tunable per Instrument)

```yaml
validation:
  required:
    walk_forward:
      min_folds: 5
      min_wfe: 0.3
      min_oos_sharpe: 0.5
    dsr:
      min_prob: 0.95  # Pr >0.95 after deflation (if N known)
      min_trials_tracked: true
    pbo:
      max_pbo: 0.5
    perturbation:
      max_sharpe_drop: 0.3
    stress:
      spread_1_5x_pf: 1.0
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
