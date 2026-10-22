# XAUUSD@ MT5 broker-bar stability check — 2026-10-22

**Disposition: `DISCOVERY ONLY`. No validated edge, no promotion, no orders.**

This is a read-only stability check of the fixed assay documented in
`docs/research/mt5_broker_bar_discovery_2026-10-22.md`. It compares the
29,987-bar export with the shorter 19,987-bar export using the same four
predeclared hypotheses, the same next-observed-bar-open execution rule, the
same hard gap boundaries, and the same chronological 60% discovery / 20%
validation / 20% holdout split. No parameters were tuned to either output.

The exports overlap substantially, so this is not independent confirmation and
does not increase claim eligibility. It is only a bounded implementation and
stability check on locally available broker data.

## Data and cost boundary

| Export | Rows | UTC span | SHA-256 |
|---|---:|---|---|
| `data/raw/mt5_xauusd_m15_30000.csv` | 29,987 | 2025-07-14 20:00 to 2026-10-20 09:00 | `0dfd3025fb6b3fc636d8531b22ab30640f45f7bfa344136ce181f29e76adbab2` |
| `data/raw/mt5_xauusd_m15.csv` | 19,987 | 2025-12-02 02:15 to 2026-10-20 08:45 | `793355daf5ade61d98ce067874a104dfe2446bd00897136f96c65ad17fff70c7` |

The quality summary reports no duplicate timestamps, invalid timestamps,
non-positive OHLC rows, or OHLC invariant failures in the shorter export. The
30k export contains 328 intervals longer than 15 minutes; the shorter export
contains 219. Missing intervals are hard boundaries and no unobserved gap return
is credited.

The raw `spread` field is retained as broker points, but the export does not
contain a verified point value, executable bid/ask history, commission,
slippage, or swap history. The cost scenarios below are therefore explicit
price-distance assumptions, not measured broker costs. They are a stress test,
not a profitability claim.

## Fixed hypotheses and holdout results

The hypotheses are independent rule families: 12-bar trend following, 4-bar
reversal, 32-bar breakout, and 07:00–18:00 UTC session momentum. Signals are
formed only at a completed M15 close and applied at the next observed M15 open.
The statistic is HAC t for daily compounded strategy excess return versus an
exposure-matched constant-long control.

At the 0.30 assumed one-side price-distance scenario:

| Hypothesis | 30k validation t | 30k holdout t | 30k holdout Sharpe | 20k validation t | 20k holdout t | 20k holdout Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| `H-MT5-TREND-12` | +0.64 | -1.90 | -3.48 | -0.08 | -1.51 | -4.61 |
| `H-MT5-REVERT-4` | +0.18 | -1.63 | -5.10 | -2.25 | -1.13 | -5.25 |
| `H-MT5-BREAKOUT-32` | -1.02 | -0.77 | -1.51 | +0.49 | +0.66 | +1.04 |
| `H-MT5-SESSION-MOM-4` | -0.96 | -1.32 | -2.99 | +0.09 | -0.75 | -2.71 |

The 20k breakout holdout is positive at the 0.30 scenario (+0.66), but it is
not stable across the overlapping export: the 30k result is -0.77 under the
same protocol and cost. Within the shorter export its holdout t declines from
+1.57 at zero assumed cost to +0.07 at 0.50. This is a short, overlapping
sample with contradictory window behavior, so it cannot support a
validated-edge claim.

## Decision

The stability check remains `NO_VALIDATED_EDGE`. The data supports only
negative or cost-fragile discovery observations. Broker-specific execution
costs remain an evidence blocker; collecting them requires a separately
authorized, read-only DEMO measurement and still would not turn this assay
into a promotion. `DEMO_EXECUTION` remains disabled, `LIVE` remains locked,
and real-capital exposure remains zero.

Reproduction:

```text
python scripts/run_xauusd_mt5_broker_bars.py \
  --input data/raw/mt5_xauusd_m15_30000.csv \
  --evidence data/evidence/mt5_bars_30000.json \
  --output data/research/experiments/mt5_broker_bars_discovery_corrected_20261022.json \
  --markdown reports/mt5_broker_bars_discovery_corrected_20261022.md
```

The shorter-export comparison was executed in memory with the same
`qts.research.xauusd_mt5_broker_bars.run_discovery` function and did not write
broker state or call an order API.
