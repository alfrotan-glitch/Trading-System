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
| Microstructure | Does a spread-exceeding move reverse on the next quote after one spread? | H-MS-01, preregistered |
| Microstructure | Is the next absolute move larger, in spread units, when the spread is wide? | H-MS-02, preregistered |
| Statistical structure | Dependence, clustering, and variance beyond those two tests | NOT TESTED |
| Regimes | Behavior conditional on a causal state label | NOT TESTED |
| Temporal structure | Hour, session, weekday | BLOCKED |
| Event/state behavior | Sequences other than the two preregistered quote events | NOT TESTED |
| Cross-feature conditionals | Interactions beyond spread and the next quote | NOT TESTED |

No family is assumed to be the edge. No model is fit because a simpler test has
not yet established a reason to.
