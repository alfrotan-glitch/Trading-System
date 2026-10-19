# Results — Lagged FX-dispersion gate on frozen gold trend

**Cycle:** `LH-XAUUSD-FX-DISPERSION-GATE-2026-10-19`
**Protocol:** `docs/research/preregistration_longhistory_fx_dispersion_gate_2026-10-19.md`
**Protocol SHA-256:** `8f879945749943a19223db709b371c0eb75a4eb2de2fdfc03ef1c2b6f18d909c`
**Protocol freeze commit:** `7be45522c9e962c963614159d37546bd813a87a7`
**Runner checkout at execution:** `9bc6e03c5f08ec1b66606d4859c36f0ad77df283`
**Evidence:** `data/evidence/longhistory/fx_dispersion_gate_discovery_dev.json`
- **Runner status:** `REJECTED` — the frozen screen failed its gates.
- **Research interpretation:** **INCONCLUSIVE for the intended FX-dispersion hypothesis** because a pre-existing repository quote-convention contract conflicts with the orientation preregistered here. No corrected rerun or tuning is authorized.

## Frozen candidate

One configuration was preregistered before computing or inspecting FX-dispersion feature values or this candidate's returns:

- Long gold only when the frozen 9-month gold trend is positive **and** the one-month-lagged population standard deviation across eight common-orientation 12-month currency log returns is at least `0.05`.
- The Australia, New Zealand, and United Kingdom quote series were inverted as prescribed by the pinned dataset's quote metadata; no currency subset or alternate statistic was tested.
- Otherwise flat; no shorts. This is a cross-sectional FX-dispersion hypothesis, not a CMR basket/parameter variant and not a rerun of the Brent gate.
- Windows: 1973–1983 selection; 1984–1989 confirmation; 1990–1999 development. No evaluation stage.
- Cumulative development DSR count: `N=358` (357 inherited trials + one preregistered candidate). Costs are ASSUMED.

## Outcomes

Each account starts at USD 10,000. Values below are net USD and annualized monthly Sharpe.

| Window | FX-dispersion candidate | `ts9_lo` comparator | `veto9` comparator |
|---|---:|---:|---:|
| 1973–1983 selection | **+$20,124.35 / 0.9072** | +$25,906.52 / 1.0103 | +$31,960.11 / 1.0469 |
| 1984–1989 confirmation | **+$2,784.11 / 0.5615** | +$2,784.11 / 0.5615 | +$3,625.71 / 0.5498 |
| 1990–1999 development | **−$1,000.05 / −0.2158** | −$1,171.24 / −0.2579 | +$1,827.96 / 0.2678 |

The candidate had positive net in the two discovery windows but failed all four required Sharpe-comparison gates: its selection Sharpe was below both comparators, and its confirmation Sharpe advantage was below 0.10 against both. In development it had a 14-turn round-trip count, only 2/10 positive calendar years, maximum drawdown −14.22%, and DSR `0.0001` at `N=358`.

Development candidate gross P&L was −$899.54 and base costs were $100.51. Net remained negative at 2× costs (−$1,097.07), 3× costs (−$1,193.10), and under the financing assumption (−$1,262.00). The candidate beat `ts9_lo` by only $171.19 and 0.0421 Sharpe, missing the frozen $500 and 0.10 thresholds; it trailed `veto9` by $2,828.01 and 0.4836 Sharpe.

Paired development bootstrap results were not supportive:

| Comparator | Mean monthly excess | One-sided 95% lower bound | Holm-adjusted p |
|---|---:|---:|---:|
| `ts9_lo` | +0.0001592 | approximately 0 (−3.43e−15) | 0.1738 |
| `veto9` | −0.0024136 | −0.0056976 | 0.8942 |

The lower bounds did not exceed zero and neither adjusted p-value met 0.05. Only the two positive-net discovery subgates passed; all selection/confirmation Sharpe gates and all development gates failed under the frozen formula. The exact per-gate outcomes and month-level paired differences are retained in the evidence JSON.

## Post-run quote-convention integrity finding

After the single authorized run, a whole-repository audit found that the pre-existing `scripts/build_longhistory_monthly_dataset.py` explicitly treats **all eight** basket series as `currency per USD`, notes that the pinned `datasets/exchange-rates` README's inversion claims for Australia, New Zealand, and the United Kingdom do not match the extract, and encodes quote probes that reject the inverted reading. The preregistration and runner instead followed those README inversion claims for those three series. This source-semantics conflict means the runner's calculated feature is not established as the intended cross-sectional dispersion of consistently oriented currency returns.

The evidence JSON therefore correctly preserves the frozen runner's gate status `REJECTED`, but that is **not a clean rejection of the intended economic hypothesis**; its research interpretation is `INCONCLUSIVE`. This conflict was found after candidate outcomes were available. Do not inspect additional FX values to resolve it, change the quote orientation, overwrite evidence, or rerun on these reused partitions. The `N=358` attempted-configuration count remains in force; the issue adds no alternate trial and grants no permission to promote or trade.

## Data boundary and disposition

Input preflight verified 480 eligible Gold monthly rows from 1960-01 through 1999-12, 348 H.10 monthly closes from 1971-01 through 1999-12, and at least six currencies in every monthly close (minimum coverage was eight). The model input contained 337 months from 1971-12 through 1999-12. Post-1999 price values converted: `0`; post-1999 FX values converted: `0`.

No post-1999 price or FX rate value, evaluation metric, or 730-day tick row was opened. `held_out_span_opened=false`; `orders_submitted=0`; `strategy_promoted=false`; `LIVE=LOCKED`; real-capital exposure remains zero. The runner's result is rejected under the registered transformation, while the intended dispersion hypothesis remains inconclusive; neither outcome supports a trading claim.

The candidate is closed. Do not change the currency set, quote orientation, statistic, lookback, lag, threshold, or combination rule on these reused partitions. Any future cycle must be a separately preregistered, genuinely distinct mechanism; the 2000+ evaluation and 730-day holdout remain locked.
