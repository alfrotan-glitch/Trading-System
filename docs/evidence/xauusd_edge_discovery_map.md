# XAUUSD edge discovery map

This is the search ledger. It is not a strategy. A row stays `NOT TESTED` or
`BLOCKED` until a preregistered test is measured. Measured rejections stay
rejections. The canonical archive is not repaired. The last 40 percent of the
raw `time_msc` span is locked and is not used to choose a hypothesis.

## Separation

- Data facts are counts, ranges, and quote fields measured from the archive.
- Research assumptions are stated before a test. They are not facts.
- Derived features are mid, spread, next mid change, and spread-scaled absolute next mid change.
- Hypotheses predict a relationship. A failed prediction stays in the ledger.

## Clock

Timestamp basis is not confirmed. Blocked until it is: hour of day, session,
day of week, weekend labels, and H-TOD-01. Raw order, bid, ask, and spread
remain usable.

## Map

| Family | Question | Status |
| --- | --- | --- |
| Microstructure | Does a spread-exceeding move reverse on the next quote after one spread? | H-MS-01 REJECTED. |
| Microstructure | Is the next absolute move larger, in spread units, when the spread is wide? | H-MS-02 REJECTED. The reversed comparison was not preregistered. |
| Quote process | Do one-sided and two-sided updates differ in next-quote continuation? | H-QD-01 REJECTED. |
| Quote process | Does the next mid-change sign depend on the current sign beyond independence? | H-QD-02 REJECTED. Tilt was below the floor and lost one spread. |
| Quote process | Do short gaps cluster? | H-INT-01 REJECTED. At 100 ms the lift was negative. |
| Quote process | Does the spread stay put more than an independent draw? | H-SP-01 TESTED. Process structure, not a return predictor. |
| Quote process | Does a one-sided bid update predict the next 1-cent move? | H-MV-01 REJECTED. |
| Quote process | Do short gaps precede larger 16-quote absolute moves? | H-VOL-01 REJECTED. Ratio below the floor. |
| Quote process | Does a widen precede a larger 16-quote move than a tighten? | H-SPR-01 REJECTED. |
| Trade prints | Size, aggressor, or last-price behavior | BLOCKED. `volume` and `last` are zero on every row. |
| State magnitude | Does wide-and-active have a larger 256-quote absolute move than wide-and-quiet? | H-ST-01 REJECTED. Ratio 1.20, below 1.25. Exceed-spread lift 3.8 pp, below 5. |
| State magnitude | Does a high recent 16-quote absolute move predict a larger 256-quote absolute move? | H-ST-02 TESTED on full Discovery (ratio 1.48) but **NOT ROBUST walk-forward**: **H-ST-02WF REJECTED.** [Preregistration](../xauusd_magnitude_walkforward_H-ST-02WF_2026-09-23.md); 5-fold on same verifiable 70.78M view; Actions `35862228204` — `WalkForwardScan` with `preflight_view`. Fold ratios 1.19/1.23/1.25/1.16/1.36 and lifts 0.046/0.049/0.032/0.029/0.046 — all lifts **<0.05**, 3 ratios <1.25, one fold blocks 45 <50. All folds sign-positive (ratio>1, lift>0) and CV 0.055 stable, but no fold clears `ratio≥1.25 & gap≥$0.10 & lift≥0.05`. Process structure, not a directional trade, not robust to time. `reports/xauusd_walkforward_state.json`. |
| State direction | After a mid-sign run of length at least 5, does the 256-quote move fade? | H-ST-03 REJECTED. Fade rate 0.494. Residual after one spread plus one cent is negative. |
| State direction | Does the sign of a past 16-quote displacement predict a cost-surviving 256-quote move conditional on the locked high/low volatility states? | H-DIR-01 PREREGISTERED, NOT TESTED. [Decision and one bounded protocol](../xauusd_directional_next_step_2026-09-23.md); [independent metadata audit](xauusd_directional_boundary_audit_2026-09-23.md): original part 441 straddles Discovery/held-out, so access is BLOCKED and H-DIR-01 is NOT RUN. Held-out quote rows remained closed in this audit. |
| State direction | Does the same 16→256 directional mechanism survive on the maximal verifiable prefix (70,783,710 rows, 99.928% of Discovery) without opening the straddling part? | **H-DIR-02 REJECTED.** [Preregistration](../xauusd_directional_next_step_H-DIR-02_2026-09-23.md); [verifiable view manifest](../../reports/xauusd_directional_H-DIR-02_view_manifest.json) + [authority](xauusd_directional_view_authority_H-DIR-02.json); Actions `35860835154` — `scan_attested_view` with `preflight_view` on every row-group `< cutoff`, `held_out_span_opened=false`. T1 (high-state cost-stressed net) **−$0.300** (< $0.05 floor), T2 (high−low gross) **−$0.0016** (< $0.05), all gates false; `reports/xauusd_directional_H-DIR-02_state.json` (VERIFIABLE_ROWS 70783710, omitted 50716). Mechanism rejected on this 70.78M sample; H-DIR-01 remains separately blocked. |
| State direction | Does spread state (tighten vs widen, one-sided) predict the next 16/64 mid direction after spread+2c? | **H-DIR-03a/b REJECTED.** [Preregistration](../xauusd_directional_next_step_H-DIR-03_2026-09-23.md); same verifiable view; Actions `35861163668` — `SpreadDirectionalScan` with `preflight_view`. At 16q: tighten `n=65881` vs widen `61815`, lift **−0.016** (<0.02), pooled net **−$0.305**; bid_up_same `180294` vs bid_down_same `174639`, lift **−0.0076**, pooled **−$0.295**. At 64q lifts −0.004/−0.005, nets −$0.30/−$0.29. All terciles/gap/stability gates false. `reports/xauusd_spread_directional_state.json`. |
| State magnitude | Does raw hour (active 15,16,17 vs quiet 0,1,23) predict larger absolute 16-quote move and exceed-spread+2c? | **H-TEMP-01 REJECTED.** [Preregistration](../xauusd_temporal_next_step_H-TEMP-01_2026-09-23.md); same verifiable view; Actions `35862027176` — `TemporalScan` with `preflight_view`. At 16q: active `952933` mean $0.232 vs quiet `127521` mean $0.302, ratio **0.77** (<1.25), gap **−$0.07**, lift **0.036** (<0.05). Inverted: quiet > active. At 64q ratio 0.75. All gates false. `reports/xauusd_temporal_state.json`. Descriptive raw-hour ticks 77k at 0 vs 5.7M at 16 and abs16 0.169–0.476 produced this test but did not predict its direction. |
| State magnitude | Does leaving a persistent spread enlarge the 256-quote absolute move? | H-ST-04 REJECTED. Ratio 1.07, below 1.15. Not the rejected widen-versus-tighten test. |
| Volatility cost | Does the H-ST-02 contrast still clear spread plus two cents, and does high reach spread plus one cent sooner? | H-VL-01 TESTED. Lift 7.5 percentage points. Median wait 17 versus 29 quotes. Not a trade. |
| Volatility tail | Does a recent move of at least $0.40 have a larger 256-quote absolute move than high-but-not-extreme? | H-VL-02 TESTED. Ratio 1.36. Dollar gap $0.34. Not a trade. |
| Volatility transition | Does quiet-to-expansion have a larger 256-quote absolute move than staying quiet? | H-VL-03 TESTED. Ratio 1.34. Dollar gap $0.223, just above the $0.22 floor. Not a trade. |
| Volatility persistence | Does persistent high have a larger 256-quote absolute move than contraction onset? | H-VL-04 TESTED. Ratio 1.45. Dollar gap $0.43. Not an exhaustion trade. |
| Statistical structure | Dependence beyond the locked families | NOT TESTED. H-ST-02 is one absolute-move contrast, not a general dependence claim. |
| Regimes | State labels other than the locked family | NOT TESTED. Ranked panel cells are hypothesis generators, not tests. The 38-cent mode stays descriptive. |
| Temporal structure | Hour, session, weekday | BLOCKED. Timestamp basis is not confirmed. |
| Event/state behavior | Sequences other than the locked state family | NOT TESTED. Horizon 4096 signed cells were descriptive and were not confirmed. |
| Cross-feature conditionals | Interactions other than wide×activity, recent volatility, and persistence leave/stay | **H-XF-01 INCONCLUSIVE** (insufficient tercile-2 tight). [Preregistration](../xauusd_cross_next_step_H-XF-01_2026-09-23.md); same verifiable 70.78M view; Actions `35862702846` — `CrossScan` locked spread `tight ≤0.20` vs `wide ≥0.27` within `trail16≥0.20`. Pooled 256: High+Wide `42,086` mean **$1.32** vs High+Tight `8,647` mean **$0.645**, ratio **2.04** (pass), gap **$0.67** (pass), lift **0.042** (<0.05); 1024 ratio 2.02 lift 0.006. Terciles: 0 ratio 1.26 lift **−0.076**, 1 ratio 1.96 lift 0.048, 2 ratio 1.10 lift **−0.063** with `n_B=481` (<1000) → INCONCLUSIVE. Gap/delay ratios 2.03. `reports/xauusd_cross_state.json`. **H-XF-02 REJECTED.** [Preregistration](../xauusd_cross_next_step_H-XF-02_2026-09-23.md); same view; Actions `35862918711` — `CrossActivityScan` locked `High+Active (gap≤100ms)` vs `High+Quiet (gap>500ms)`. Pooled 256: Active `26,075` mean **$1.13** vs Quiet `14,870` mean **$0.983**, ratio **1.15** (<1.25), gap **$0.15** (pass), lift **0.025** (<0.05); 1024 ratio 1.09 lift 0.013. Terciles ratios 1.09/1.11/1.20 with lifts 0.045/0.024/0.023 sign-positive but below floors. `reports/xauusd_cross_activity_state.json`. |
| Market-making | Does low-vol tight spread capture spread via limit fills with smaller adverse excursion than high-vol wide? | **H-MM-01 REJECTED by absolute-net gate but shows risk edge** (see above) `reports/xauusd_marketmaking_state.json` (lift 0.054 ratio 2.62 gap 0.809, risk-adj 0.174 vs 0.121). **H-MM-02 REJECTED walk-forward 5-fold risk-adjusted.** [Preregistration](../xauusd_marketmaking_next_step_H-MM-02_2026-09-23.md); same view; Actions `35864781455` — `MarketMakingWFScan` 5-fold time splits. Full: F 78.2% vs U 72.8% lift 0.054 ratio 2.62 gap 0.809 net_F $0.132. Folds: 0 lift 0.060 ratio1.52 risk 0.192<0.215 **fail**, 1 lift0.061 ratio1.64 risk0.175<0.196 fail, 2 lift0.027 ratio2.16 risk0.141>0.118 but lift<0.05 fail, 3 lift0.036 ratio1.14 risk0.091<0.137 fail, 4 lift0.005 ratio1.19 risk0.060<0.095 fail. No fold clears `lift≥0.05 & ratio≥1.25 & risk_F>risk_U & net_F>0.08 & 2× net>0`. `reports/xauusd_marketmaking_wf_state.json`. |
| Timeframe 1m (derived) | Does 1m Donchian 20-bar breakout predict 12-bar/48-bar net after 5 bps + $0.02 and 1-bar latency? | **H-1M-01 REJECTED.** [Preregistration](../xauusd_1m_next_step_H-1M-01_2026-09-23.md); 1m bars derived from verifiable tick mids (423,490 bars, 53,653 events: 29,052 long / 24,601 short); Actions `35865595759` — `OneMScan` 20 lookback, 12 primary/48 stability. Long mean **−4.77 bps** PF **0.255** win 24.4%, Short mean **−5.30 bps** PF 0.281 win 22.4%, Baseline mean **−4.95 bps** PF 0.234 win 23.7%; H48 long +0.49 bps short −0.65 bps. All terciles mean negative. `reports/xauusd_1m_state.json` `SYNTHETIC_DERIVED`. |

No family is assumed to be the edge. No model is fit. The measured magnitude
clustering survived the locked cost filter and is still not a reason to add a
model, to invent a side, or to open the held-out span.
