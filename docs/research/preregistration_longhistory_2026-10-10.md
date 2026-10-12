# Preregistration — XAUUSD Long-History Daily Strategy Research

**ID:** `LH-XAUUSD-D1-2026-10-10`
**Status:** frozen before the final stage is run. Code: `src/qts/research/longhistory/protocol.py`.
**Runner:** `scripts/run_longhistory_research.py --stage final` (writes `data/evidence/longhistory/research_final.json`).
**Data:** `docs/research/longhistory_data_provenance_2026-10-10.md`.

This document fixes the question, data windows, candidate grid, execution model, selection rule, gates and verdict rule **before** the holdout is evaluated. A result that does not satisfy a gate is a failed gate. Nothing here may be re-tuned against the holdout or the replicate.

## 1. Question

Does any simple, causal, daily XAUUSD trading rule from a documented family produce positive net performance (after ASSUMED costs) that survives:

1. walk-forward selection on 2010–2019 out-of-sample years,
2. an untouched holdout 2020-01-01 → 2025-02-28 with the training-only selection,
3. cost stress at 2× and 3×,
4. a multiple-testing correction over all 26 evaluated configurations,
5. a mechanical regime split?

This is a **research** question. A pass would earn forward validation, not a claim. Every cost in this study is ASSUMED, and `CLAIM_ELIGIBLE_BASES` is MEASURED only, so no economic-edge claim can result from this study.

## 2. Data and windows

| Role | Source | Window (UTC trading days, 22:00 roll) | Days |
|---|---|---|---|
| Research (selection, walk-forward, holdout) | BaseMax/XAUUSD-LSTM 15-minute bars, server clock converted to UTC | 2004-06-11 → 2025-02-28 | 5,281 complete days (55 partial days excluded) |
| Replicate (run once, frozen selections, not a fresh test) | Dukascopy mirror 15-minute mid bars, UTC | 2025-08-06 → 2026-09-16 | 288 complete days |

- The research data's provenance is **unverified third-party**. Yuan, ejtraderLabs and BaseMax agree to cents, so they are one quote stream. They cannot corroborate prices independently.
- The Dukascopy replicate was already used by earlier research (`docs/research/walkforward_findings_2026-10-09.md`). It is a replicate, not an untouched test.
- No broker (MT5) bars or costs were available. Broker depth is UNKNOWN (see project control doc).

## 3. Execution model (fixed)

- Daily bars. A decision at the **close** of day `t` (from data through `t`) executes at the **open** of day `t+1`.
- Protective stops are checked against the same day's high/low. A stop fills at the stop price, or at the open if the open has gapped through it. Re-entry in the same direction is blocked until the signal state changes.
- Position size, as a fraction of equity (no leverage, cap 1.0):
  - stop-based: risk 1% of equity to `k × ATR14` (`size = min(1, 0.01 / (k·ATR/close))`);
  - no-stop: volatility target 10% annualised over 60 days (`min(1, 0.10 / σ60)`).
- A position open at a window end is closed at the final close (`forced_exit`). Each window's P&L is self-contained.
- Initial equity USD 10,000. Trades are round turns from flat to flat (rebalances and stops count inside one trade).

## 4. Costs (ASSUMED)

| Component | Base | Notes |
|---|---|---|
| Full spread | 3.0 bps | half charged per side |
| Slippage | 1.0 bps per side | |
| Commission | USD 7 per lot per side | 1 lot = 100 oz; ≈0.2–0.7 bps depending on price |
| Financing | 0 bps/day | not modelled; stress is out of scope and disclosed |

Base round turn ≈ 5–6 bps. Stress: 2× and 3× every cost component. **Break-even multiplier** on the holdout is reported by bisection. Costs are ASSUMED: no broker measurement exists here.

## 5. Candidate grid (26 configurations, all counted as trials)

Six family groups are the hypotheses tested. Each group chooses one winner per window.

| Group | Candidates | Mechanism (public basis) |
|---|---|---|
| `tsmom` | L = 63, 126, 252 days; sign of trailing return, monthly rebalance, vol-targeted | time-series momentum (Moskowitz, Ooi & Pedersen 2012) |
| `ma_cross` | SMA 20/100, 20/200, 50/200; stop-and-reverse; each with and without 3-ATR stop (6) | Brock, Lakonishok & LeBaron (1992) |
| `donchian` | 20/10 and 55/20 breakout; stops 2 or 3 ATR (4) | channel breakout / Turtle-style trend following |
| `volatility_expansion` | range expansion k ∈ {0.5, 1.0} ATR20, hold 1 or 3 bars (4); NR7 breakout, hold 3 or 5 bars (2) | Crabel-style volatility expansion and contraction, daily proxies |
| `trend_gated` | 55/20 breakout, 3-ATR stop, entry gated by efficiency ratio(60) ≥ 0.25 or ≥ 0.35 (2) | regime-conditioned trend (Kaufman efficiency ratio) |
| `mean_reversion` | RSI(2) < 5 or < 10 (long) / > 95 or > 90 (short), with or without SMA(200) trend filter (4) | Connors RSI(2) pullback reversion |
| `bollinger_20_2_control` | Bollinger(20, 2) fade to mean | **CONTROL, not a candidate.** Counts as a trial. |

`N_TRIALS = 26` (25 candidates plus the control). This is the deflation count for the Deflated Sharpe Ratio (Bailey & López de Prado 2014).

## 6. Windows and selection rule

- **Selection rule (any window):** within each group, the candidate with the highest **net Sharpe on the training window** at base costs, among candidates with at least 20 training round turns. Ties go to the earlier candidate. Training data always ends before the test window starts. Indicators are causal, so a test window's indicators use only earlier bars.
- **Walk-forward:** expanding training from 2004-06-11, one test year per fold, for 2010 through 2019 (10 folds). Selection is re-run each fold and frozen for that year.
- **Holdout:** selection run once on 2004-06-11 → 2019-12-31. The chosen candidate per group is run **once** on 2020-01-01 → 2025-02-28. Holdout results never feed back into selection.
- **Replicate:** the holdout selections are run once, unchanged, on the Dukascopy daily series. A candidate whose first valid signal bar is later than 25% of the replicate window is reported `NOT_EVALUABLE_INSUFFICIENT_WARMUP`, not forced.

## 7. Statistics

- Sharpe: annualised with √252 on daily returns, flat days included.
- Uncertainty: circular block bootstrap (block 20, 1,000 resamples) for Sharpe 95% intervals.
- Mean-return test: one-sided block-bootstrap p-value for H0: mean daily return ≤ 0 (2,000 resamples, seeded).
- Multiple testing across the six groups: Holm step-down on those p-values (family-wise α = 0.05).
- Deflated Sharpe: `qts.validation.metrics.deflated_sharpe_ratio` with `N = 26`, on combined out-of-sample returns (walk-forward 2010–2019 plus holdout).
- Trade-level direction-randomisation null (approximate, with costs fixed): reported, not gated.
- Regimes (causal, mechanical, ex-ante): trend = sign of 252-day return; volatility = 60-day realised vol above or below its expanding median (min 252 days). Four regimes: UP/DOWN × HIVOL/LOWVOL.

## 8. Gates (all must pass for a group to pass)

| Gate | Test |
|---|---|
| G1 | Holdout net P&L > 0 **and** holdout Sharpe > 0 (base costs) |
| G2 | Holdout net P&L > 0 at 2× costs |
| G3 | Walk-forward 2010–2019 Sharpe > 0 **and** ≥ 6 of 10 fold years net positive |
| G4 | Holm-adjusted p ≤ 0.05 for holdout mean daily return > 0 (six groups) |
| G5 | DSR ≥ 0.95 with N = 26 on combined out-of-sample returns |
| G6 | ≥ 100 out-of-sample round turns (2010 → 2025-02) |
| G7 | Net P&L positive in ≥ 3 of 4 regimes, with all 4 regimes present out-of-sample |

**Verdict rule**

- Any group passes G1–G7 → `FORWARD_VALIDATION_CANDIDATE_ONLY`. The claim is still **none**, because costs are ASSUMED. DEMO forward observation is the only permitted next step. Promotion requires the existing governance pipeline and measured costs.
- No group passes → `NO_VALIDATED_EDGE`. The report names the failing gates and the strongest candidates.
- Nothing here places orders, changes DEMO/LIVE state, or relaxes any risk limit.

## 9. Deviations and disclosure

- **Dev run before commit.** A dev-stage run of the walk-forward folds (2010–2019, no holdout) was executed once to debug the pipeline. The grid, gates and windows were fixed before it and were **not changed** afterwards. The only later change was a bug fix to the causality checker: a calendar-driven rebalance flag on a truncated series' final bar was being compared as if it were price-driven. The fix exempts only that bar's calendar-driven target, and only when the flag itself differs. The check now passes for all 26 candidates. The fix is documented in `checks.py`.
- Any change to this protocol after the final stage is a **new** experiment. It must be recorded in the results document as a deviation and cannot reuse the holdout.
- Results are reported whether they pass or fail.
- **Final stage run twice; strategy outputs identical.** The first final run (before the commit of this note) produced the walk-forward, holdout, replicate, gate and verdict sections. The buy-and-hold reference baseline (non-gating, specified in the research mission but not in this prereg) was then added to the runner, and the final stage was rerun. The walk-forward, holdout, replicate, gates and verdict sections were checked to be byte-identical between the two runs. The baseline does not enter any gate. Its entry is one bar later when a window starts on the first bar of the file (replicate only).
- **Accounting check.** For every candidate and window, the sum of trade-ledger net P&L equals the change in equity (maximum difference 0.0 USD) with financing set to zero.
