# Preregistration — fixed causal broker-quote ML assay

## Question

Does a fixed, causal statistical classifier using only the local MT5
XAUUSD bid/ask ledger predict a cost-surviving five-minute directional move,
with a longer-horizon stability check, after chronological walk-forward and
an untouched 40% time holdout?

This is a research assay, not a strategy authorization. `LIVE` remains
locked and order submission remains disabled.

## Data and separation

- Use the complete local 365-day MT5 bid/ask tick ledger whose timestamp basis
  was measured in the same read-only session and bound to its dataset digest.
- Aggregate raw ticks into one-minute bars without repair or reordering. A
  minute is usable only when its quote fields are finite and `ask >= bid`.
- Define the discovery/holdout boundary as the existing raw-time 60/40
  `discovery_cutoff` used by the broker research engines. The model may fit
  only samples whose signal, entry, and exit are strictly before that cutoff.
  The final holdout is evaluated once with the model frozen after discovery.
- A signal is formed at minute `i` close. Entry is the next minute open
  (`i+1`), which is the fixed one-bar latency. The primary exit is minute
  `i+5` close. The stability exit is minute `i+15` close.
- Samples crossing a missing-minute gap are excluded. No weekend or session
  label is used.

## Fixed model

Fit one ridge-logistic classifier with no hyperparameter search. The target is
whether the five-minute mid-price move from entry mid to exit mid is positive.
Features available at signal close `i` are exactly:

`log-return` over 1, 3, 5, 15, and 60 minutes; rolling mean absolute return
over 5, 15, and 60 minutes; and current mean quoted spread in basis points.

Features are standardized using the training prefix only. Use ridge strength
`alpha=0.01`, Newton iterations `50`, and seed `42` for bootstrap only. A
probability at least `0.5` is long; below `0.5` is short. There is no
confidence threshold, feature selection, threshold search, or model search.

## Evaluation

- Use the first 20% of the discovery time span as fixed model warm-up.
- Evaluate five equal chronological walk-forward folds over the remaining 80%
  of discovery. Each fold fits on all earlier usable samples and evaluates
  only later samples. A trade's exit must remain within its fold.
- At most one trade may be open: after a selected signal, the next eligible
  signal starts after that trade's fixed exit. This deterministic non-overlap
  rule is applied before viewing outcomes.
- Fit the final model on all usable discovery samples and evaluate the frozen
  holdout once. The holdout is not used for model choice or threshold choice.
- Primary gates require at least 500 non-overlapping trades in every fold and
  at least 500 holdout trades. Report all counts even if a gate fails.

## Costs and gates

Entry and exit use the actual broker sides: long enters ask/exits bid; short
enters bid/exits ask. This measures the quoted spread. Commission, slippage,
and financing remain unmeasured. Apply additional fixed round-trip stress of
0, 1, and 2 bps to the entry mid and report each separately.

The assay can be `PROMISING_NOT_VALIDATED` only if all of the following hold:

1. every fold has at least 500 trades;
2. at least four of five folds have positive mean net bps at 2-bps stress;
3. the frozen holdout has at least 500 trades;
4. holdout mean net bps is positive at 2-bps stress; and
5. the 95% moving-block bootstrap CI for holdout mean net bps at 2-bps stress
   excludes zero.

Otherwise classify the result as `REJECTED` when the sample minimum is met and
the cost gate fails, or `INCONCLUSIVE` when sample or inference requirements
are not met. No result from this assay authorizes trading or product
integration.

## Integrity and safety

The runner must record the dataset digest, timestamp-basis status, discovery
and holdout counts, feature/model constants, missing-minute exclusions, cost
status, fold metrics, bootstrap seed, and safety fields. It must not copy raw
broker/server/account metadata into tracked evidence. No MT5 order API is
called; `orders_submitted=0`, `DEMO_EXECUTION=DISABLED`, and `LIVE=LOCKED`.
