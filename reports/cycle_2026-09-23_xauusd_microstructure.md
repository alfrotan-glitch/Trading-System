# XAUUSD microstructure research state — 2026-09-23

Decision: INCONCLUSIVE

No strategy was promoted. Nothing is robust, validated, or Demo-ready. The held-out span was not opened. These measurements narrow the short-horizon quote process. They do not show that the archive has no edge.

Measurement: `reports/xauusd_microstructure_state.json`, Actions run `35837520722`, code `de9cb1f89bb054c89604f2f4d962846218b9a002`. Zip SHA-256 matched `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723` before extraction. Row count 139,930,971 and cutoff `1764563969254` match the verified inventory. Non-monotonic steps: 0. Invalid prices: 0. Negative spreads: 0. No row was repaired.

Discovery rows: 70,834,426. Locked-span rows were counted only so they could be excluded. Definitions were locked in `docs/xauusd_microstructure_preregistration.md` before the run. With this sample size, a tiny p-value is not a finding. The pre-declared effect floors are the gates.

## Clock

Still blocked. MetaQuotes' current `copy_ticks_range` page says obtained tick times are UTC. The project's live-tick path says WM Markets stamps are server-local and must be shifted by a measured offset. This archive's manifest keeps `timestamp_interpretation_confirmed` false. Those statements were not reconciled, so hour, session, and weekday were not unlocked. Raw millisecond gaps do not need a timezone and were used. Gaps of an hour or more were not labeled weekends.

Trade prints remain blocked. `last` and `volume` are zero. Flags were not used: the observed values include a bit the official flag names do not define.

## Level 1 — what the quote process is

These are descriptions of the discovery window, not tests.

The stream is mostly a two-sided quote update, not a one-tick bounce.

- 78.8% of quote changes move bid and ask in the same direction.
- 17.9% move only one side.
- 3.3% widen or tighten the spread.
- 10 changes leave both sides unchanged.
- 66.3% of mid changes are larger than one cent. 23.9% are exactly one cent. 9.1% are exactly half a cent. A half-cent move is what a one-cent, one-sided update does to the mid. That pattern is a minority.
- Of bid changes, 27.4% are exactly one cent. 3.0% are 20 cents or more.

The next quote-event type is only weakly predictable. On non-overlapping pairs, the next-state entropy is 2.054 bits and the mutual information is 0.130 bits, about 6.3% of that entropy. After a two-sided down move, 41.3% of the next events are again two-sided down and 45.9% are two-sided up. After a two-sided up move, 41.7% continue and 45.4% flip. The mass alternates a little more than it continues. It is not a trend and not a clean reversal machine.

Mid-sign runs are short and close to geometric. Of 37,227,380 runs, 53.4% last one quote, 24.4% last two, and 11.5% last three. A memoryless stop rate of 0.534 predicts those frequencies within about one percentage point through length 5. There is a small excess of longer runs. That excess was not a pre-registered test and is not an edge.

Arrival times, in raw milliseconds, are concentrated. Of positive gaps, 35.0% fall in 100–200 ms, 19.5% in 50–100 ms, and 23.5% in 200–500 ms. Same-millisecond gaps are 2.5% of discovery changes. Sixty-five gaps last at least 24 hours. They stay unclassified. Short gaps are isolated: 80.2% of runs of gaps at most 100 ms last exactly one step. Runs of four or more are 0.3%.

The spread is sticky. On the inferential sample, 56.6% of steps keep the same spread in cents. An independent draw from the spread distribution would stay only 10.4% of the time. That is real structure in the quote process. It is not a prediction of return.

The common spread is 22 cents (25.5% of the inferential h=1 sample). The mean absolute next mid change there is 0.048, about 22% of that spread. Across the common spread bins, the next quote's absolute move is a fraction of the spread, not a multiple of it. This curve is exploratory. It was not used to choose a new threshold, and it does not reopen the rejected median-split test.

## Level 2 — pre-registered predictions

| ID | Result | What was measured |
| --- | --- | --- |
| H-QD-01 | REJECTED | Two-sided continuation 0.479, one-sided 0.472. Difference 0.006, below 0.02. Following the two-sided move loses 0.80 bps after one spread. Fading the one-sided move loses 0.91 bps. |
| H-QD-02 | REJECTED | Next-quote continuation 0.477 versus an independence benchmark of 0.497. The reversal tilt is 1.95 percentage points, below the 0.02 floor. Both the follow and the fade lose about 0.82 bps after one spread. |
| H-INT-01 | REJECTED | After a gap of at most 100 ms, the next gap is that short 18.7% of the time, against a 24.1% base rate. The lift is −0.054, not positive clustering. The 50 ms sensitivity is also negative. |
| H-SP-01 | TESTED | Spread persistence exceeds independence by 0.46. Process structure only. Not a return predictor and not a strategy. |
| H-MV-01 | REJECTED | After a bid-up with the ask unchanged, the next 1-cent mid move is up 49.8% of the time. The bid-down mirror is down 48.1%. Almost every signal resolves inside 64 quotes (49,588 resolved, 1 censored). The predicted-direction residual is −0.85 bps. |
| H-VOL-01 | REJECTED | Mean absolute 16-quote move is 0.221 after a gap of at most 100 ms and 0.194 after a gap of at least 1 second. Ratio 1.14, below 1.25. |
| H-SPR-01 | REJECTED | After a widen, the 16-quote absolute move averages 0.200. After a tighten, 0.207. The predicted widen-larger ratio is 0.97. The delayed window agrees. |

The exploratory horizon panel says the same thing at 4, 16, and 64 quotes. For the two dominant states, continuation stays between 0.46 and 0.50. The mean signed move in the state's direction is under one cent even at 64 quotes. The mean absolute move grows from about 0.046 at one quote to about 0.21 at 16 quotes and about 0.44 at 64 quotes. The movement is real. The conditional direction is not. A signed drift of a few tenths of a cent does not survive a spread of about 22 cents. No cell in that panel was promoted. The largest signed cell is still far below one spread, and choosing it after seeing the table would be snooping.

## What this narrows

Failed tests remove mechanisms. They do not empty the archive.

Removed, at the pre-declared definitions and floors:

- The next quote is not a material continuation or reversal bet after a one-sided update, a two-sided update, or a generic non-zero mid change.
- A one-sided bid update does not predict the next 1-cent move.
- Short gaps do not cluster at 100 ms. They are mostly isolated.
- A spread widen does not forecast a larger 16-quote move than a tighten.
- Busy quotes have only a modestly larger 16-quote absolute move than quiet quotes, below the declared floor.
- Quote direction runs are nearly memoryless beyond one step.

Still true, and useful:

- The book usually updates both sides together, by more than one tick.
- The spread you see is usually still there on the next quote.
- The next event type carries about 0.13 bits of information about the following event type.
- Absolute movement over 16–64 quotes is on the order of one or two spreads. Directional conditioning on the current quote state does not capture it.

## What was not tested

No regime label was built. No interaction beyond the locked family was confirmed. No horizon beyond 64 quotes was measured. No model was fit. The held-out span was not used, because nothing was `PROMISING`. A later phase may preregister a new object. It may not retune these thresholds on this same discovery sample, and it may not treat the 200 ms intensity lift or the small reversal tilt as already confirmed.

## Validation, execution, engineering

Validation: no candidate. The locked span remains locked.

Execution: the cost model was one spread at the signal quote, with a one-quote delay as a stress. Those stresses were not broker fills. `DEMO_EXECUTION` was not enabled. `confirm_live` was not changed. Orders submitted: 0. Demo readiness: NOT ESTABLISHED. Live remains locked.

Engineering: the scan is `src/qts/research/xauusd_microstructure.py`. Local pytest: 9 passed in `tests/test_xauusd_microstructure.py`. Ruff passed on the new files. The full suite was not run. No gate was weakened. `uuid7()` was not edited.

## Decision

INCONCLUSIVE

The short-horizon directional quote-state family was measured and rejected. Spread persistence is real and is not an edge. The rest of the search has not been run. No executable mechanism has been established.
