# Results — Broad non-energy commodity-breadth gate on frozen gold trend

- **Cycle:** `LH-XAUUSD-COMMODITY-BREADTH-GATE-2026-10-19`
- **Protocol:** `docs/research/preregistration_longhistory_commodity_breadth_gate_2026-10-19.md`
- **Protocol SHA-256:** `d8b7ffae856d92eaba4ace166097c9809fdda51a7cc5003c8a56fd8e966f7bd2`
- **Protocol freeze commit (including pre-measurement Amendment A1):** `a303e3af418a0eb5ea816f608d1e58ae94de0d09`
- **Runner checkout at execution:** `75b8cd4f2e11af3667ab6bb0bd9bb03093ff4786`
- **Evidence:** `data/evidence/longhistory/commodity_breadth_gate_discovery_dev.json`
- **Verdict:** **REJECTED — no validated edge; no tuning or rescue.**

## Frozen candidate

One configuration was preregistered before converting eligible commodity prices or computing the breadth feature:

- Long gold only when the frozen 9-month gold trend is positive **and** at least 28 of the fixed 42 non-energy/non-precious commodity series have positive 12-month log returns ending one month earlier.
- Only raw `price_nominal_usd` values were used. All precomputed momentum, volatility, average, regime, and index columns were excluded.
- Gold was the only traded series. The basket excluded Gold, Silver, Platinum, all crude-oil series, and natural gas; this was neither a CMR metal basket nor a Brent-gate variant.
- Windows: 1973–1983 selection; 1984–1989 confirmation; 1990–1999 development. No evaluation stage.
- Cumulative development DSR count: `N=359` (358 inherited trials + one preregistered candidate). Costs are ASSUMED.

## Outcomes

Each account starts at USD 10,000. Values below are net USD and annualized monthly Sharpe.

| Window | Commodity-breadth candidate | `ts9_lo` comparator | `veto9` comparator |
|---|---:|---:|---:|
| 1973–1983 selection | **+$17,845.65 / 0.8947** | +$25,906.52 / 1.0103 | +$31,960.11 / 1.0469 |
| 1984–1989 confirmation | **−$372.19 / −0.1677** | +$2,784.11 / 0.5615 | +$3,625.71 / 0.5498 |
| 1990–1999 development | **+$117.97 / 0.1171** | −$1,171.24 / −0.2579 | +$1,827.96 / 0.2678 |

The candidate passed the selection positive-net subgate but failed both selection Sharpe-comparison gates. Confirmation net and Sharpe were negative and failed all confirmation gates. Development net and Sharpe were positive, and the candidate beat `ts9_lo` by $1,289.21 and 0.3750 Sharpe; it did not beat `veto9` (−$1,709.99 and −0.1507 Sharpe). The candidate had only 3 development round turns, 2/10 positive calendar years, 4.17% exposure, maximum drawdown −1.27%, and DSR `0.0017` at `N=359`.

Development gross P&L was +$144.06 and base costs were $26.09. Net remained positive at 2× costs (+$91.76), 3× costs (+$65.61), and under the financing assumption (+$80.03). This does not overcome the failed confirmation, low-turnover/year-count, `veto9`-comparison, and paired-uncertainty gates.

Paired development bootstrap results were not significant:

| Comparator | Mean monthly excess | One-sided 95% lower bound | Holm-adjusted p |
|---|---:|---:|---:|
| `ts9_lo` | +0.0010574 | −0.0003649 | 0.2658 |
| `veto9` | −0.0015154 | −0.0049189 | 0.7711 |

Neither lower bound exceeded zero and neither adjusted p-value met 0.05. The exact gate outcomes and monthly paired differences are in the evidence JSON.

## Data boundary and disposition

The frozen loader verified Gold plus all 42 basket series: 480 unique eligible monthly rows per series from 1960-01 through 1999-12. The model input contained 337 months from 1971-12 through 1999-12. Precomputed source-panel features were not used. Post-1999 price values converted: `0`; post-1999 FX values converted: `0`.

The commodity file is a pinned later snapshot without historical release/vintage timestamps. As preregistered, results are retrospective associations; the data cannot establish real-time point-in-time availability. No post-1999 price or FX value, evaluation metric, or 730-day tick row was opened. `held_out_span_opened=false`; `orders_submitted=0`; `strategy_promoted=false`; `LIVE=LOCKED`; real-capital exposure remains zero.

The candidate is closed. Do not change the 42-series panel, exclusions, lag, threshold, or combination rule on these reused partitions. Any future cycle must be separately preregistered and genuinely distinct; the 2000+ evaluation and 730-day holdout remain locked.
