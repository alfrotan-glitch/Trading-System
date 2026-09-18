# Adversarial Research

**Updated:** 2026-09-18
**Purpose:** attack hypotheses and evidence; never confirm a strategy merely
because a return is attractive.

## Attack dimensions

`src/qts/research/adversary.py` and the validation pipeline are expected to
look for:

- future leakage, normalization leakage, feature/locked-test contamination;
- parameter fragility and unstable exits;
- regime/sample dependence and population overreach;
- spread, slippage, latency, and gross/net cost sensitivity;
- null/placebo equivalence and multiple-testing/selection bias;
- unrealistic fills, missing bid/ask, missing execution timestamps;
- selective reporting, missing drawdown, and provenance/data-quality flaws;
- missing forward observation or unbound paper/shadow comparison.

Every important candidate report should include both evidence for and evidence
against, the attack inputs, code/dataset/experiment lineage, and a deterministic
verdict. Missing attack evidence is a blocker, not a pass.

## Current negative evidence

The canonical inventory now contains a REAL, claim-eligible dataset:
`20260918-010+8f120133-1ba57af7` (XAUUSD 15m, 26,038 Dukascopy tick-derived
mid OHLC bars, 407.00 days, 12/12 quality checks pass, readiness `READY`;
provenance record `docs/data_provenance_xauusd_dukascopy.md`). The 500-bar
synthetic XAUUSD 1H fixture remains registered, labelled `SYNTHETIC`, and is
mechanism-validation-only.

The pre-registered impulse study has been re-run against the REAL dataset in
`REAL_CLAIMS` mode. The measured conclusion is `REGIME_DEPENDENT` /
`go_block = BLOCK`: no candidate is promoted and the system remains
`NO_TRADE`. R5 (continuous bid/ask/tick execution-cost history) remains
`FAIL`, so execution-realism attacks are still unavailable rather than passed;
campaign/edge artifacts generated from the synthetic fixture remain
`BLOCKED_INSUFFICIENT_DATA`.

The paper/shadow comparison has event alignment evidence for its available
records, but DEMO execution is disabled and the canonical observation store
has zero observations. Therefore demo fill/slippage/latency/P&L attacks are
not silently replaced by zeros; they remain unavailable.

## Integration and memory

Campaign attack results, blocked trials, rejections, and failure reasons are
stored in the cumulative research/experiment ledger. Similar failed searches
remain discoverable through research memory. Trial count is never reset to
make a candidate look more significant.

**Adversarial conclusion:** the acquired REAL dataset was attacked by the
existing controls (chronological splits, locked partition untouched, Holm
correction, deflated Sharpe against the full ledger, cost multiplication) and
survived only as `REGIME_DEPENDENT` with a `BLOCK`. Execution-realism attacks
remain unavailable until continuous bid/ask/tick history is acquired and
bound to the same lineage. Keep `NO_TRADE`.
