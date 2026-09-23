# XAUUSD edge discovery map

This is the search plan. It is not a result and not a strategy. Statuses here
are `NOT TESTED` or `BLOCKED` until a preregistered test is measured. The
canonical archive is not repaired. The last 40 percent of the raw `time_msc`
span is locked and is not used to choose a hypothesis.

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
| Statistical structure | Dependence, clustering, and variance beyond those two tests | NOT TESTED |
| Regimes | Behavior conditional on a causal state label | NOT TESTED |
| Temporal structure | Hour, session, weekday | BLOCKED. Timestamp basis is not confirmed. |
| Event/state behavior | Sequences other than the two preregistered quote events | NOT TESTED |
| Cross-feature conditionals | Interactions beyond spread and the next quote | NOT TESTED |

No family is assumed to be the edge. No model is fit because a simpler test has
not yet established a reason to.
