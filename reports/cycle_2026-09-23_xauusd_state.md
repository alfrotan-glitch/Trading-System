# XAUUSD state-conditional research state — 2026-09-23

Decision: INCONCLUSIVE

No strategy was promoted. Nothing is robust, validated, or Demo-ready. The held-out span was not opened. A magnitude effect was measured. It is not a directional trade, and it is not evidence that the archive has no edge.

## Data

Measurement: `reports/xauusd_state_scan.json`, Actions run `35844031516`, code `bf7482ce71fd0aa5a87bb870c93afc7bf8b83f6a`, measurement commit `016bfb0`. Zip SHA-256 matched `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723` before extraction. Manifest dataset digest `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`. Row count 139,930,971 and cutoff `1764563969254` match the verified inventory. Identity check passed.

Discovery rows: 70,834,426. Locked-span rows: 69,096,545, counted only so a window that touches them could be excluded. No locked-span distribution was computed. Non-monotonic steps: 0. Negative spreads: 0. No row was repaired. Histogram overflow at ±$200 was 0, so the reported quantiles are not censored.

Definitions were locked in `docs/xauusd_state_preregistration.md` before the run. Inferential events are global rows divisible by `horizon + 1`. With this sample size, a tiny p-value is not a finding. The pre-declared floors are the gates.

Clock: still blocked. The manifest keeps `timestamp_interpretation_confirmed` false. Hour, session, and weekday were not used. Raw millisecond gaps were used only as intensity. Trade prints remain blocked: `last` and `volume` are zero.

## Discovery

The question was whether an observable quote state changes the distribution of later movement. Direction and magnitude were measured separately. The unconditional discovery distribution is the reference.

| Horizon | n | Mean signed | Mean absolute | Median | P(up) | P(move > spread) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 14,166,884 | +0.01 cent | $0.097 | 0 | 0.476 | 0.071 |
| 16 | 4,166,729 | +0.04 cent | $0.210 | 0 | 0.494 | 0.273 |
| 64 | 1,089,759 | +0.17 cent | $0.433 | 0.5 cent | 0.501 | 0.559 |
| 256 | 275,619 | +0.59 cent | $0.873 | 1.5 cents | 0.505 | 0.770 |
| 1024 | 69,105 | +2.4 cents | $1.739 | 5 cents | 0.510 | 0.884 |
| 4096 | 17,288 | +9.6 cents | $3.475 | 14.5 cents | 0.517 | 0.940 |

Mean spread in that sample is 26.2 cents. At the primary horizon, the mean absolute move is about 3.3 spreads and the mean signed move is 2.3% of one spread. The 10th and 90th percentiles at 256 quotes are −$1.345 and +$1.355. The distribution is wide and nearly symmetric. Absolute movement is real. Direction is not a trade.

### Confirmatory family

Holm-Bonferroni was applied across the four locked tests. Floors bound the result. No status is `PROMISING` or `ROBUST`.

| ID | Result | What was measured |
| --- | --- | --- |
| H-ST-01 | REJECTED | Wide and active, 256-quote mean absolute move $1.192 (n 21,485). Wide and quiet, $0.996 (n 15,507). Ratio 1.197, below 1.25. Exceed-spread lift 3.8 percentage points, below 5. Delay ratio 1.20. Horizon 1024 ratio 1.17. The sign is the predicted one. The floor is missed. Holm p about 10⁻⁵⁷ does not override the floor. |
| H-ST-02 | TESTED | After a 16-quote absolute move of at least $0.20, the next 256-quote mean absolute move is $1.073 (n 103,498). After a move of at most $0.10, it is $0.727 (n 109,532). Ratio 1.476. Exceed-spread lift 7.0 percentage points. Delay ratio 1.474. Horizon 1024 ratio 1.42. All three discovery terciles have ratio at least 1.25. |
| H-ST-03 | REJECTED | After a non-zero mid-sign run of length at least 5, the 256-quote move fades 49.4% of the time (n 15,718). The predicted floor was 52%. The fade residual after one spread plus one cent is −0.91 bps. Up-runs fade 48.3%. Down-runs fade 50.5%. Both residuals are negative. Delay fade rate 49.3%. Horizon 1024 fade rate is 50.7% (n 3,865), still far below 52%, and it does not agree with the primary sign. |
| H-ST-04 | REJECTED | Leaving a spread that has lasted at least four quotes, mean absolute move $0.925 (n 7,682). Staying, $0.865 (n 113,946). Ratio 1.069, below 1.15. Exceed-spread lift 0.1 percentage point. Horizon 1024 ratio 1.05. Tercile 0 is 1.07. The pooled floor fails. |

H-ST-02 is process structure. In the high-vol cell the mean signed move is +0.8 cents against a 27.6-cent spread, and P(up) is 0.506. The absolute move is larger even after scaling by the cell spread: 3.89 spreads versus 2.88 in the low-vol cell. That is volatility clustering in the quote stream, not a direction. Two of the three tercile exceed-spread lifts are 3.6 and 4.3 percentage points. The locked gate was the pooled lift, which cleared. The terciles are not equally strong. This was not a retest of the rejected 16-quote gap contrast.

The 38-cent occupancy mode is still descriptive. At 256 quotes its mean absolute move is $1.368 against a 38.7-cent spread, 3.53 spreads, versus 3.33 unconditionally. Its exceed-spread probability is 0.778 versus 0.770. The dollar move is larger mostly because the spread is wider. That cell was not given a confirmatory test.

### Hypothesis generators

Thirty-three panel cells cleared a pre-declared ranking score. Every one is `NOT TESTED`. None can be confirmed on this discovery sample.

The top of that list is not a state-conditional edge. At 4096 quotes the unconditional mean signed move is already +9.6 cents, 36% of the mean spread, and P(up) is 0.517. Horizon 4096 was declared descriptive. Cells such as quiet, typical, tight, and persistent spreads clear the signed-score floor because they carry that same drift. The largest listed cell, wide and quiet at 4096 quotes, is +30.7 cents (n 1,007). The same state at 256 quotes is −1.1 cents. Active-to-quiet is −2.1 cents at 256 quotes and +13.1 cents at 1024. A sign that flips with the horizon is not a hypothesis.

No new directional hypothesis is registered from this panel. The only mechanism this sample supports is the one already tested: recent absolute movement clusters, and the cluster is not a sign prediction.

## Validation

No candidate. H-ST-02 is `TESTED`, not `PROMISING`. The preregistration keeps the held-out span closed unless a directional gate passes. None did. The locked span was not used to choose a feature, a threshold, a horizon, or a state.

## Execution

The cost stress on the directional test was one spread plus one cent, with a one-quote delay. The magnitude tests used a one-quote-delayed absolute move. Those are not broker fills. Nothing cleared a directional cost model. `DEMO_EXECUTION` was not enabled. `confirm_live` was not changed. Orders submitted: 0. Demo readiness: NOT ESTABLISHED. Live remains locked.

## Engineering

The scan is `src/qts/research/xauusd_state_scan.py`, run by `scripts/run_xauusd_state_scan.py` under `.github/workflows/canonical-xauusd-state.yml`. Discovery and microstructure modules were not edited. `uuid7()` was not edited. No gate was weakened.

Local pytest: 16 passed in `tests/test_xauusd_state_scan.py`. Ruff passed on the new files. The full suite was not run.

## Decision

INCONCLUSIVE

State changes the size of later movement. Recent volatility is the measured form of that, and it is not a trade. State does not change the sign enough to pay the spread. The long-horizon signed list is a common drift plus unstable cells, not a set of discoveries. No executable mechanism has been established.
