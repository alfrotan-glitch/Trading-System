# Edge Discovery Report — Research Memory and Current Evidence

**Updated:** 2026-09-18
**Branch:** `arena/01a0b358-trading-system`
**Scope:** research plane only; no DEMO execution and no LIVE.

This report supersedes older snapshots that described duplicate datasets,
placeholder execution metrics, or a smaller/different trial ledger. Current
claims must be regenerated from the canonical stores and carry their own
experiment/configuration lineage.

## A. Research capabilities

QTS provides a bounded modular-monolith research path with:

- preregistered hypotheses and explicit mechanism, prediction, null,
  competing explanations, falsification criteria, required data,
  horizon/population, and regime fields;
- immutable experiments with dataset/version, provenance, manifest checksum,
  code version, seed, split definition, cost assumptions, exclusions,
  configuration hash, outcomes, conclusions, and failure reasons;
- cumulative trial accounting in SQLite, including blocked, rejected, and
  failed trials; no denominator reset;
- chronological splits, locked-test access logging, walk-forward and CPCV/PBO
  gates where actually executed, parameter perturbation, cost stress, and
  explicit missing-control blockers;
- bounded campaigns and autonomous research planning with durable negative
  evidence and research memory;
- evidence exports that distinguish `MEASURED`, `UNAVAILABLE`,
  `INSUFFICIENT_EVIDENCE`, and `BLOCKED_INSUFFICIENT_DATA`.

These capabilities do not imply that the current fixture has enough evidence
for a market claim.

## B. Canonical dataset and readiness

The canonical inventory contains one dataset version:

- `XAUUSD_1H_500`, version `20260918-010-572728d9`;
- 500 UTC OHLC bars spanning approximately 20.83 days;
- source `SYNTHETIC:fixture:XAUUSD_1H_500.csv`, class `SYNTHETIC`;
- fixture quality checks pass, but bid/ask, tick, broker session, measured
  spread, real-volume semantics, and execution history are unavailable;
- research status: `MECHANISM_VALIDATION_ONLY`.

The readiness gate blocks claim-grade research because provenance is not an
allowed real-market class, depth is below 5,000 bars, and span is below 180
days. Duplicate raw/curated inventory rows are not counted as separate
samples.

## C. Current campaign evidence

The derived artifacts currently record:

- `campaign_last.json`: 2 bounded trials, zero passed,
  `BLOCKED_INSUFFICIENT_DATA`;
- `autonomous_campaign.json`: 6 bounded trials, zero passed, self-audit
  `BLOCK — independent audit gates remain unproven`;
- `edge_validation.json`: `BLOCKED_INSUFFICIENT_DATA`, with synthetic
  provenance, depth/span blockers, and cumulative ledger accounting;
- `campaigns_summary.json`: compact pointer to the canonical bounded campaign,
  not an independent trial ledger.

Every blocked trial retains its hypothesis/configuration/provenance/failure
reason. No candidate is promoted, and the correct operational conclusion is
`NO_TRADE`.

## D. Scientific controls and limitations

Where a control was not bound to the current experiment, the evidence says so
rather than borrowing a result from another run:

- null and placebo controls: unavailable/not implemented for this evidence
  object;
- regime result: unavailable as a separately trial-bound artifact;
- gross/net economic decomposition and realized expectancy: unavailable;
- forward execution comparison: unavailable because DEMO execution is
  disabled and the observation store has no session;
- cost stress: measured rerun values are retained when present; missing,
  non-numeric, and non-finite values block explicitly (`MEASURED_INVALID` for
  invalid measurements).

`NaN` and `inf` are never converted to favorable values. Unsupported
promotion is never substituted for missing evidence.

## E. Paper, shadow, and forward boundary

Paper records are simulated. Shadow records would-be intents and submits no
orders. DEMO_FORWARD records real MT5 demo-account observations only when a
real terminal/session is available. DEMO_EXECUTION is disabled by product
policy and has no order path in this product boundary.

Current derived comparison evidence reports 6 paper records, 10 shadow
intents, zero canonical DEMO_FORWARD observations, measured paper/shadow event
alignment of 0.5, and `UNAVAILABLE` demo fill/slippage/latency/PnL metrics.
No old JSON sample is relabeled as a real observation.

## F. Research memory and next falsification action

Negative evidence is retained in the experiment ledger and research memory so
similar blocked searches are not silently presented as novel winners. The
next meaningful experiment requires a provenance-qualified dataset with a
declared population, horizon, timestamp/session semantics, enough depth/span,
and measured cost fields. Then regenerate all controls from that one dataset,
lock the validation partition before selection, and inspect both evidence for
and evidence against the hypothesis.

**Conclusion:** no validated edge is demonstrated. Keep `NO_TRADE`; acquire
claim-eligible data before interpreting model returns.
