# Annual gold calendar-seasonality screen — discovery/development results

**Hypothesis:** `LH-XAUUSD-GOLD-CALENDAR-SEASONALITY-2026-10-19`
**Decision:** `REJECTED` — the single frozen seasonal candidate did not pass; do not adjust the month mask or rerun on these partitions.
**Evidence:** `data/evidence/longhistory/gold_calendar_seasonality_discovery_dev.json`
**Runner:** `scripts/run_longhistory_gold_calendar_seasonality.py`, checkout `b6ae3f50b3f7ea79454d5119b7c0b2dec2b7d028`
**Protocol:** `docs/research/preregistration_longhistory_gold_calendar_seasonality_2026-10-19.md` (SHA-256 `9dc5214bf7adf9403237ccf47dfbb1315877bbcdeb3412b86251e578604d91d1`)

## Frozen run and source preflight

The one candidate, `calendar_seasonal_gold_5m`, was long only for January–March and August–September, using the frozen 12-month realized-volatility sizing primitive. It was evaluated once against unchanged `ts9_lo` and `veto9` on selection (1973–1983), confirmation (1984–1989), and development (1990–1999). Execution, separate USD 10,000 window accounts, assumed costs, and statistical gates were frozen in advance. The H.10 eight-currency source was used only to reproduce unchanged comparator `veto9`.

Pinned source identities passed before seasonal features/outcomes were calculated. The eligible Gold series contains 480 monthly observations from 1960-01 through 1999-12. H.10 is pinned to `datasets/exchange-rates@c023dd8b8f879610641a7391c0394c3bbb42d0f7`, SHA-256 `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa`. Gold is pinned to `awongstory/commodity-price-forecast-xgboost@c4a9f734d92df0d0a6c4744a2d7c34417ecd074b`, blob `b31639d3bbf4c42ecd6406526d21bb7536e24ef9`, SHA-256 `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf`. Post-1999 Gold prices and H.10 exchange-rate values converted: **0**. No final stage or locked holdout was accessed.

## Results

Net and gross P&L are USD per separate USD 10,000 window account. Costs are ASSUMED. Sharpe is annualized from monthly net returns.

| Window | Strategy | Net P&L | Gross P&L | Costs | Sharpe | Max drawdown | Exposure | Round turns |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1973–1983 selection | `calendar_seasonal_gold_5m` | $6,613.70 | $6,817.11 | $203.41 | 0.6184 | −12.13% | 41.67% | 22 |
|  | `ts9_lo` | $25,906.52 | $25,997.95 | $91.44 | 1.0103 | −10.96% | 67.42% | 5 |
|  | `veto9` | $31,960.11 | $32,190.75 | $230.64 | 1.0469 | −17.35% | 96.21% | 12 |
| 1984–1989 confirmation | `calendar_seasonal_gold_5m` | $309.89 | $407.19 | $97.30 | 0.1062 | −16.30% | 41.67% | 12 |
|  | `ts9_lo` | $2,784.11 | $2,819.00 | $34.90 | 0.5615 | −9.08% | 41.67% | 3 |
|  | `veto9` | $3,625.71 | $3,699.49 | $73.79 | 0.5498 | −12.39% | 84.72% | 6 |
| 1990–1999 development | `calendar_seasonal_gold_5m` | $451.18 | $598.18 | $147.00 | 0.0947 | −22.07% | 41.67% | 20 |
|  | `ts9_lo` | −$1,171.24 | −$1,086.87 | $84.37 | −0.2579 | −14.22% | 36.67% | 12 |
|  | `veto9` | $1,827.96 | $1,975.09 | $147.13 | 0.2678 | −18.32% | 76.67% | 18 |

Development had **4/10 positive calendar years** and DSR **0.0024 at N=361**. The candidate beat `ts9_lo` in development by $1,622.42 and 0.3526 Sharpe, but trailed `veto9` by $1,376.78 and 0.1731 Sharpe. It failed both discovery Sharpe margins, both development comparisons against `veto9`, the six-positive-years gate, and both paired-uncertainty gates.

### Cost robustness and paired uncertainty

| Development view | Candidate net P&L |
|---|---:|
| Base ASSUMED costs | $451.18 |
| 2× base costs | $271.58 |
| 3× base costs (reported, non-gating) | $94.93 |
| Base costs + 0.25 bps/day financing assumption | $86.93 |

| Paired candidate-minus-comparator test | Mean monthly excess | One-sided 95% lower bound | One-sided p | Holm-adjusted p |
|---|---:|---:|---:|---:|
| vs `ts9_lo` | 0.001532 | −0.001570 | 0.2170 | 0.4340 |
| vs `veto9` | −0.001041 | −0.005201 | 0.6596 | 0.6596 |

Although the candidate stayed marginally positive under the frozen cost stresses, neither paired lower bound exceeded zero and neither Holm-adjusted p-value was ≤0.05. The candidate did not pass the preregistered statistical or comparator gates.

## Conclusion and safety state

The fixed calendar mask had positive but weak development net P&L and a positive Sharpe, yet its result was concentrated in four calendar years, missed the minimum six positive years, and did not beat `veto9`. Bootstrap uncertainty did not support a positive paired edge. This is a preregistered **REJECTED** trading candidate, not evidence that the seasonal-demand mechanism is profitable. Do not change the five-month mask, sizing, timing, or comparator and do not rerun on these partitions.

One outcome-calculated configuration moves the long-history denominator from **N=360 to N=361**. `strategy_promoted=false`, `orders_submitted=0`, `LIVE=LOCKED`, `post_1999_gold_prices_accessed=false`, and `holdout_accessed=false`. No DEMO or live execution occurred.
