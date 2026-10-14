# Preregistration — XAUUSD M15 impulse-fade (short-horizon reversal)

**ID:** `LH-XAUUSD-M15-REV-2026-10-14`
**Status:** frozen and committed **before** any reversal walk-forward, holdout or replicate result is computed.
Code: `src/qts/research/longhistory/reversal_protocol.py`, `signals.impulse_fade`.
Runner: `scripts/run_longhistory_reversal.py --stage dev|final`.
Evidence (to be written by the runner): `data/evidence/longhistory/reversal_research_{dev,final}.json`;
tables: `docs/research/longhistory_reversal_results_tables_2026-10-14.md`.
Parents: `LH-XAUUSD-M15-2026-10-10` (intraday, `NO_VALIDATED_EDGE`) and `LH-XAUUSD-SES-2026-10-14`
(seasonal, `NO_VALIDATED_EDGE`). Their data, cost model, gates and selection rule are inherited unchanged,
except G8 (carried from the seasonal cycle) and the trial count (§7).

This document fixes the question, candidates, rules, selection rule, gates and verdict rule before the
holdout result is read. A failed gate is a failed gate. Nothing here may be re-tuned against the holdout
or the replicate. A change is a new preregistration with a new ID.

## 1. Question and mechanism

**Question.** Does a short-horizon *reversal* of large single-bar impulses on XAUUSD M15 produce positive
net performance after the ASSUMED cost model, and does it survive the same chain of tests as the parent
cycles?

**Mechanism (why a reversal, and why it is not a re-test).** Large one-bar body moves in a liquid market
are often driven by transient order-flow imbalance (stop runs, market-order clusters, thin-liquidity
prints). Inventory-holding liquidity providers and market makers absorb that flow and are compensated by
partial reversion over the next hours. This is the short-horizon reversal and liquidity-provision channel
(e.g. Jegadeesh 1990; Lehmann 1990; Nagel 2012 on the link between reversal profits and liquidity
provision). The opposite sign was tested in the parent cycle as `rexp_k10_h4/h16`
(continuation): it was negative at zero cost on the holdout (−3,450 zero-cost P&L for `rexp_k10_h16`).
This study tests the **sign-reversed** hypothesis with a stricter impulse threshold and a different
stop structure. It is a new hypothesis, not a re-run of the continuation grid, and it is counted in the
trial count (§7).

**Falsifiable predictions.**
1. Fading a `> k·ATR` impulse produces a *positive gross* return over the holding period (before costs),
   at the next bar's open.
2. The gross edge per trade is larger than the cost per round turn, so the net is positive at base cost
   and at 2× cost (G1, G2).
3. The edge is not produced by a single regime or era (G3, G7).

If the gross return is not positive, the mechanism is rejected at the gross level regardless of costs.

## 2. Data and windows (inherited, unchanged)

| Role | Source | Window (UTC) | Bars |
|---|---|---|---|
| Research (selection, walk-forward, holdout) | BaseMax XAUUSD 15m (UTC), complete trading days | 2004-06-11 → 2025-02-28 | 474,388 |
| Replicate (informational, final stage only) | Dukascopy M15 (UTC), complete trading days | 2025-08-06 → 2026-09-16 | 26,030 |

- A trading day rolls at 22:00 UTC; only complete days (≥ 40 bars) are used. Bars per complete day: 92.
- **Holdout reuse (disclosed).** The 2020-01-01 → 2025-02-28 holdout has been evaluated in the daily,
  intraday and seasonal cycles. The replicate has been evaluated in the intraday and seasonal cycles.
  **This cycle is therefore not an independent test on those windows.** A pass on this holdout would earn
  *forward validation only*, not a claim, and the replicate result would be read with the same caveat.
  No window with fresh, unseen data exists in this repository (see the blockers in §10).
- Timestamp convention (bar open vs close) is unresolved (see the intraday preregistration §2). It is not
  corrected here.

## 3. Execution model (inherited, unchanged)

A decision at the close of bar `t` fills at the open of bar `t+1`. The stop is at `2 × ATR(14)` from the
entry fill, checked against each bar's range, filled at the stop (or the open on a gap). Position is
fixed-fraction risk sized (`RISK_PER_TRADE = 1%` over stop distance), capped at 1.0× equity, no leverage.
A fixed-horizon trade exits after `hold` bars. Re-entry blocked while a position is open. An open position
at the window end is closed at the final close and marked forced.

## 4. Costs (ASSUMED — not measured)

Inherited `COST_BASE`: `spread_bps = 3`, `slippage_bps = 1` per side, commission `$7/lot/side`,
financing `0`. Basis `ASSUMED`. Stress multipliers 2× and 3×. **No cost in this document is measured.**
The break-even multiplier is reported for every holdout result.

## 5. Candidates (3, all counted)

| Candidate | Rule | Hold | Stop |
|---|---|---|---|
| `fade_k20_h4` | bar body > 2.0 × ATR20(prior bar) → short; body < −2.0 × ATR20 → long | 4 bars (1 h) | 2 ATR |
| `fade_k20_h16` | same trigger | 16 bars (4 h) | 2 ATR |
| `fade_k10_h4` | body > 1.0 × ATR20 → short; body < −1.0 × ATR20 → long (sign mirror of `rexp_k10_h4`) | 4 bars | 2 ATR |

- Single family group `impulse_fade`. The walk-forward selects one candidate per year by training-window
  Sharpe (inherited rule, §6).
- The turnover filter is the threshold: `k = 2.0` is a stricter trigger than the parent's `k = 1.0`, so
  it trades far less. This is the designed response to the parent's cost failure (8,162 round turns on
  the holdout).
- **Scope exclusions:** no discretionary override; no per-bar conditioning on the session; no optimisation
  of `k`, `hold` or stop beyond the three frozen values above.

## 6. Selection rule and walk-forward (inherited, unchanged)

Per year `Y ∈ {2010..2019}`: train on data before `Y`, select the candidate with the best training-window
Sharpe that has at least `MIN_TRAIN_ROUND_TURNS` round turns; trade it in `Y`. The 2020-01-01 → 2025-02-28
holdout uses one selection made on data through 2019-12-31, frozen before the holdout is read.

## 7. Trial count (multiple testing)

`N_TRIALS = 47 + 3 = 50`: 47 is the cumulative count after the seasonal cycle (`seasonal_protocol.N_TRIALS`),
and the three candidates of this cycle are added. The deflated Sharpe ratio (DSR) uses 50 trials. Holm
adjusts across the single family group.

## 8. Gates (inherited G1–G7, plus G8 from the seasonal cycle)

| Gate | Criterion (all must hold for the selected candidate) |
|---|---|
| G1 | Holdout base-cost net P&L > 0 and Sharpe > 0 |
| G2 | Holdout net P&L > 0 at 2× cost |
| G3 | Walk-forward 2010–2019 Sharpe > 0 and ≥ 6 of 10 positive years |
| G4 | Holm-adjusted p ≤ 0.05 (sign / bootstrap, as in the parent) |
| G5 | DSR ≥ 0.95 at N = 50 |
| G6 | ≥ 100 out-of-sample round turns |
| G7 | Positive net in ≥ 3 of 4 regimes, with every regime present |
| G8 | Holdout break-even cost multiplier ≥ 2.0× (strict; from the seasonal cycle) |

Gate thresholds are not changed after seeing any result. A **PASS** requires all eight gates. A pass on
this cycle earns *forward validation*, not a claim, because the holdout and replicate are reused (§2).

## 9. Verdict rules

- **`NO_VALIDATED_EDGE`** if no candidate passes all eight gates (expected).
- **`FORWARD_VALIDATION_CANDIDATE`** if the selected candidate passes all eight gates on the reused
  holdout and is not negative on the replicate.
- Any gross-level falsification (§1, prediction 1: gross holdout P&L ≤ 0 at zero cost) is recorded as a
  mechanism rejection regardless of costs.
- Failure analysis (per-regime, per-year, cost, gross vs net) is recorded in the results document, and it
  does not revise any gate.

## 10. Remaining blockers (not addressed by this cycle)

- Independent unseen data: no fresh XAUUSD window is available in this repository beyond the reused replicate.
- Measured costs: `qts demo cost-check --record` needs the Windows MT5 terminal; spread and commission are
  ASSUMED throughout.
- Tick-level order-flow (the tick archive) remains operator-side (see the seasonal preregistration §11).
- Cross-asset (DXY, real yields): no source is reachable in this sandbox beyond GitHub/PyPI/npm.

## 11. Pre-run declarations

1. This preregistration is committed before the `dev` and `final` stage runs of this cycle.
2. The `dev` stage (walk-forward 2010–2019 only) is run first. The `final` stage is run once after it.
3. Any `final`-stage discrepancy (for example, a bias check failure) is recorded and does not alter
   the gates.
