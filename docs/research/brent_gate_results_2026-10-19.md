# Results — Lagged Brent gate on frozen gold trend

**Cycle:** `LH-XAUUSD-BRENT-GATE-2026-10-19`
**Protocol:** `docs/research/preregistration_longhistory_brent_inflation_gate_2026-10-19.md`
**Protocol SHA-256:** `764a31ab214877ca41c5692704f9eff6358861939cab20aa916072e5d02d9f5b`
**Protocol freeze commit:** `038ecfbf55838ad21dfce7d8a79bc893bbc2c5bd`
**Runner checkout at execution:** `674d0453c3c5faaffdbba6b2a999787724120cdf`
**Evidence:** `data/evidence/longhistory/brent_gate_discovery_dev.json`
**Verdict:** **REJECTED — no validated edge; no tuning or rescue.**

## Frozen candidate

One configuration was preregistered before candidate feature values were read:

- Long gold only when the frozen 9-month gold trend is positive **and** the 12-month Brent log return ending one month earlier is positive.
- Otherwise flat; no shorts. The Brent series is a macro gate, not an alternate precious-metal basket.
- Source: pinned World Bank Pink Sheet-derived monthly series, Gold and Crude oil, Brent, through 1999-12 only. USD comparator input is the pinned H.10 basket.
- Windows: 1973–1983 selection; 1984–1989 confirmation; 1990–1999 development. No evaluation stage.
- Cumulative development DSR count: `N=357` (356 inherited trials + one preregistered candidate). Costs are ASSUMED.

## Outcomes

Each account starts at USD 10,000. Values below are net USD and annualized monthly Sharpe.

| Window | Brent-gated candidate | `ts9_lo` comparator | `veto9` comparator |
|---|---:|---:|---:|
| 1973–1983 selection | **+$31,445.17 / 1.1585** | +$25,906.52 / 1.0103 | +$31,960.11 / 1.0469 |
| 1984–1989 confirmation | **−$151.46 / −0.0355** | +$2,784.11 / 0.5615 | +$3,625.71 / 0.5498 |
| 1990–1999 development | **−$1,658.02 / −0.6737** | −$1,171.24 / −0.2579 | +$1,827.96 / 0.2678 |

The candidate cleared the selection-only conditions (positive net and Sharpe at least 0.10 above both comparators). It failed confirmation. In development it had an 8-turn round trip count, only 1/10 positive calendar years, max drawdown −17.69%, and DSR 0.0000 at `N=357`.

Development net remained negative at 2× costs (−$1,710.80), 3× costs (−$1,763.28), and the financing assumption (−$1,781.60). Paired development bootstrap results were also negative:

| Comparator | Mean monthly excess | One-sided 95% lower bound | Holm-adjusted p |
|---|---:|---:|---:|
| `ts9_lo` | −0.0005249 | −0.0014946 | 1.0000 |
| `veto9` | −0.0030977 | −0.0061921 | 1.0000 |

Only the three selection gates passed. All confirmation and development gates failed. The exact per-gate outcomes and month-level paired differences are retained in the evidence JSON.

## Data boundary and disposition

Input preflight verified 480 monthly Gold rows and 480 monthly Brent rows from 1960-01 through 1999-12; the model frame contained 337 months from 1971-12 through 1999-12. The H.10 basket covered 1971-01 through 1999-12. Post-1999 price values converted: `0`; post-1999 FX values converted: `0`.

No 2000+ price observation, evaluation metric, or 730-day tick row was opened. `held_out_span_opened=false`; `orders_submitted=0`; `strategy_promoted=false`; `LIVE=LOCKED`; real-capital exposure remains zero. This result is a rejected discovery/development screen, not evidence for a trading claim.

The candidate is closed. Do not change the oil series, lag, lookback, sign, threshold, or combination rule on these reused partitions. Any future cycle must be a separately preregistered, genuinely distinct mechanism; the 2000+ evaluation and 730-day holdout remain locked.
