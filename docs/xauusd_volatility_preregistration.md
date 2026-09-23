# XAUUSD volatility-state preregistration

Registered before this measurement. Discovery is `time_msc < min + (span * 60) // 100`.
The locked span is not read for a statistic, a threshold, or a state definition.

H-ST-02 remains `TESTED` process structure: a recent 16-quote absolute move of at least
$0.20 was followed by a larger 256-quote absolute move than a move of at most $0.10.
That contrast is not reopened. The 16-quote high-versus-low means already visible in
the state panel are not a new test. No directional signal is registered. Nothing in
this phase can be `PROMISING` or `ROBUST`. A pass is not a strategy. The held-out
span stays closed even if a gate passes.

## Why these questions

The known structure is volatility clustering, not a sign. The open question is
whether that clustering is economically usable, and whether two mechanism-backed
splits add anything the coarse high-versus-low contrast did not already say.

Thresholds are the prior scale, not a search of future returns. Low is at most
$0.10. Normal is above $0.10 and below $0.20. High is at least $0.20. Extreme is
at least $0.40, twice the locked high threshold. The middle of high, $0.20 up to
$0.40, is the adjacent bin.

A quiet-to-expansion onset is a 4-quote absolute move of at least $0.10 after the
16-quote window ending four quotes earlier was at most $0.10. Stay-quiet is that
same prior window with a 4-quote move below $0.10. The groups are disjoint: the
$0.10 boundary is a burst, so it belongs to the onset. Contraction onset is a
4-quote move of at most $0.10 after that prior window was at least $0.20.
Persistent high is both of those windows at least $0.20. Those two groups do not
overlap. Repeated bursts, two or more onsets in 64 quotes, are descriptive only.

## Locked measurement

Horizons are 16, 64, 256, 1024, and 4096 quotes. Sixteen is included because the
state is a 16-quote window. No other horizon is added. Inferential events are
global rows divisible by `horizon + 1`. A window that touches the locked span is
excluded. Rows are not repaired.

Primary horizon: 256. Horizon 1024 must agree in the sign of the absolute-move
ratio when both sides have at least 1,000 events. Underpowered is noted and is
not a failure. It is not a second economic test. Horizons 16, 64, and 4096 are
descriptive for the confirmatory family. A delay sample below 1,000 is
`INCONCLUSIVE`. P-values are one-sided in the predicted direction. Holm uses
those four p-values. The waiting-time median is among events that clear the
cost before 4,096 quotes or the locked span. Both the immediate and delayed
medians are gated. A side with fewer than half of its events resolved cannot
support a positive time gate. Waiting time to spread plus two cents is
descriptive only.

Discovery time is three equal raw-span terciles of the discovery cutoff span. A
tercile below 1,000 blocks a positive status. Each tercile must agree in sign.
One-quote delay starts the window at the next quote. Slippage of one cent was already visible in the prior panel
and is not a new confirmatory result. The new cost is two cents. Degraded
execution is spread plus $0.02.

Waiting time is the event count until the absolute move exceeds the spread plus
one cent, censored at 4,096 quotes or at the locked span. A side with fewer than
half of its events resolved cannot support a positive time gate.

Direction, tail asymmetry, transition counts, and run length are reported. They
are not hypotheses. A cell is not a directional signal. There is no volatility
instrument in this archive.

## Confirmatory family

Holm-Bonferroni across these four. Adjusted p below 0.01 is required for a
positive status. The floor is the binding gate. Positive status is `TESTED`
only. It is not a trade.

| ID | Prediction | Floor | Positive status |
| --- | --- | --- | --- |
| H-VL-01 | The known high-versus-low contrast still clears spread plus two cents, and the high state reaches spread plus one cent sooner | degraded exceed-probability lift ≥ 0.05; delayed lift ≥ 0.02; median waiting-time ratio ≤ 0.80; the scan must also reproduce absolute-move ratio ≥ 1.25 and a dollar gap ≥ $0.22 | `TESTED` cost-qualified magnitude. Not a strategy. Failure to reproduce H-ST-02 is `INCONCLUSIVE`, not a new rejection of that result. |
| H-VL-02 | Extreme recent movement has a larger 256-quote absolute move than high-but-not-extreme | ratio ≥ 1.15, dollar gap ≥ $0.10, delay ratio ≥ 1.10 | `TESTED` tail continuation, or saturation if the floor fails. Not a strategy. |
| H-VL-03 | Quiet-to-expansion has a larger 256-quote absolute move than staying quiet | ratio ≥ 1.25, dollar gap ≥ $0.22, delay ratio ≥ 1.10 | `TESTED` transition structure. Not a strategy. |
| H-VL-04 | Persistent high volatility has a larger 256-quote absolute move than contraction onset | ratio ≥ 1.15, dollar gap ≥ $0.10, delay ratio ≥ 1.10 | `TESTED` persistence-versus-exhaustion. Not a strategy. |

A wrong sign or a missed floor is `REJECTED`. Fewer than 1,000 events, or a
backward timestamp, is `INCONCLUSIVE`. Panel cells that clear the old ranking
scores of 0.25, 1.25, or 0.05 are `NOT TESTED` generators. They cannot be
confirmed on this discovery sample.

No model is fit. No order is submitted. Session labels stay blocked.
