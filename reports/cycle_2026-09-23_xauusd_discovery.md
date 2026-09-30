# XAUUSD research state — 2026-09-23

Decision: INCONCLUSIVE

No strategy was promoted. Neither tested hypothesis is a candidate. Nothing is validated, and nothing is Demo-ready.

The measurement is `reports/xauusd_discovery_state.json`, written by Actions run `35834431066` from code `97188642d87fec225d92d31a67128902561f455c`. This sandbox did not re-read the zip. The runner matched zip SHA-256 `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723` before extraction. Rows were not repaired.

## Data

Dataset: release `dataset-xauusd-730d-20260919`, asset `XAUUSD_730d_20260919T114013Z.zip`. Manifest dataset digest `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`. Manifest symbol `XAUUSD@`. Runner host `github-actions-runner`. Orders submitted: 0.

### DATA FACTS

These are counts and ranges. They are not predictions.

- 139,930,971 rows. Raw `time_msc` runs from 1726746013452 to 1789775939790. That matches the earlier inventory.
- `time` equals `time_msc // 1000` on every row. The two fields are the same clock truncated to seconds. That does not establish UTC.
- 137,378 rows are whole seconds. 14,008,189 are divisible by 10, and 1,400,381 by 100. Those fractions are about 0.001, 0.10, and 0.01. The millisecond field varies. It is not a second-rounded clock.
- Timezone, session, and calendar remain `UNAVAILABLE`. The manifest describes an MT5 convention and sets `timestamp_interpretation_confirmed` to false. No offset was applied.
- Every bid is on a 0.01 grid, and every bid is also on a 0.001 grid because of that. The minimum positive adjacent bid change stored is 0.009999999999308784. The observed price grid is one cent. This is not a separate exchange-specification document.
- Of 66,359,323 positive bid changes, 17,956,294 are exactly one cent. Other changes are larger. The grid step is one cent; the typical change is not.
- `volume` / `volume_real` is zero on every row. `last` is zero on every row. This archive has no trade print, trade size, or aggressor side. Those studies cannot be run on it.
- Adjacent quote pairs: 139,930,970. Both bid and ask changed on 123,767,511. Bid only: 8,153,716. Ask only: 8,005,622. Neither: 4,121. Almost every row is a quote update.
- Flag values, uninterpreted: 4 (7,963,568), 130 (8,157,814), 134 (123,809,589). No flag dictionary was confirmed, so flags were not used as a feature.
- Equal raw-span bins, descriptive only. Bins 3 and 4 overlap the locked span and were not used to fit a test. Mean spread in price: 0.244, 0.262, 0.280, 0.305, 0.251. Row counts: 23,682,649; 22,345,383; 24,806,394; 36,299,244; 32,797,301. The spread level is not constant. That observation did not select a hypothesis.
- Discovery cutoff, integer 60 percent of the raw span: `time_msc < 1764563969254`. Discovery rows: 70,834,426. Locked-span rows: 69,096,545. The split is on time, not on row count. The two counts sum to the archive.
- Inverted quotes in the H-MS-01 event sample: 0. No inverted row was dropped, because none was present.

### RESEARCH ASSUMPTIONS

- The next quote is the next ledger row, not the next distinct timestamp.
- The prevailing spread is the spread on the quote before the move.
- One spread cost is the spread at the event quote, subtracted in price.
- A triple is excluded when any of its three stamps is at or after the cutoff. It is not repaired.
- The inferential sample is discovery events whose global center row is divisible by 3. Those events do not share a quote.
- An iid binomial p-value on adjacent events is not evidence.

### DERIVED FEATURES

Mid, spread, next mid change, and absolute next mid change divided by spread. No other feature was built. No model was fit.

## Discovery

### H-MS-01 — REJECTED

Prediction: after a mid move larger than the previous spread, the next mid change reverses more than half the time, and the fade still has a positive mean after paying one spread.

Discovery events: 921,674. Directional next moves: 916,788. Reversals: 458,004. Continuations: 458,784. Flat next: 4,886. Overlapping reversal frequency: 0.49957. That p-value against one half is 0.42 and is not inferential.

Non-overlapping events: 306,526. Directional: 304,951. Reversal frequency: 0.49941. Binomial p-value against one half: 0.51. Mean residual: -0.803 bps. Seeded bootstrap interval on a 100,000 draw, with the mean taken from the full non-overlapping count: -0.806 to -0.799. The interval is entirely below zero. Positive residual frequency: 0.0223.

The same non-overlapping sample, keeping only gaps of at most 1 second, has mean residual -0.804 bps. Dropping longer gaps does not change the sign. A one-quote delay, which is a stress and not a separate hypothesis, has mean residual -0.801 bps on 921,673 events. Inverted events: 0.

The frequency is not above one half. The residual after one spread is negative. The hypothesis is rejected. It is not a statistical edge, not an economic edge, and not an executable edge.

### H-MS-02 — REJECTED

Prediction: quotes with spread above the discovery-window median have a larger mean absolute next mid change, measured in spread units, than quotes below the median. Ties at the median are in neither half.

Median spread: 0.23999999999978172 price units, from the full discovery-window store. The store was not truncated. Wide: 34,999,170. Narrow: 31,146,764. Ties excluded: 4,688,491. Wide mean scaled move: 0.1492. Narrow: 0.1939. Difference, wide minus narrow: -0.0447.

Non-overlapping: wide 11,666,103, narrow 10,383,923. Difference: -0.0448. The wide half is smaller, not larger. The preregistered direction fails. This is a mechanism check, not a strategy. The reversed comparison was not preregistered and was not promoted. Both halves move by much less than one spread on the next quote.

### H-TOD-01 — NOT TESTED

Blocked. The timestamp basis is not confirmed. Hour, session, and weekday tests were not run.

### Not tested

Regimes, event sequences other than these two, and cross-feature conditionals. No machine-learning model. The edge discovery map is `docs/xauusd_edge_discovery_map.md`. Trade-print studies are blocked by the volume and last fields, not by the clock.

## Validation

No candidate reached validation. The locked span was not used to estimate either hypothesis. A profitable backtest was not produced, and none would have been a validation pass.

## Execution

Assumed cost for H-MS-01 was one spread at the event quote, with the next ledger row treated as the exit observation. That is not a broker fill. The one-quote delay stress did not change the sign. `DEMO_EXECUTION` was not enabled. `confirm_live` was not changed. Execution mode in `configs/dev.yaml` remains `backtest`. No order was submitted. Demo readiness: NOT ESTABLISHED. Live remains locked.

## Engineering

Added `src/qts/research/xauusd_tick_discovery.py`, `scripts/run_xauusd_discovery.py`, and the runner workflow. Local pytest: 6 passed in `tests/test_xauusd_tick_discovery.py`. Ruff passed on those files. The full suite was not run. The runner job succeeded and committed the measurement. No gate was weakened. `uuid7()` was not edited. The canonical zip was not rewritten.

## Decision

INCONCLUSIVE

Two preregistered hypotheses are rejected. The rest of the search has not been run. Clock-based and trade-print studies are blocked by the archive, not by a missing download. No edge has been established.
