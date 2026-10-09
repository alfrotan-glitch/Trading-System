# Frozen Benchmark Candidates

**Generated:** 2026-10-09T12:51:04.774216+00:00
**Dataset:** 20261009-010+2b024334-1ba57af7 (REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks)
**Cost basis:** ASSUMED
**Preregistered:** 2026-10-09

## Conclusion

**NO_EDGE_ESTABLISHED — mechanism evidence only**

- no hypothesis was promoted — this report measures, it does not authorise
- the dataset cannot support an edge claim, so these numbers are mechanism evidence only

## Preregistered hypotheses (frozen before evaluation)

- **BENCH-A-TREND-EMA-12-48** (CANDIDATE) — family `trend`, params `{'fast': 12, 'slow': 48, 'ma_type': 'ema'}`, timeframe 15m, size 0.01 lots, stop 3.0 USD, max hold 16 bars. Hash `d6d5dccd5b0c…`
- **BENCH-B-BREAKOUT-DONCHIAN-20** (CANDIDATE) — family `breakout`, params `{'period': 20}`, timeframe 15m, size 0.01 lots, stop 3.0 USD, max hold 16 bars. Hash `f44be6d02e28…`
- **BENCH-C-MEANREV-BOLLINGER-20-2.0** (CONTROL) — family `mean_reversion`, params `{'period': 20, 'k': 2.0}`, timeframe 15m, size 0.01 lots, stop 3.0 USD, max hold 16 bars. Hash `7704e9b18617…`

## Observations

| Benchmark | Role | Timeframe | Round turns | Gross USD | Modelled cost | Measured cost | Net USD | Net/trade | Break-even | WF folds |
|:---|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| BENCH-A-TREND-EMA-12-48 | CANDIDATE | 15m (matches) | 912 | -125.77 | 456.00 | 2763.93 | -581.77 | -0.6379 | -0.28x | 6 |
| BENCH-B-BREAKOUT-DONCHIAN-20 | CANDIDATE | 15m (matches) | 4999 | -735.39 | 1422.00 | 8579.93 | -2157.39 | -0.4316 | -0.52x | 6 |
| BENCH-C-MEANREV-BOLLINGER-20-2.0 | CONTROL | 15m (matches) | 6289 | +81.85 | 1609.00 | 9754.73 | -1527.15 | -0.2428 | 0.05x | 6 |

Modelled cost is what the declared cost model charges; measured cost is what the
simulation actually charged (spread, slippage and fees recovered from the fill
prices against their reference prices). A large gap between them means the cost
model does not describe the venue.

**Nothing on this page promotes a strategy.** A positive net expectancy on a
non-claim-eligible dataset is arithmetic about that dataset.
