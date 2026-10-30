# Results — Lagged Sahm/U3 labor-stress gate on frozen Gold trend

- **Hypothesis:** `LH-XAUUSD-SAHM-U3-GATE-2026-10-20`
- **Decision:** **REJECTED** — do not tune or rerun the candidate on these partitions.
- **Protocol:** `docs/research/preregistration_longhistory_sahm_unemployment_gate_2026-10-20.md` (SHA-256 `160a2babca41d9f9cf0886d9ece8921b284bdb00ab0bfd38dffcd6751936d73d`)
- **Evidence:** `data/evidence/longhistory/sahm_u3_gate_discovery_dev.json`
- **Runner:** `scripts/run_longhistory_sahm_unemployment_gate.py`; one screen invocation.
- **Cumulative long-history denominator:** `N=362` (one new outcome-calculated configuration from `N=361`).

## Frozen candidate and sources

The one candidate, `sahm_u3_ts9_longflat`, kept the inherited 9-month long-or-flat Gold trend only when a two-month-lagged Sahm U3 indicator was at least 0.50 percentage points. The indicator is the current 3-month average U3 rate minus the minimum of the previous 12 three-month averages. `ts9_lo` and `veto9` were reproduced unchanged. Sizing, monthly execution, separate USD 10,000 window accounts, cost assumptions, and screen gates were frozen in advance.

Gold and the H.10 comparator used the prior pinned inputs. The U3 snapshot was `pmichaillat/feru@23d5e7795325ce1a69d02bd52e20ad075983082a`, `raw/UNRATE.csv`, blob `3e09b6924c5a010da67ffc2e850f9331bd7cdb4b`, SHA-256 `c3be736b31e2ea488076b46190efbfa1762ea0bdf6171e92585e710523840a78`. The repository identifies the upstream series as seasonally adjusted U.S. BLS U-3 unemployment. The pinned file contains 624 eligible monthly observations from 1948-01 through 1999-12. The repository has an MIT license, but the U3 file has no separate vintage history; the protocol treats it as a revised historical snapshot and does not support a real-time or production claim.

**Post-run source metadata erratum:** the frozen protocol and initial run record misspelled the source commit's last character (`…082e` instead of `…082a`). The corrected commit tree contains the exact recorded `raw/UNRATE.csv` Git blob SHA-1; no data values were read and the screen was not rerun. The frozen protocol remains unchanged; see `docs/research/erratum_sahm_u3_source_revision_2026-10-20.md`.

Only pre-2000 Gold, H.10, and U3 numerical values were converted. The model span was 1971-12 through 1999-12 (337 months). Post-1999 Gold price values converted: **0**; post-1999 H.10 values converted: **0**; post-1999 U3 values converted: **0**. The screen runner did not read 2000+ evaluation metrics or locked 730-day tick values.

## Results

Net P&L is USD per separate USD 10,000 window account; Sharpe is annualized monthly net-return Sharpe. Costs are ASSUMED.

| Window | Candidate net | Candidate Sharpe | Candidate turns | Candidate positive years | `ts9_lo` net / Sharpe | `veto9` net / Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| 1973–1983 selection | −$512.28 | −0.1185 | 5 | 3/11 | +$25,906.52 / 1.0103 | +$31,960.11 / 1.0469 |
| 1984–1989 confirmation | $0.00 | 0.0000 | 0 | 0/6 | +$2,784.11 / 0.5615 | +$3,625.71 / 0.5498 |
| 1990–1999 development | −$52.81 | −0.4661 | 2 | 0/10 | −$1,171.24 / −0.2579 | +$1,827.96 / 0.2678 |

The candidate was unprofitable in selection, placed no trades in confirmation, and made only two development round turns. It failed the selection and confirmation net/Sharpe gates, development positive-net/positive-Sharpe, minimum-turnover and positive-year gates, the `veto9` comparisons, cost robustness, and both paired-uncertainty tests. It did beat `ts9_lo` by $1,118.43 in development net dollars, but its development Sharpe was lower.

| Development cost view | Candidate net P&L |
|---|---:|
| Base ASSUMED costs | −$52.81 |
| 2× base costs | −$65.89 |
| 3× base costs | −$78.96 |
| Base + 0.25 bps/day financing assumption | −$64.24 |

| Paired development comparison | Mean monthly excess | One-sided 95% lower bound | Holm-adjusted p |
|---|---:|---:|---:|
| vs `ts9_lo` | +0.000911 | −0.000508 | 0.3334 |
| vs `veto9` | −0.001662 | −0.005106 | 0.7897 |

Neither bootstrap lower bound exceeded zero and neither Holm-adjusted p-value met 0.05. The candidate therefore failed the frozen screen; low activity and revised-vintage data also preclude a real-time trading interpretation.

## Disposition and safety

The fixed Sahm/U3 gate is **closed**. Do not adjust the threshold, averaging window, lag, Gold rule, or comparators, and do not rerun it on these partitions. The result is not a validated edge and does not alter frozen champions or trading policy. `strategy_promoted=false`; `orders_submitted=0`; `LIVE=LOCKED`; `holdout_accessed=false`. The cumulative long-history trial count is now **N=362**. The separate `qts edge` SQLite count remains uncombined.
