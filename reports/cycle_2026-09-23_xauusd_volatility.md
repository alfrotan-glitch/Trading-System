# XAUUSD volatility-state research state — 2026-09-23

Decision: INCONCLUSIVE

No strategy was promoted. Nothing is robust, validated, or Demo-ready. The held-out span was not opened. The known absolute-move clustering survived a harsher cost on the discovery sample. That is not a directional trade, and it is not evidence that the archive has no edge.

## Data

Measurement: `reports/xauusd_volatility_state.json`, Actions run `35850795793`, code `a22f9dc50c9fe60afc4d01d5ea0cbf59f105d762`, measurement commit `308b432`. Zip SHA-256 matched `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723` before extraction. Manifest dataset digest `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`. Row count 139,930,971 and cutoff `1764563969254` match the verified inventory. Identity check passed.

Discovery rows: 70,834,426. Locked-span rows: 69,096,545, counted only so a window that touches them could be excluded. No locked-span distribution was computed. Non-monotonic steps: 0. Negative spreads: 0. No row was repaired. Histogram overflow at ±$200 was 0.

Definitions were locked in `docs/xauusd_volatility_preregistration.md` before the run. Inferential events are global rows divisible by `horizon + 1`. Floors bind. A tiny p-value is not a finding.

Clock: still blocked. Hour, session, and weekday were not used. Trade prints remain blocked.

## Hypotheses

H-ST-02 was not reopened. This scan reproduced it. After a 16-quote absolute move of at least $0.20, the 256-quote mean absolute move is $1.0729275928037256 (n 103,498). After a move of at most $0.10, it is $0.7268080560931959 (n 109,532). Ratio 1.476. Those are the same counts and the same means as the state panel. The 16-quote high-versus-low means already in that panel were not treated as a new test. Spread plus one cent was already visible there and is not a new confirmatory result.

Holm-Bonferroni was applied across the four locked tests. No status is `PROMISING` or `ROBUST`. A pass is not a strategy.

| ID | Result | What was measured |
| --- | --- | --- |
| H-VL-01 | TESTED | The same high-versus-low contrast clears spread plus two cents. High-cell probability 0.7950. Low-cell probability 0.7196. Lift 0.0754, above 0.05. One-quote-delayed lift 0.0756, above 0.02. Median quotes to clear spread plus one cent: 17 after high, 29 after low, ratio 0.586. The delayed medians are the same. Dollar gap $0.346, above $0.22. Horizon 1024 agrees. |
| H-VL-02 | TESTED | Extreme, a recent move of at least $0.40, has a 256-quote mean absolute move of $1.287 (n 38,979). High but not extreme, $0.943 (n 64,519). Ratio 1.364, above 1.15. Dollar gap $0.344, above $0.10. Delay ratio 1.362. Horizon 1024 agrees. The tail continues. It does not saturate at the ordinary high cut. |
| H-VL-03 | TESTED | Quiet-to-expansion, $0.887 (n 29,318). Stay-quiet, $0.664 (n 80,073). Ratio 1.335, above 1.25. Dollar gap $0.2226, above the $0.22 floor by $0.0026. Delay ratio 1.333. Horizon 1024 agrees. The floor is cleared. The dollar surplus is two-tenths of a cent. |
| H-VL-04 | TESTED | Persistent high, $1.389 (n 19,038). Contraction onset, $0.960 (n 62,175). Ratio 1.447, above 1.15. Dollar gap $0.429, above $0.10. Delay ratio 1.446. Horizon 1024 agrees. A high state that is still high has a larger later move than the onset of contraction. That is persistence, not an exhaustion trade. |

Both the high and the low state clear spread plus two cents most of the time. The new fact is a 7.5 percentage-point lift and a shorter wait, not a rare event that only the high state reaches. The lift is charged against each cell's own spread, so it is not just the high cell's wider spread. High-cell mean spread is 27.6 cents. Low-cell mean spread is 25.2 cents. The absolute move is 3.89 spreads after high and 2.88 spreads after low.

Direction is still not a signal. In the high cell the mean signed move is +0.8 cents and P(up) is 0.506. Extreme is +0.4 cents, P(up) 0.504. Quiet-to-expansion is −0.06 cents, P(up) 0.504. Persistent high is −1.9 cents against a 30.0-cent spread, P(up) 0.501. None of these is a side.

The probability that the next 16-quote window is larger than the current one falls from 0.75 in the low bin to 0.13 in the extreme bin. That comparison is partly mechanical: a very small window is easier to exceed than a very large one. It was not a confirmatory test and it is not an exhaustion strategy.

## Validation

No candidate was sent forward. The four passes are `TESTED` on the discovery sample. The preregistration keeps the held-out span closed even if a gate passes. It stayed closed. It was not used to choose a feature, a threshold, a horizon, or a state.

Eighteen panel cells cleared a pre-declared ranking score. Every one is `NOT TESTED`. The 4096-quote signed scores are the same class of descriptive drift already seen in the state panel. Several flip or shrink at 256 quotes. They are not registered as directional hypotheses. They cannot be confirmed on this sample.

## Execution

The new cost was spread plus two cents. Waiting time used spread plus one cent, censored at 4,096 quotes or at the locked span. In these cells every event resolved, so the cap did not bind. Delay entered at the next quote and charged that quote's spread. These are not broker fills.

There is no volatility instrument in this archive. A larger absolute move does not name a buy or a sell. Conditioning these states on a directional signal would require that signal to be supported separately. It is not. No order can be constructed from this result.

`DEMO_EXECUTION` was not enabled. `confirm_live` was not changed. Orders submitted: 0. Demo readiness: NOT ESTABLISHED. Live remains locked.

## Engineering

The scan is `src/qts/research/xauusd_volatility.py`, run by `scripts/run_xauusd_volatility.py` under `.github/workflows/canonical-xauusd-volatility.yml`. The state-scan module, script, and workflow were not edited. `uuid7()` was not edited. No gate was weakened. The runner did not repair rows and did not replace the archive.

Local pytest: 17 passed in `tests/test_xauusd_volatility.py`. Ruff passed on the new files. The full suite was not run.

## Decision

INCONCLUSIVE

The magnitude difference survives spread plus two cents and arrives sooner. Extreme continues past ordinary high volatility. A quiet-to-expansion onset is larger than staying quiet, with almost no dollar surplus over the floor. Persistent high is larger than contraction onset. None of that is a trade. No executable mechanism has been established. The held-out span stays closed. No model is fit.
