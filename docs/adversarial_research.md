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

The current canonical dataset is one 500-bar synthetic XAUUSD 1H fixture. It
is useful for mechanism checks but not for real-market claims. Current campaign
and edge artifacts are `BLOCKED_INSUFFICIENT_DATA`; null/placebo/regime,
gross/net cost, and execution metrics are unavailable or not bound to the
current experiment. No candidate is promoted and the system remains
`NO_TRADE`.

The paper/shadow comparison has event alignment evidence for its available
records, but DEMO execution is disabled and the canonical observation store
has zero observations. Therefore demo fill/slippage/latency/P&L attacks are
not silently replaced by zeros; they remain unavailable.

## Integration and memory

Campaign attack results, blocked trials, rejections, and failure reasons are
stored in the cumulative research/experiment ledger. Similar failed searches
remain discoverable through research memory. Trial count is never reset to
make a candidate look more significant.

**Adversarial conclusion:** acquire claim-eligible history, preregister the
hypothesis and attacks, lock the validation partition, then rerun all controls
from the same canonical dataset. Until then, keep `NO_TRADE`.
