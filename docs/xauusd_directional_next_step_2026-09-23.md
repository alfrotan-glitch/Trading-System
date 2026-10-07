# XAUUSD next-step decision and directional preregistration — 2026-09-23

**Decision recorded; H-DIR-01 preregistered, NOT RUN.** This document precedes any
implementation or new measurement. It is one discovery-only falsification test,
not a strategy or a validation plan. The last 40% of the raw `time_msc` span
remains closed, regardless of the result. No order, Demo execution, model fit, or
promotion is authorized.

## What is known, and the decision

Sources: [`docs/xauusd_volatility_preregistration.md`](xauusd_volatility_preregistration.md),
[`reports/cycle_2026-09-23_xauusd_volatility.md`](../reports/cycle_2026-09-23_xauusd_volatility.md),
[`reports/xauusd_volatility_summary.json`](../reports/xauusd_volatility_summary.json),
and the earlier [state report](../reports/cycle_2026-09-23_xauusd_state.md).
These are *existing discovery-sample results*, not fresh confirmation.

- H-ST-02 established a **discovery-sample absolute-move contrast**: a past
  16-quote move of at least $0.20 versus at most $0.10 predicts a larger
  *absolute* move 256 quotes later (ratio 1.476). The volatility preregistration
  expressly did not reopen it or preregister a direction.
- H-VL-01 was `TESTED`, not `PROMISING`: at 256 quotes the high state cleared
  each cell's spread plus $0.02 79.50% of the time versus 71.96% in the low
  state (7.54 percentage points). Median time to clear spread plus $0.01 was
  17 versus 29 quotes. H-VL-02 (extreme versus ordinary high, ratio 1.36),
  H-VL-03 (quiet-to-expansion versus quiet, ratio 1.34, with its dollar gap only
  $0.0026 above its floor), and H-VL-04 (persistent high versus contraction,
  ratio 1.45) also passed their *magnitude* gates. All four are process
  measurements on the reused 60%, not evidence of profitable trading.
- The high state's mean *signed* 256-quote move was only +$0.008 against a
  roughly $0.276 spread; P(up) was 0.506. The extreme and transition cells did
  not supply a side either. A marginal signed mean close to zero cannot rule
  out a prespecified **conditional** direction, but neither does it support one.
  Existing short-horizon directional hypotheses H-QD-01/02 and the 256-quote
  long-run fade H-ST-03 were rejected. A failed fade is **not** evidence to
  follow the run. The independently preregistered [15-minute impulse
  question](../data/evidence/owner_impulse_oos_preregistration_2026-09-19.json)
  and its [frozen report](research/impulse_continuation_report_xauusd_dukascopy_15m.md)
  are `REGIME_DEPENDENT / BLOCK`, with an inadequate completeness/execution
  basis. They motivate asking about signed persistence, **not** assuming it
  exists here; 256 quotes are not 12 fifteen-minute bars.

**Choose the first path: test one independently motivated directional
hypothesis conditional on the already defined high/low volatility states.**
No additional state/transition measurement is needed to ask whether a side
exists. More slicing of H-VL-02/03/04, especially the thin H-VL-03 pass, would
consume the repeatedly used discovery sample without supplying a directional
mechanism. Use the broad, previously locked high/low contrast, **not** a
highest-ranked signed panel cell or a newly tuned extreme/transition subgroup.

What remains unknown: whether the sign of a *past multi-quote price displacement*
contains predictive information about the **future signed** move at all; whether
any such information is stronger in the established high state than in the low
state; whether it survives actual quoted bid/ask costs, a fixed cost stress and
one-quote delay. Direction is a separate conjecture from volatility clustering.
Broker fills, commissions, slippage and a verified session clock are unavailable.

## One bounded hypothesis — H-DIR-01 (NOT TESTED)

**Mechanism conjecture.** A sustained signed net displacement over 16 quotes
can proxy temporary directional price pressure/information assimilation. If
that pressure persists during the already measured high-volatility state,
following its *past* sign might predict a later signed move. If volatility
merely clusters in size while direction is unpredictable, the sign-aligned
move will not exceed the bid/ask cost. This is a falsification of a prior
impulse-persistence idea, **not** an inference from the positive H-VL results
or a retest/reversal of H-ST-03's run-length fade.

**Prediction.** At a fixed 256-quote horizon, the sign of the preceding
16-quote mid displacement has positive, material, cost-stressed directional
alignment in the pre-existing high state **and** more gross sign-alignment than
in the pre-existing low state. Both prior up and prior down signs must work;
there is no choice of a winning side. Null: the high-state sign provides no
cost-positive information and/or its alignment is no greater than in low
volatility. A common upward drift, a larger *absolute* move alone, or one
favorable sign does not pass.

**Population and features.** Only the canonical `XAUUSD_730d_20260919T114013Z.zip`
(verified archive SHA-256 `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723`,
manifest digest `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`).
Original global quote order, bid, ask and raw `time_msc` only. Define mid
`m_i = (bid_i + ask_i)/2`, spread `q_i = ask_i - bid_i`, past displacement
`r_i = m_i - m_(i-16)`, and sign `s_i = sign(r_i)`. High is `|r_i| >= $0.20`;
low is `|r_i| <= $0.10`; ignore the middle and `r_i = 0` (count and report
exclusions). Cuts are the **existing** H-ST-02/H-VL-01 cuts, interpreted in
integer half-cent mid-price units to avoid floating-point boundary changes.
No clock labels, volume/last, flags, session filter, new state, model, or
threshold search. Unlike a one-quote sign or a run-length-5 fade, the feature
is the sign of the *net 16-quote displacement*; the volatility state uses its
absolute value. The sign is a new, unproven assumption, not a result already
seen in a panel.

**Time and sampling lock.** Discovery is exactly `time_msc < 1764563969254`
(first 60% of the pre-existing raw span). Every feature, delayed entry and
exit quote must be inside it. Never read a quote at or after that cutoff for
this experiment, even to complete a forward outcome; drop and count boundary
windows instead. Reuse the previously recorded dataset identity/cutoff, not
new held-out counts or statistics. Do **not** run the existing full-archive
scan/extraction routines unchanged: they iterate beyond this boundary. A
future implementation must read only a provenance-qualified discovery view;
if the archive layout cannot provide it without accessing locked quote rows,
leave H-DIR-01 `NOT RUN` and report the access blocker. No rows are repaired or
interpolated; a backward timestamp, inverted/invalid quote, changed identity
or changed partition makes the measurement `INCONCLUSIVE`. Long raw gaps are
not silently called weekends.

The **only** outcome horizons are `h = 256` quotes (primary) and `h = 1024`
(sign-stability check, not another discovery opportunity). The sign is known at
row `i`; the earliest hypothetical observation is row `i+1`. For each horizon
use original global anchors `i % (h+18) == 0`, with `i >= 16` and `i+1+h`
still in discovery. This fixed stride makes the complete used windows
`[i-16, i+1+h]` non-overlapping *within each horizon*. No horizon, side,
threshold, or state will be selected after looking at results. The 1024-quote
sample may overlap the 256-quote sample and is **not** independent evidence.

**Measured outcome and economic filter (no simulated fills).** At each anchor,
let `g_(i,h) = s_i * (m_(i+1+h) - m_(i+1))` and
`c_(i,h) = (q_(i+1) + q_(i+1+h))/2 + $0.02`. Let `y = g - c`.
This charges both observed endpoint bid/ask quotes (equivalent to buying at
ask and selling at bid, or selling at bid and buying at ask), **plus** a fixed
one-cent-per-side uncertainty/slippage stress. It is a counterfactual
cost filter, not a broker fill or an instruction to place orders. Unmeasured
commission/latency can only weaken any executable claim.

To avoid choosing the favorable sign, for each state and horizon calculate
`G_state = (mean(g | s=+1) + mean(g | s=-1))/2` and
`N_state = (mean(y | s=+1) + mean(y | s=-1))/2`. The two *jointly required*
primary estimands are `T1 = N_high` (cost-stressed directional effect) and
`T2 = G_high - G_low` (incremental sign alignment, **gross** so a difference
in spreads alone cannot create the interaction). Fixed, binding material floors:
`T1 >= $0.05` and `T2 >= $0.05`, **five observed one-cent bid-price grid
steps each**, over and above the $0.02 stress and the quoted bid/ask cost
for T1. A p-value cannot replace either floor. Report both signs' sample sizes,
mean gross/net moves, spreads, sign-match rates (flats counted as nonmatches),
and all exclusions, including unfavorable results. Rates are diagnostics, not
new success criteria.

**Uncertainty, controls and non-negotiable artifact gates.** Define three equal
raw-`time_msc` terciles *within discovery* before measuring outcomes. For the
256-quote sample require at least 1,000 events in **each** `(tercile, high/low,
prior up/down)` cell; for 1024 require at least 1,000 pooled in each
`(high/low, prior up/down)` cell. These are minimum counts, not a power
certificate. Resample paired outcomes/signs/states in contiguous blocks of
1,024 consecutive **global primary-horizon anchors**, splitting blocks at
tercile boundaries; retain every anchor, including middle/zero-sign anchors,
in its block. Require at least 50 such blocks in each tercile. Use 9,999
stratified block-bootstrap draws with seed `20260923`, drawing the observed
number of blocks with replacement **within each tercile**. For either
observed statistic `T` and its bootstrap replicates `T*`, use the centered
one-sided p-value `(1 + count(T* - T >= T)) / 10000` for the null `T <= 0`;
its one-sided 99% lower bound is `T - percentile_99(T* - T)`. Both lower
bounds must exceed zero. Do not use an iid quote binomial p-value.

One prespecified negative control: within each `(tercile, chronological
1,024-anchor block, high/low)` group, shuffle the **past sign labels** among
eligible events, leaving outcomes, states, spreads and sign counts fixed. Use
1,999 permutations with seed `20260923`; for either estimand use
`(1 + count(T_shuffled >= T_observed)) / 2000` in the predicted positive
direction. Apply **Holm-Bonferroni at family-wise 0.01 across all four
predeclared p-values** (two block-bootstrap tests and two shuffle comparisons);
require *all four* adjusted p-values below 0.01. The shuffle is an artifact
check, not proof of
independence or a way to choose a favorable result. No alternative shuffle,
block length, or multiple-testing family can be selected afterward.

Additionally require `mean(y | high, s=+1) > 0` and
`mean(y | high, s=-1) > 0`, **each in all three terciles**, and `T1 > 0`
and `T2 > 0` in each tercile. At 1024 quotes require `T1 > 0`, `T2 > 0` and
both high-state sign-specific net means positive, with the minimum counts
above; do not use its p-value as a substitute for the primary test. As a fixed
gap sensitivity, recompute 256-quote `T1` and `T2` after omitting windows
containing a raw interarrival gap of **at least one hour**; both must remain
positive, with at least 1,000 retained events in each pooled
`(high/low, prior up/down)` cell. This is a spacing check, not a
session/weekend classification or an invitation to search gap cutoffs. Report
the retained n. Too few events or an inapplicable bootstrap/permutation check
is `INCONCLUSIVE`, never a pass.

These are joint gates on **one** hypothesis; neither the low state, a sign,
a tercile, a gap subset nor the 1024 horizon is a separate selectable winner.
Record H-DIR-01 and all earlier failed/attempted families in the cumulative
research ledger. Local Holm adjustment does **not** make the repeatedly used
60% an independent confirmatory sample; even a clean pass remains provisional.

## What would make us continue or stop

- **Continue research only if every primary statistical, material, cost,
  mirrored-sign, tercile, 1024 and gap gate above passes:** record
  `SURVIVED_DISCOVERY_ONLY`. The next action would be an independently reviewed,
  separately frozen out-of-sample protocol/data decision, **not** another
  feature search, a trade, or automatic access to the existing held-out 40%.
  No validation or economic/executable edge is established by this pass.
- **Stop this directional-impulse/high-versus-low branch** if either material
  floor is missed, costs overwhelm signed movement, or the predicted sign,
  mirror, tercile, stability or gap check fails with adequate data: record
  `REJECTED` with the failing metric. This rejects **this mechanism at these
  settings**, not every possible XAUUSD edge.
- If identity, boundary integrity, minimum counts, or a required uncertainty
  check cannot be established, or if the point estimates clear the floors but
  adjusted inference/negative control does not distinguish the effect from
  noise or artifact, record `INCONCLUSIVE` and stop. Insufficient evidence is
  not evidence of no effect. For **either** stopping outcome, do not reverse
  the sign, substitute extreme/transition cells, tune a threshold, pick the
  best horizon, or open the held-out span to rescue it.

**Current action:** document this decision only. No implementation, dataset
scan, validation, execution-enablement, order submission or promotion is part
of this decision record. The held-out 40% stays untouched for every outcome.
