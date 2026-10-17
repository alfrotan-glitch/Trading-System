# Preregistration — XAUUSD Monthly Slow USD-Conditioned Hybrid Trend

**ID:** `LH-XAUUSD-HYB-2026-10-17`
**Status:** frozen in `src/qts/research/longhistory/hybrid_protocol.py`
(builders in `ensemble_signals.py`) before any evaluation-window or
replicate result of this cycle. Discovery on ≤1989 only (§4);
`--stage dev` (WF 1990–1999 only) ran pre-freeze as pipeline debug, so
the G3 walk-forward component is knowable before final — disclosed, as
in every parent monthly cycle. Runner:
`scripts/run_longhistory_hybrid.py --stage dev|final`. Parents: all prior
long-history cycles, most recently `LH-XAUUSD-ENS-2026-10-17` and
`LH-XAUUSD-W1-2026-10-17` in the same 2026-10-17 series.

## 1. Question

The ensemble cycle produced the repository's two strongest partial
results on disjoint windows: slow long-or-flat trend (`ts9_lo`,
evaluation Sharpe 0.837, DSR 0.929, break-even > 50x) whose 1990s
walk-forward is structurally flat/ineligible, and USD-conditioned trend
(least-bad 1990s walk-forward). Does the **asymmetric slow hybrid** —
longs unconditioned, shorts only on 12-month USD confirmation (veto
form); or both sides only on USD agreement (agreement form) — at slow
horizons (9m; 6/9/12; 4/9/12) keep the evaluation-window strength while
turning the 1990s walk-forward positive, the combination no prior cycle
tested?

## 2. Data, windows, costs, gates (inherited unchanged from ENS)

World Bank monthly gold + Fed USD index, 645 months 1973-01 → 2026-09;
discovery ≤1989; WF test years 1990–1999 (expanding selection);
evaluation 2000-01 → 2026-09 (selection through 1999-12-31); BaseMax
monthly replicate 2004-06 → 2025-02 informational. TWAP-at-next-month-
average execution, `fixed_units.v2`, 10% vol target, cap 1.0x, no stops.
Costs ASSUMED (base 3+1 bps + $7/lot/side; 2x/3x; break-even; G9
financing +0.25 bps/day). Gates G1–G9 identical thresholds to
`LH-XAUUSD-ENS-2026-10-17` (G3: WF Sharpe > 0 and ≥ 6/10 positive years;
G5: DSR ≥ 0.95 at §5's N; G6: ≥ 100 OOS turns). Selection: highest
training Sharpe among ≥ 20-turn candidates per group. Known mechanical
consequence: slow long-or-flat candidates reach < 20 training turns
through 1998, so `hyb_lo` may contribute no WF folds; its group G3 is
then unreachable by construction and the group serves as the registered
replication of the ensemble cycle's `ts9_lo` selection under the new
trial count. Holdout reuse and ASSUMED-cost ceiling
(`FORWARD_VALIDATION_CANDIDATE_ONLY`, claim none) disclosed as before.
No DEMO/LIVE/risk/order-path change; `REAL_CAPITAL_EXPOSURE = 0`.

## 3. Candidates (9 + 1 control)

| Group | Candidate | Definition |
|---|---|---|
| `hyb_veto` | `veto9` / `veto6912` / `veto4912` | trend sign (9m; vote 6/9/12; vote 4/9/12); shorts only if USD +12m |
| `hyb_agree` | `agree9` / `agree6912` / `agree4912` | same trends, traded only when 12m USD move agrees, else flat |
| `hyb_lo` | `ts9_lo` / `lo6912` / `lo4912` | same trends, long-or-flat |
| (control) | `m_boll20_2` | CONTROL 20m 2σ Bollinger reversion |

## 4. Discovery record (≤1989, complete)

43 configurations: for each lookback set {(9), (12), (6,12), (9,12),
(6,9,12), (4,9,12), (3,9,12), (4,12), (6,9), (3,6,9,12)} the veto,
agreement, long-or-flat and long-short forms, plus long-or-flat singles
6/9/12m (duplicates of ensemble-of-one forms counted once). Frozen-set
selection/test Sharpe: `veto9` 0.828/0.588, `veto6912` 0.811/0.586,
`veto4912` 0.818/0.558; `agree9` 0.773/0.609, `agree6912` 0.746/0.608,
`agree4912` 0.747/0.580; `ts9_lo` 0.779/0.563, `lo6912` 0.760/0.562,
`lo4912` 0.761/0.525. Training round turns through 1989 for the frozen
veto/agreement candidates: 14–21 (eligibility arrives between the first
and later WF folds, handled by the inherited selection rule).

## 5. Trial count

`DISCOVERY_TRIALS = 44` (43 discovery + control). Inherited `N = 193`
through `LH-XAUUSD-W1-2026-10-17`. **`N_TRIALS = 237`.**
