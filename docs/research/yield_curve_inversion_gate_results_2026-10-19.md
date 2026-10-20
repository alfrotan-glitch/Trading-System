# Yield-curve inversion gate — discovery/development results

**Hypothesis:** `LH-XAUUSD-YC-INVERSION-GATE-2026-10-19`
**Decision:** `REJECTED` — no validated edge; do not tune or rerun this candidate on the reused partitions.
**Evidence:** `data/evidence/longhistory/yield_curve_inversion_gate_discovery_dev.json`
**Runner:** `scripts/run_longhistory_yield_curve_inversion_gate.py`, checkout `1fb0ed89e6bc67a2759e0442a4dc847750b4cac0`
**Protocol:** `docs/research/preregistration_longhistory_yield_curve_inversion_gate_2026-10-19.md` (SHA-256 `005f134f1198bd557940a2a814d522334892b0fb6bc8f922e2915fb7f932b830`)
**Comparator amendment:** `docs/research/amendment_A1_longhistory_yield_curve_inversion_gate_comparator_source_2026-10-19.md` (SHA-256 `a8fe14283581f51d53d578c35eef5e4d257a09e47845c6d1f95a043ca789e8a5`)

## Frozen run and input verification

The one registered candidate, `yc_inversion_ts9_lo`, applied the prior-complete-month `GS10 monthly mean − DFF monthly mean < 0` gate to the frozen 9-month long-only gold trend. The comparators were unchanged `ts9_lo` and `veto9`. The screen ran once on discovery selection (1973–1983), discovery confirmation (1984–1989), and development (1990–1999), using the registered `fixed_units.v2` engine, separate USD 10,000 window accounts, frozen ASSUMED costs, and no final/evaluation stage.

All pinned local files passed their source identities before the signal/outcome calculation. The two CSVs whose checkout line endings did not preserve the upstream Git blobs (H.15 GS10 and H.10) were restored from the pinned Git objects and verified before parsing; their numeric rows were not inspected during that identity repair.

| Input | Pinned source | Eligible coverage | Verified identity |
|---|---|---|---|
| Gold `price_nominal_usd` | `awongstory/commodity-price-forecast-xgboost@c4a9f734d92df0d0a6c4744a2d7c34417ecd074b` | 480 months, 1960-01–1999-12 | blob `b31639d3bbf4c42ecd6406526d21bb7536e24ef9`; SHA-256 `3328bdff6156eb9ae11173ca2d52a8b207218cdd913ee0fa986be17d16e92aaf` |
| Monthly 10Y yield (GS10) | `datasets/bond-yields-us-10y@238315525deafefcf8334536990cafe23dc5eac4` | 561 months, 1953-04–1999-12 | blob `873ccc4e9c90ab9e5b79e326a6af5d9ccda8856f`; SHA-256 `314515604d06592af462d7e9ec8b4014d746c5ab21deb0a2e9ec72d1675c9265` |
| Daily DFF, averaged by month | `OpenSourceEcon/FedFundsPlot@167fd89006994f09f482b9e3c1ad23fecf276416` | 546 months, 1954-07–1999-12 | blob `df041eca9aee2e860b9d7cf1365f3ec960d525e9`; SHA-256 `cdf81e1afaa6999ed3bbd0677e90e9b7377232ab9fbd23d2dd1d2230a22aa1ce` |
| H.10 eight-currency comparator input | `datasets/exchange-rates@c023dd8b8f879610641a7391c0394c3bbb42d0f7` | Frozen comparator construction through 1999-12 | SHA-256 `68349ef41ecc0cf35fa00ba0d9d63ec93b45a5182c37d2bb9a368fcd654bfeaa` |

The model input spans 1971-12–1999-12 (337 monthly bars). The gold loader read only eligible pre-2000 price values and skipped later Gold rows using date/name only. Post-1999 gold-price, GS10, DFF, and H.10 numeric values converted: **0**. `FedFundsPlot` has no repository license and does not provide as-of vintage history; DFF remains internal-research-only. No production or redistribution rights are implied by this result.

## Results

Net and gross P&L are USD per separate USD 10,000 window account. Costs are ASSUMED. Sharpe is annualized from monthly net returns.

| Window | Strategy | Net P&L | Gross P&L | Costs | Sharpe | Max drawdown | Exposure | Round turns |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1973–1983 selection | `yc_inversion_ts9_lo` | $12,674.40 | $12,707.17 | $32.77 | 0.7787 | −8.79% | 33.33% | 3 |
|  | `ts9_lo` | $25,906.52 | $25,997.95 | $91.44 | 1.0103 | −10.96% | 67.42% | 5 |
|  | `veto9` | $31,960.11 | $32,190.75 | $230.64 | 1.0469 | −17.35% | 96.21% | 12 |
| 1984–1989 confirmation | `yc_inversion_ts9_lo` | −$7.71 | $0.00 | $7.71 | −0.4082 | −0.08% | 0.00% | 1 |
|  | `ts9_lo` | $2,784.11 | $2,819.00 | $34.90 | 0.5615 | −9.08% | 41.67% | 3 |
|  | `veto9` | $3,625.71 | $3,699.49 | $73.79 | 0.5498 | −12.39% | 84.72% | 6 |
| 1990–1999 development | `yc_inversion_ts9_lo` | −$967.43 | −$951.28 | $16.15 | −0.4368 | −10.88% | 4.17% | 2 |
|  | `ts9_lo` | −$1,171.24 | −$1,086.87 | $84.37 | −0.2579 | −14.22% | 36.67% | 12 |
|  | `veto9` | $1,827.96 | $1,975.09 | $147.13 | 0.2678 | −18.32% | 76.67% | 18 |

The candidate's development DSR was **0.0000 at N=360**. It had **0/10 positive development years** and only two round turns. Its development net P&L was $203.81 above `ts9_lo`, but still negative and $2,795.39 below `veto9`; its Sharpe was below both comparators. The candidate's positive selection-window net was the sole frozen subgate passed. It failed the selection and confirmation Sharpe margins, confirmation net profitability, every development activity/performance/comparator gate, and both paired-uncertainty comparisons.

### Cost robustness and paired uncertainty

| Development view | Candidate net P&L |
|---|---:|
| Base ASSUMED costs | −$967.43 |
| 2× base costs | −$983.08 |
| 3× base costs (reported, non-gating) | −$998.71 |
| Base costs + 0.25 bps/day financing assumption | −$998.70 |

| Paired candidate-minus-comparator test | Mean monthly excess | One-sided 95% lower bound | One-sided p | Holm-adjusted p |
|---|---:|---:|---:|---:|
| vs `ts9_lo` | 0.000130 | −0.000805 | 0.4219 | 0.8438 |
| vs `veto9` | −0.002443 | −0.005515 | 0.9081 | 0.9081 |

Both 95% lower bounds were non-positive and both Holm-adjusted p-values exceeded 0.05. The preregistered paired-uncertainty gates failed.

## Conclusion and safety state

The inversion gate was highly selective in the 1990s and did not capture a robust, diversified stream of long trades: it had 4.17% development exposure, two turns, negative net P&L and Sharpe, and no positive development years. The 1973–1983 positive result did not repeat in confirmation or development and did not outperform either comparator by the frozen Sharpe margin. This is a clean **REJECTED** result, not an inconclusive source failure. Do not change the spread threshold/sign, lag, averaging rule, comparator, or signal parameters and do not rerun on these partitions.

This one outcome-calculated configuration moves the long-history denominator from **N=359 to N=360**. The DSR is descriptive only; no candidate was promoted. `strategy_promoted=false`, `orders_submitted=0`, `LIVE=LOCKED`, `post_1999_gold_prices_accessed=false`, and `holdout_accessed=false`. The 2000+ price span and frozen 730-day holdout remain unopened. No production or DEMO execution occurred.
