# XAUUSD@ MT5 broker-bar discovery — 2026-10-22

**Disposition: `DISCOVERY_ONLY`. No validated edge, no promotion, no orders.**

This is a new broker-feed assay on the locally preserved WMMarkets DEMO M15
OHLC export. It is not a profitability claim and it does not reopen any spent
long-history holdout. The product remains `NO_VALIDATED_EDGE`, `LIVE LOCKED`,
and `REAL_CAPITAL_EXPOSURE = 0`.

## Data custody and limits

- Source: `data/raw/mt5_xauusd_m15_30000.csv`, referenced by
  `data/evidence/mt5_bars_30000.json`.
- 29,987 closed bars, `2025-07-14T20:00:00Z` through
  `2026-10-20T09:00:00Z`.
- Source SHA-256:
  `0dfd3025fb6b3fc636d8531b22ab30640f45f7bfa344136ce181f29e76adbab2`.
- 328 observed intervals exceeded 15 minutes; the longest was 4,395 minutes.
  These intervals are treated as hard boundaries. No unobserved gap return is
  credited.
- The export has OHLC and a broker-points `spread` field, but not executable
  bid/ask events, fill prices, commission, slippage, swap, or a verified point
  conversion. The spread field is therefore preserved but not converted into a
  USD/oz cost.

## Predeclared hypotheses

The parameter set was fixed before reading the output and was not swept:

| ID | Rule | Execution |
|---|---|---|
| `H-MT5-TREND-12` | sign of the 12-bar close return | next observed M15 open |
| `H-MT5-REVERT-4` | opposite sign of the 4-bar close return | next observed M15 open |
| `H-MT5-BREAKOUT-32` | close above/below the prior 32-bar high/low | next observed M15 open |
| `H-MT5-SESSION-MOM-4` | sign of the 4-bar return, decisions only 07:00–18:00 UTC | next observed M15 open |

Signals use only completed bars. Missing bars flatten the position before the
next observed bar. Results are compared with a constant-long control whose
exposure matches each signal's mean absolute exposure in the split.

Costs are reported at assumed one-side price distances of `0.00`, `0.15`,
`0.30`, and `0.50`; they are explicitly `ASSUMED`, not measured broker costs.

## Results at assumed 0.30 price distance per side

The reported statistic is HAC t for the strategy's daily excess return versus
its exposure-matched control. The holdout is chronological and was not used to
select a rule.

| Hypothesis | Discovery t | Validation t | Holdout t | Holdout Sharpe |
|---|---:|---:|---:|---:|
| `H-MT5-TREND-12` | -1.27 | +0.64 | -1.91 | -3.48 |
| `H-MT5-REVERT-4` | -4.31 | +0.19 | -1.61 | -5.10 |
| `H-MT5-BREAKOUT-32` | -1.17 | -1.02 | -0.77 | -1.51 |
| `H-MT5-SESSION-MOM-4` | -1.70 | -0.96 | -1.33 | -2.99 |

The results do not support a positive, stable, cost-aware effect in this
sample. The high turnover of the reversal and session rules also makes the
unmeasured broker execution terms especially material. These are historical
observations on a limited broker export, not evidence of future profitability.

Machine-readable output: `data/research/experiments/mt5_broker_bars_discovery_20261022.json`.

## Reproduction and safety

```text
python scripts/run_xauusd_mt5_broker_bars.py \
  --input data/raw/mt5_xauusd_m15_30000.csv \
  --evidence data/evidence/mt5_bars_30000.json
```

The runner has no broker import and no order path. Recorded safety facts are
`orders_submitted = 0`, `DEMO_EXECUTION = DISABLED`, and `LIVE = LOCKED`.
