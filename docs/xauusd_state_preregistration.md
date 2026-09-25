# XAUUSD state-conditional preregistration

Registered before the measurement. Discovery is `time_msc < min + (span * 60) // 100`.
The locked span is not read for a statistic, a threshold, or a state definition.

This phase does not construct a strategy. `PROMISING` is not promotion and not
`ROBUST`. The held-out span stays closed even if a discovery gate passes.

## Why these states

Prior discovery measurements, not future returns, set the priorities.

- Spread persistence is real. A new question is whether leaving a sticky spread
  changes later magnitude. That is not the rejected widen-versus-tighten test.
- Absolute movement grows with horizon while signed drift stays near zero.
  Longer event horizons are for magnitude and asymmetry, not another next-quote
  sign test.
- The intensity effect at 16 quotes was below its floor. It is not retested.
  The new question is the interaction of a wide spread with activity.
- Run lengths are nearly geometric. The only directional test is the thin tail,
  run length at least 5, at 256 quotes. It does not reopen H-QD-02.
- One-tick bounce is a minority. States are not built on half-cent flips.
- No hidden-state model and no clustering. The quote variables are already
  discrete. An unconstrained model would spend the held-out sample on state
  selection.

## Locked definitions

Spread, from the occupancy distribution: tight is at most 20 cents, typical is
21–26, wide is at least 27. A second occupancy mode at 37–41 cents is
descriptive only.

Intensity, from the gap histogram: active is a positive gap of at most 100 ms,
normal is 100–500 ms, quiet is above 500 ms. Same-millisecond gaps are neither.

Recent magnitude uses the previously measured 16-quote absolute-move scale of
about 0.21. High is at least 0.20. Low is at most 0.10. The middle is unused.

A long run is a non-zero mid-sign run of length at least 5. A short run is
length 1 or 2.

Persistence is the current spread level lasting at least 4 quotes. Leave means
the previous quote was persistent and the spread changes. Stay means it was
persistent and the spread does not change.

Acceleration compares the last 16 quotes with the 16 before them. Equal
magnitudes are neither.

Horizons are 4, 16, 64, 256, 1024, and 4096 quotes. Inferential events are
those whose global row is divisible by `horizon + 1`. A triple or window that
touches the locked span is excluded. Rows are not repaired.

Primary inference horizon: 256. Horizon 1024 must agree in sign when both sides
have at least 1,000 inferential events. If it is underpowered, that is noted
and is not a failure. Horizon 4096 is descriptive.

Discovery time is three equal raw-span terciles. A tercile below 1,000 events
blocks a positive status. Slippage stress is one extra cent. One-quote delay
measures the window that starts at the next quote.

## Confirmatory family

Holm-Bonferroni across these four. Adjusted p below 0.01 is required for a
positive status. The effect floor is the binding gate.

| ID | Prediction | Floor | Positive status |
| --- | --- | --- | --- |
| H-ST-01 | Wide and active has a larger 256-quote absolute move than wide and quiet | ratio ≥ 1.25 and exceed-spread probability lift ≥ 0.05 | `TESTED` magnitude structure if the delay ratio stays ≥ 1.10. Not a directional trade. |
| H-ST-02 | High recent 16-quote absolute move predicts a larger 256-quote absolute move than low | same floors | same. Not a retest of the rejected gap test. |
| H-ST-03 | After a run of length ≥ 5, the next 256-quote move fades that run | sign rate at least 0.02 above one half, and the fade residual after one spread plus one cent is positive | `PROMISING` only if both run directions agree, delay agrees, and terciles agree. Still not a strategy. |
| H-ST-04 | Leaving a persistent spread has a larger 256-quote absolute move than staying in it | ratio ≥ 1.15 | `TESTED` magnitude structure if delay ratio ≥ 1.10. Not the rejected widen-versus-tighten test. |

A wrong sign or a missed floor is `REJECTED`. Fewer than 1,000 events, or a
backward timestamp, is `INCONCLUSIVE`. Nothing is `ROBUST`.

## Descriptive panel

The same horizons, for the marginal states and the interactions above, plus
the two occupancy modes, acceleration, and quiet-to-active transitions.
Summaries are n, mean signed move, mean absolute move, median, 10th and 90th
percentiles, probability of up and down, probability of exceeding the spread
and the spread plus one cent, and the average up move and down move.

Cells are ranked after measurement by three pre-declared scores: absolute
signed move divided by the cell's mean spread, absolute-move ratio versus the
unconditional mean, and exceed-spread probability minus the unconditional
probability. A cell is listed only if n is at least 1,000 and the score clears
0.25, 1.25, or 0.05 respectively. Listed cells are hypothesis generators.
They are `NOT TESTED`. They cannot be confirmed on this same discovery sample.

No model is fit. No order is submitted. Session labels stay blocked.
