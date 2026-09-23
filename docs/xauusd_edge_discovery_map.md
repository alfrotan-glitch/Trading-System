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
| State magnitude | Does a high recent 16-quote absolute move predict a larger 256-quote absolute move? | H-ST-02 TESTED. Ratio 1.48. Process structure, not a directional trade and not a strategy. |
| State direction | After a mid-sign run of length at least 5, does the 256-quote move fade? | H-ST-03 REJECTED. Fade rate 0.494. Residual after one spread plus one cent is negative. |
| State direction | Does the sign of a past 16-quote displacement predict a cost-surviving 256-quote move conditional on the locked high/low volatility states? | H-DIR-01 PREREGISTERED, NOT TESTED. [Decision and one bounded protocol](xauusd_directional_next_step_2026-09-23.md); [independent metadata audit](xauusd_directional_boundary_audit_2026-09-23.md): original part 441 straddles Discovery/held-out, so access is BLOCKED and H-DIR-01 is NOT RUN. Held-out quote rows remained closed in this audit. |
| State direction | Does the same 16→256 directional mechanism survive on the maximal verifiable prefix (70,783,710 rows, 99.928% of Discovery) without opening the straddling part? | **H-DIR-02 REJECTED.** [Preregistration](xauusd_directional_next_step_H-DIR-02_2026-09-23.md); [verifiable view manifest](xauusd_directional_H-DIR-02_view_manifest.json) + [authority](xauusd_directional_view_authority_H-DIR-02.json); Actions `35860835154` — `scan_attested_view` with `preflight_view` on every row-group `< cutoff`, `held_out_span_opened=false`. T1 (high-state cost-stressed net) **−$0.300** (< $0.05 floor), T2 (high−low gross) **−$0.0016** (< $0.05), all gates false; `reports/xauusd_directional_H-DIR-02_state.json` (VERIFIABLE_ROWS 70783710, omitted 50716). Mechanism rejected on this 70.78M sample; H-DIR-01 remains separately blocked. |
| State magnitude | Does leaving a persistent spread enlarge the 256-quote absolute move? | H-ST-04 REJECTED. Ratio 1.07, below 1.15. Not the rejected widen-versus-tighten test. |
| Volatility cost | Does the H-ST-02 contrast still clear spread plus two cents, and does high reach spread plus one cent sooner? | H-VL-01 TESTED. Lift 7.5 percentage points. Median wait 17 versus 29 quotes. Not a trade. |
| Volatility tail | Does a recent move of at least $0.40 have a larger 256-quote absolute move than high-but-not-extreme? | H-VL-02 TESTED. Ratio 1.36. Dollar gap $0.34. Not a trade. |
| Volatility transition | Does quiet-to-expansion have a larger 256-quote absolute move than staying quiet? | H-VL-03 TESTED. Ratio 1.34. Dollar gap $0.223, just above the $0.22 floor. Not a trade. |
| Volatility persistence | Does persistent high have a larger 256-quote absolute move than contraction onset? | H-VL-04 TESTED. Ratio 1.45. Dollar gap $0.43. Not an exhaustion trade. |
| Statistical structure | Dependence beyond the locked families | NOT TESTED. H-ST-02 is one absolute-move contrast, not a general dependence claim. |
| Regimes | State labels other than the locked family | NOT TESTED. Ranked panel cells are hypothesis generators, not tests. The 38-cent mode stays descriptive. |
| Temporal structure | Hour, session, weekday | BLOCKED. Timestamp basis is not confirmed. |
| Event/state behavior | Sequences other than the locked state family | NOT TESTED. Horizon 4096 signed cells were descriptive and were not confirmed. |
| Cross-feature conditionals | Interactions other than wide×activity, recent volatility, and persistence leave/stay | NOT TESTED. |

No family is assumed to be the edge. No model is fit. The measured magnitude
clustering survived the locked cost filter and is still not a reason to add a
model, to invent a side, or to open the held-out span.
