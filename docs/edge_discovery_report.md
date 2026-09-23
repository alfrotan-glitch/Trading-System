# Edge Discovery Report — Research Memory and Current Evidence

**Updated:** 2026-09-18
**Branch:** `arena/01a0b574-trading-system`
**Current-state authority:** [`docs/current_state.md`](current_state.md)
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

These capabilities do not imply that any current dataset or result proves a
profitable market edge.

## B. Canonical datasets and readiness

The current research population includes:

- REAL XAUUSD 15m history `20260918-010+8f120133-1ba57af7`, 26,038 bars,
  approximately 407 days, class `REAL`, suitable for the executed bar-based
  impulse study under declared costs;
- unchanged synthetic XAUUSD 1H fixture `20260918-010-572728d9`, 500 bars,
  approximately 20.83 days, class `SYNTHETIC`, mechanism-validation-only.

The REAL impulse study returned `REGIME_DEPENDENT` / `go_block = BLOCK`.
Continuous historical bid/ask/tick execution-cost evidence is absent, so R5
remains FAIL/non-blocking. Duplicate raw/curated representations are not
independent samples. See `docs/current_state.md` and
`docs/data_provenance_xauusd_dukascopy.md`.

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
real terminal/session is available. `DEMO_EXECUTION` is `DISABLED BY POLICY` by
default and `ENABLED_AUTHORIZED` once a recorded owner authorization exists
(DEMO account only); in both cases an order additionally requires the staged
progression, a pinned+confirmed identity, an eligible registered strategy and
22 pre-trade checks — currently `NO_TRADE`.

Current derived comparison evidence reports 6 paper records, 10 shadow
intents, zero canonical DEMO_FORWARD observations, measured paper/shadow event
alignment of 0.5, and `UNAVAILABLE` demo fill/slippage/latency/PnL metrics.
No old JSON sample is relabeled as a real observation.

## F. Research memory and next falsification action

Negative evidence is retained in the experiment ledger and research memory so
similar blocked searches are not silently presented as novel winners. The REAL
bar-based study has now run and must not be rerun merely to seek a favorable
result. The next research milestone is improved execution-cost evidence (R5),
followed by a rerun of the same preregistered design if that evidence is
acquired. A separate operator milestone is the first real Windows/MT5
observation session.

**Conclusion:** no validated edge is demonstrated. Keep `NO_TRADE`; the REAL
result remains `REGIME_DEPENDENT / BLOCK`.
