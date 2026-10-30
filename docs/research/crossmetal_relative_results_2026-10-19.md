# Cross-Metal Relative-Momentum Screen — 2026-10-19

**Status:** `REJECTED` — discovery/development only; not validation.

This is the single frozen `cmr12_longflat` rule. No 2000+ price/rate values were converted or evaluated. The 730-day MT5 holdout remains closed.

## Predeclared window outcomes

| Window | Rule | Net USD | Gross USD | Fill costs | Financing | Sharpe | DSR* | Max DD | Exposure | Turns |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| discovery_selection | cmr12_longflat | 5892.01 | 5964.27 | 72.26 | 0.00 | 0.5295 | — | -0.2163 | 0.5758 | 5 |
| discovery_selection | ts9_lo | 25906.52 | 25997.95 | 91.44 | 0.00 | 1.0103 | — | -0.1096 | 0.6742 | 5 |
| discovery_selection | veto9 | 31960.11 | 32190.75 | 230.64 | 0.00 | 1.0469 | — | -0.1735 | 0.9621 | 12 |
| discovery_confirmation | cmr12_longflat | -630.49 | -590.74 | 39.75 | 0.00 | -0.0854 | — | -0.1952 | 0.6389 | 5 |
| discovery_confirmation | ts9_lo | 2784.11 | 2819.00 | 34.90 | 0.00 | 0.5615 | — | -0.0908 | 0.4167 | 3 |
| discovery_confirmation | veto9 | 3625.71 | 3699.49 | 73.79 | 0.00 | 0.5498 | — | -0.1239 | 0.8472 | 6 |
| development | cmr12_longflat | -2627.82 | -2561.25 | 66.58 | 0.00 | -0.4852 | 0.0000 | -0.2726 | 0.4250 | 8 |
| development | ts9_lo | -1171.24 | -1086.87 | 84.37 | 0.00 | -0.2579 | 0.0001 | -0.1422 | 0.3667 | 12 |
| development | veto9 | 1827.96 | 1975.09 | 147.13 | 0.00 | 0.2678 | 0.0186 | -0.1832 | 0.7667 | 18 |

*DSR is reported only for the 1990–1999 development window, using the frozen descriptive denominator `N=356`; it is not a gate.*

### Calendar-year returns

| Window | Rule | Calendar-year returns |
|---|---|---|
| discovery_selection | cmr12_longflat | 1973 +32.14%, 1974 +18.97%, 1975 -12.46%, 1976 +0.00%, 1977 +5.16%, 1978 +8.53%, 1979 +0.00%, 1980 +1.50%, 1981 -7.45%, 1982 +3.98%, 1983 +3.58% |
| discovery_selection | ts9_lo | 1973 +32.14%, 1974 +20.45%, 1975 -10.92%, 1976 +0.00%, 1977 +12.81%, 1978 +25.52%, 1979 +50.10%, 1980 +22.41%, 1981 -0.06%, 1982 +1.82%, 1983 -4.34% |
| discovery_selection | veto9 | 1973 +32.14%, 1974 +20.45%, 1975 -9.40%, 1976 +11.40%, 1977 +13.55%, 1978 +25.52%, 1979 +50.10%, 1980 +22.41%, 1981 +6.95%, 1982 -2.26%, 1983 -4.57% |
| discovery_confirmation | cmr12_longflat | 1984 -13.85%, 1985 +0.14%, 1986 +4.32%, 1987 +11.05%, 1988 -14.04%, 1989 +9.06% |
| discovery_confirmation | ts9_lo | 1984 +0.00%, 1985 -1.00%, 1986 +22.36%, 1987 +15.83%, 1988 -8.82%, 1989 -0.08% |
| discovery_confirmation | veto9 | 1984 +13.58%, 1985 -4.66%, 1986 +22.36%, 1987 +15.83%, 1988 -8.82%, 1989 -2.64% |
| development | cmr12_longflat | 1990 -7.51%, 1991 -2.48%, 1992 -6.68%, 1993 +9.13%, 1994 +0.00%, 1995 +0.73%, 1996 -5.89%, 1997 -4.70%, 1998 -0.77%, 1999 -10.46% |
| development | ts9_lo | 1990 -8.80%, 1991 -0.53%, 1992 +0.00%, 1993 +1.94%, 1994 -1.97%, 1995 +2.40%, 1996 -1.69%, 1997 +0.00%, 1998 -1.36%, 1999 -1.93% |
| development | veto9 | 1990 -8.80%, 1991 +0.09%, 1992 +5.93%, 1993 -8.93%, 1994 -2.88%, 1995 +2.40%, 1996 +1.42%, 1997 +26.27%, 1998 -4.67%, 1999 +10.63% |

## Development cost stresses

| Cost regime | Net USD | Gross USD | Fill costs | Financing | Sharpe |
|---|---:|---:|---:|---:|---:|
| 2x_base | -2683.39 | -2550.69 | 132.70 | 0.00 | -0.4977 |
| 3x_base | -2738.58 | -2540.20 | 198.38 | 0.00 | -0.5102 |
| financing_0_25_bps_day | -2884.70 | -2511.63 | 65.37 | 307.69 | -0.5430 |

## Paired development uncertainty

| Comparator | Mean monthly excess | One-sided 95% lower bound | Raw p | Holm p |
|---|---:|---:|---:|---:|
| ts9_lo | -0.00143805 | -0.00340711 | 0.8874 | 1.0000 |
| veto9 | -0.00401085 | -0.00875010 | 0.9166 | 1.0000 |

The complete 120-month candidate/comparator net-return pairs and differences are preserved in the JSON evidence artifact.

## Frozen gates

| Gate | Result |
|---|---|
| discovery_selection_candidate_net_positive | PASS |
| discovery_selection_beats_ts9_lo_sharpe_by_0_10 | FAIL |
| discovery_selection_beats_veto9_sharpe_by_0_10 | FAIL |
| discovery_confirmation_candidate_net_positive | FAIL |
| discovery_confirmation_beats_ts9_lo_sharpe_by_0_10 | FAIL |
| discovery_confirmation_beats_veto9_sharpe_by_0_10 | FAIL |
| development_candidate_net_positive | FAIL |
| development_candidate_sharpe_positive | FAIL |
| development_at_least_20_round_turns | FAIL |
| development_at_least_6_positive_years | FAIL |
| development_beats_ts9_lo_by_500_usd | FAIL |
| development_beats_ts9_lo_sharpe_by_0_10 | FAIL |
| development_beats_veto9_by_500_usd | FAIL |
| development_beats_veto9_sharpe_by_0_10 | FAIL |
| development_positive_at_2x_cost | FAIL |
| development_positive_with_financing_assumption | FAIL |
| development_ts9_lo_bootstrap_lower_95_positive | FAIL |
| development_ts9_lo_holm_p_le_0_05 | FAIL |
| development_veto9_bootstrap_lower_95_positive | FAIL |
| development_veto9_holm_p_le_0_05 | FAIL |

Trial-count note: `N=356` is the long-history lineage denominator used only for development DSR. The separate `qts edge` experiment ledger records 304 in a distinct registry; the counts are not combined.
Source-ingestion audit: `docs/research/crossmetal_ingest_boundary_audit_2026-10-19.md` records a premeasurement blank-rate correction; the frozen protocol and candidate were unchanged.
Costs are ASSUMED. No candidate is promoted; no broker or order path was used; LIVE remains locked.
