# XAUUSD microstructure preregistration

Registered before the measurement run. The discovery window is the first 60 percent
of the raw `time_msc` span, `time_msc < min + (span * 60) // 100`. The locked
span is not read for a hypothesis, a threshold, or a feature choice.

This is not a strategy. `PROMISING` is not promotion, not `ROBUST`, and not
Demo-ready. `ROBUST` is unavailable until a later preregistered check opens the
locked span for one already-specified statistic. Exploratory cells cannot be
confirmed on this same discovery sample.

## Clock

`timestamp_interpretation_confirmed` is false on this archive. MetaQuotes'
`copy_ticks_range` page says obtained tick times are UTC. The project's live
tick path says server-local time and a measured offset. Those statements are
not reconciled here. Hour, session, and weekday stay blocked. Raw millisecond
gaps do not need a timezone and may be used.

Flags are not a feature. The official flag names do not include a numeric value
on the constants page, and the observed values include a bit that those names
do not define. Quote changes are measured from bid and ask.

## State

A quote change is the change from the previous ledger row to the current row,
in 0.01 price units. The nine states are the signs of the bid change and the
ask change. Unchanged, one-sided, widen (bid down and ask up), and tighten
(bid up and ask down) are that partition, not a searched taxonomy.

The next quote is the next ledger row. A result that uses a later row is
excluded if any used stamp is at or after the cutoff. Rows are not repaired.
Non-positive bid or ask, and a negative spread, are excluded from the event
and counted.

Inferential events are those whose global row index is divisible by `horizon + 1`.
Their windows do not share a quote. Adjacent p-values are not evidence.

Discovery time is split into three equal raw-span terciles. A relationship is
not `PROMISING` unless every tercile with at least 1,000 inferential events
agrees in sign with the prediction. A tercile below 1,000 events makes the
hypothesis `INCONCLUSIVE` if the overall sample would otherwise pass.

## Confirmatory family

Holm-Bonferroni across these seven, one-sided in the predicted direction.
Adjusted p must be below 0.01. With this sample size the effect floor is the
binding gate. Nothing here is fit to the previous H-MS-01 or H-MS-02 results.
Those remain rejected. The reversed H-MS-02 comparison is not retested.

| ID | Prediction | Floor | Artifact gate |
| --- | --- | --- | --- |
| H-QD-01 | Two-sided same-direction updates continue more than one-sided updates, at the next quote | rate difference ≥ 0.02 | one-quote delay does not flip the difference; both the one-sided fade and the two-sided follow have positive mean residual after one spread |
| H-QD-02 | Next-quote sign dependence of all non-zero mid changes differs from independence | absolute difference ≥ 0.02 | trade the excess side; one-quote delay does not remove the excess; that trade's mean residual after one spread is positive |
| H-INT-01 | A gap of at most 100 ms raises the probability that the next positive gap is also that short | lift ≥ 0.05 | 50 ms and 200 ms lifts are positive. Process structure, not a trade |
| H-SP-01 | Spread in cents stays put more often than the independence benchmark | difference ≥ 0.05 | none beyond terciles. Process structure, not a trade |
| H-MV-01 | After bid-up with ask unchanged, the next 1-cent mid move within 64 quotes is up more than half the time | absolute deviation ≥ 0.02, and the bid-down mirror agrees | search starts one quote later under delay; delayed sign agrees; predicted-direction residual after one spread is positive; resolved fraction at least 0.50 |
| H-VOL-01 | Absolute mid change over 16 quotes is larger after a gap of at most 100 ms than after a gap of at least 1,000 ms | ratio ≥ 1.25 | 50 ms versus 2,000 ms ratio > 1; not a directional trade |
| H-SPR-01 | Absolute mid change over 16 quotes is larger after a widen than after a tighten | ratio ≥ 1.10 | the same ratio on the window that starts one quote later is ≥ 1.10; otherwise it is a construction artifact and is rejected |

`PROMISING` requires the floor, Holm, tercile agreement, the artifact gate, and,
for H-QD-01, H-QD-02, and H-MV-01, a positive one-spread residual. H-INT-01 and
H-SP-01 are not labeled `PROMISING` even if real: they do not by themselves
change a tradable return. A directional result that is stable but loses one
spread is `TESTED`, with that reason, not `PROMISING` and not an edge.

Same-millisecond and non-positive gaps are excluded from H-INT-01 and counted.
If any backward `time_msc` step is found, order-dependent hypotheses are
`INCONCLUSIVE`.

## Descriptive panel

Measured on the discovery window only. Not confirmatory. Not a place to choose
a threshold.

- Nine-by-nine state transition counts, on the non-overlapping pairs, and the
  mutual information of that table.
- Run-length histogram of mid-change sign, capped at 32.
- Run-length histogram of gaps at most 100 ms.
- Inter-arrival histogram in raw milliseconds. No weekend label.
- Spread-cent occupancy, and mean absolute mid change at 1 and 16 quotes by
  spread cent. This curve is not a new test of H-MS-02.
- Quote-change magnitude and the share of mid changes that are half a cent.
- Conditional signed and absolute moves at horizons 1, 4, 16, and 64 by state.

No model is fit. No order is submitted.
