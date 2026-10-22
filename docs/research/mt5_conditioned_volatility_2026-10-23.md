# XAUUSD@ conditioned-volatility M15 discovery — 2026-10-23

**Study:** `MT5-CONDITIONED-M15-20261023`
**Disposition:** `DISCOVERY_ONLY`; no validated edge, no promotion, no orders.

This cycle tests a materially different mechanism from the earlier
unconditional trend, reversal, breakout, session, impulse, macro, and adaptive
ML studies: direction is conditioned on observed range and broker tick-volume
state. The four hypotheses and fixed holding periods were declared in
`src/qts/research/xauusd_conditioned_m15.py` before scoring the outputs. No
parameter was selected from either result.

## Protocol

- Completed M15 close signal; next observed M15 open execution.
- Fixed holds of 4, 8, or 16 observed bars; no overlapping position entries.
- Missing intervals are hard execution boundaries. No return across a gap is
  credited. Slow direction uses observed intrabar returns only, not an
  untradeable close-to-close maintenance gap.
- Chronological 60% discovery / 20% validation / 20% holdout split.
- Daily compounded strategy return is compared with an exposure-matched
  constant-long control.
- One-side price-distance costs are explicitly assumed at 0.00, 0.15, 0.30,
  and 0.50. The broker `spread` field is not converted because its point size,
  executable bid/ask history, commission, slippage, and swap terms are not
  verified.
- The two exports overlap substantially and are not independent confirmation.

## Data

| Export | Rows | UTC span | SHA-256 |
|---|---:|---|---|
| `mt5_xauusd_m15_30000.csv` | 29,987 | 2025-07-14 20:00 to 2026-10-20 09:00 | `0dfd3025fb6b3fc636d8531b22ab30640f45f7bfa344136ce181f29e76adbab2` |
| `mt5_xauusd_m15.csv` | 19,987 | 2025-12-02 02:15 to 2026-10-20 08:45 | `793355daf5ade61d98ce067874a104dfe2446bd00897136f96c65ad17fff70c7` |

The longer export has 328 intervals over 15 minutes; the shorter has 219.
Maximum gaps are 4,395 and 18,420 minutes respectively. The shorter export
has no duplicate timestamps or OHLC invariant failures according to its
quality evidence.

## Results at assumed one-side cost 0.30

The statistic is HAC t for daily active return versus the exposure-matched
control. Positive values are not sufficient for promotion.

| Hypothesis | 30k validation t | 30k holdout t | 30k holdout Sharpe | 20k validation t | 20k holdout t | 20k holdout Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| `H-VOL-COMP-BREAK-8` | -0.24 | +1.10 | +1.81 | +0.73 | -0.00 | -0.74 |
| `H-VOL-EXP-FADE-4` | +0.56 | -1.31 | -2.67 | -0.91 | -0.61 | -1.94 |
| `H-VOL-EXP-MOM-4` | -0.31 | +0.58 | +1.04 | +0.23 | +0.27 | +0.40 |
| `H-VOL-QUIET-DRIFT-16` | +1.55 | -0.81 | -2.17 | +1.11 | -1.20 | -5.54 |

Cost stress reinforces the uncertainty. For `H-VOL-COMP-BREAK-8`, holdout HAC
t moves from +1.61 to +0.76 on the longer export as assumed one-side cost
moves from 0.00 to 0.50, but from +0.50 to -0.34 on the shorter export. For
`H-VOL-EXP-MOM-4`, the corresponding ranges are +0.98 to +0.30 and +0.55 to
+0.08. The 30k expansion-momentum holdout has 348 position changes and the
20k holdout has 203, so measured broker costs are material.

## Decision

`NO_VALIDATED_EDGE` for this cycle. The compressed-breakout result is
window-inconsistent. Expansion momentum is directionally encouraging but weak,
cost-sensitive, and not independently confirmed. Fade and quiet-drift are
rejected by the holdout results. None is eligible for QTS registration,
automatic execution, DEMO orders, or LIVE use.

The next highest-information step is not another parameter variation: acquire
genuinely unseen timestamped broker observations, measure executable spread,
slippage, commission, and swaps through the read-only/forward evidence
workflow, then evaluate this frozen family once on that future period. The
current exports cannot satisfy independent validation.

Reproduction:

```text
python scripts/run_xauusd_conditioned_m15.py --input data/raw/mt5_xauusd_m15_30000.csv --output data/research/experiments/mt5_conditioned_m15_30000_20261023.json --markdown reports/mt5_conditioned_m15_30000_20261023.md
python scripts/run_xauusd_conditioned_m15.py --input data/raw/mt5_xauusd_m15.csv --output data/research/experiments/mt5_conditioned_m15_20000_20261023.json --markdown reports/mt5_conditioned_m15_20000_20261023.md
```

Safety: `orders_submitted=0`; `DEMO_EXECUTION=DISABLED`; `LIVE=LOCKED`.
