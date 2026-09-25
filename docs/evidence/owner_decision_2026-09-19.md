# QTS owner decision: truth-first path to tradeability

## Decision

QTS has **not established a validated executable edge**. The project must not
start an unconstrained strategy search, add a model, or authorize capital. The
shortest defensible path is a controlled validation of the one existing
candidate family, followed by execution-realism validation. If that candidate
fails the unchanged gates, QTS stops rather than broadening the search
indefinitely.

## Evidence assessment

### What is supported

- The Dukascopy-derived XAUUSD 15-minute study is real-market bar research and
  reports `REGIME_DEPENDENT`, not an unconditional edge. Its promotion is
  blocked and it is not evidence of fills.
- The earlier synthetic impulse study is correctly blocked for provenance,
  depth, regime coverage, freshness, execution data, and event sufficiency.
- The private WM Markets MT5 dataset provides broker-specific quote history,
  but its 108 >24-hour tick-arrival gaps remain unresolved. A gap is an
  observation, not proof of closure or missing data.
- The DEMO observation session proves bounded observe-only pipeline operation and
  measured quote spreads. It ended on stale-data error and has no fills,
  slippage, latency experiment, or PnL.
- Existing verifiers and research-integrity controls are the correct safety
  boundary. R5 remains FAIL/non-blocking.

### What is not supported

There is no evidence of a positive, causal, out-of-sample, cost-inclusive
strategy with broker-realistic execution. No evidence supports live trading,
position sizing, or a claim that quote history is execution evidence.

## Chosen sequence

### Gate A — freeze the research question

Use only the existing regime-conditional impulse continuation candidate and its
already declared mechanism. Record one preregistration before any rerun:
feature definitions, event horizon, entry/exit rules, spread/slippage/latency
model, regime partition, OOS dates, metrics, minimum events, trial identifier,
and failure criteria. Do not change the frozen study or reset trial accounting.

### Gate B — obtain the smallest execution evidence needed

Use the existing private WM quote history for quote-level spread and tick
freshness diagnostics only after its integrity report is available locally.
The 108 gaps remain a separate data-availability limitation. The prior DEMO
session is retained for pipeline evidence but cannot satisfy fill-cost R5.

If the original canonical observation store/session export can be recovered,
verify it under the current verifier and reuse it. Only if it is absent or
refused should the operator run a new, narrowly scoped observe-only cost
experiment. That experiment must measure collection latency, freshness,
spread, outage/censoring, and a declared proxy cost model. It must not submit
orders and cannot by itself prove profitability.

### Gate C — unchanged out-of-sample validation

Run the preregistered candidate once against untouched OOS periods, including
regime-specific results, cost sensitivity, multiple-testing correction, and
trial ledger updates. Reject if aggregate or required regime performance fails,
if the edge depends on an unresolved data interval, or if cost assumptions are
not supported. No parameter sweep is authorized before this decision.

### Gate D — shadow and controlled demo only

A surviving candidate proceeds to shadow observation, then explicitly approved
DEMO execution only if the existing safety authority permits it. Require
reconciliation, stale-data kill switch, exposure limits, order/fill audit, and
independent reproduction. Demo success is never live eligibility.

### Gate E — capital decision

Live trading remains locked unless independent out-of-sample evidence,
execution-cost evidence, operational controls, and bounded-risk approval all
pass. If the candidate fails Gate C or Gate D, stop the strategy program and
publish the negative result. Do not manufacture a replacement edge through
multiple unregistered searches.

## Minimum missing evidence

1. A re-verifiable session export/canonical-store lineage for the prior DEMO
   observation, or a minimal replacement observe-only cost experiment if it is
   unrecoverable.
2. A preregistered, unchanged candidate rerun on untouched OOS periods with
   realistic cost sensitivity and full trial accounting.
3. If OOS performance survives, actual execution observations sufficient to
   estimate latency, rejection, spread, and slippage for the intended order
   path. Quote-only history is insufficient.

The first decision is lineage recovery, not a new observation by default. The
second is a single falsifiable candidate validation, not strategy discovery.

## Stop condition

If no candidate passes the unchanged OOS and execution-realism gates, QTS must
stop. “No validated edge established” is the scientifically correct terminal
outcome and is preferable to activity, overfitting, or capital loss.
