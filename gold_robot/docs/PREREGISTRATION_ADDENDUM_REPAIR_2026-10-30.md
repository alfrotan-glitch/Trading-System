# Preregistration addendum — repair branch (frozen document NOT edited)

Date: 2026-10-30. Branch: `independent/adaptive-repair-20261030`,
from exact `34cab34`. The frozen preregistration document
(`PREREGISTRATION_ADAPTIVE_2026-10-30.md`) is intentionally left
unedited; this addendum records what changed, what did not, and
what it costs in trial accounting. Anything not listed here is
unchanged from the frozen document.

## What changed

1. **Router ATR-guard reference bar (behavior change).**
   `RouterVolatilityGuardPass` previously read `values[0]` of a
   50-bar CopyBuffer window as the current ATR; in MQL5 non-series
   order that element is the OLDEST bar (shift 50). It now reads
   the LAST element (shift 1, latest closed). Window (50),
   percentile (0.90), and abstention rule are unchanged, and no
   threshold was tuned on any return — but because router
   decisions change, the repaired router is a NEW Style 7 variant.
   A repair-branch Windows run declares it as the Style 7 trial;
   it must not be presented as the adaptive-branch router's result,
   and running both routers as separate claims counts both trials.
2. **Installer, preset, runner, comparison, forensics, evaluator
   repairs.** These change deployment and measurement, not
   strategy decisions (except item 1). They are not strategy
   trials. The evaluator's 2x figure, walk-forward, and
   counterfactual methods are frozen by this addendum before any
   native PnL is viewed on the repair branch.
3. **Method frozen here (before any repair-branch native PnL):**
   genuine expanding-window walk-forward with frozen rules and no
   refit (WFE = OOS/IS, undefined when IS ≤ 0); best-static /
   random-router / shuffled-regime counterfactuals only when
   per-candidate ledgers from the same window and costs exist;
   cost multiples 1x/1.5x/2x on repaired doubled charges;
   spread stress only from a supplied per-trade spread USD or a
   separate native doubled-spread run (each a trial).

## What did not change

- All frozen thresholds: router persistence 3 bars, transition
  priority 4 + R ≥ 1.0, ATR guard percentile 0.90 over 50 bars;
  SMC 20-bar window, 0.10×ATR displacement, OB/FVG + BOS/CHoCH;
  scalp 34 M1 bars, efficiency 0.43/0.28, 12/15 bps SL/TP,
  15-minute cap, M1 only.
- The future-forward validation requirement: a pre-chosen window
  after 2026-10-30, at least 3 months, no Jan–Feb 2026 overlap,
  native, safety_on. This repair work does NOT satisfy it, and no
  Linux result in this branch substitutes for it.
- Contaminated windows: Jan–Feb 2026 and every window used for
  screening or tuning remain contaminated and can never serve
  as OOS for these candidates.
- Live trading stays disabled; Styles 4–9 stay Tester-only.

## Trial accounting for the repair-branch Windows run

Minimum `trials_tested` = 10 (styles 0–9 in one run), plus every
robustness perturbation actually run (cost multiples, spread
model, slippage stress, threshold perturbations). Cap 40 for
edge_gate tail resolution; beyond 40 use DSR/Holm over the
ledger-counted list. Under-declaring trials to regain tail
resolution is forbidden by the gate's own warning and by this
addendum.
