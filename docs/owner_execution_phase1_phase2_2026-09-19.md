# Owner execution decision: lineage and OOS validation

## Phase 1 — prior DEMO lineage

The repository contains only the derived `forward_observation_manifest.json`
for `FS-f374b6`. It records 13,222 DEMO observe-only ticks, zero signals,
zero orders, a 5h45m session, and termination on a stale-tick error. It does
not contain the canonical SQLite store, a `qts.session_evidence.v1` export, an
acquisition ledger, a research snapshot, or a verifier result.

The session cannot be independently re-verified under the current contracts
from this repository. This is a repository-boundary verdict, not a claim about
the operator's Desktop: the sandbox cannot inspect the Desktop state. The
historical manifest is preserved unchanged and remains bounded observation
context only. No ledger entries or rows were invented or repaired.

If the operator's original artifacts become available, the only permitted next
operation is read-only verification. A passing verifier would make the session
usable for pipeline and quote-observation context, but it would still not prove
fills, slippage, latency, or profitability.

## Phase 2 — exact frozen candidate

The existing frozen REAL artifact identifies the regime-conditional candidate
families `IMP-BE-B`, `IMP-RB-B`, and `IMP-RE-B`. The declared hypothesis is
short-horizon continuation after an unusually strong directional move, measured
at 12 bars with a 4-bar sensitivity horizon, against a matched baseline. The
frozen source artifact's locked chronological boundaries are discovery end
15,622, validation end 20,830, total 26,038.

A separate preregistration was created before any new validation:

```text
data/evidence/owner_impulse_oos_preregistration_2026-09-19.json
```

It fixes the candidate definition, population, OOS partition, metrics, declared
cost assumptions, sensitivity, falsification criteria, and stop conditions.

## Validation decision

A new OOS run was **not executed**. The immutable source dataset referenced by
the frozen artifact is absent from this sandbox. Reconstructing, substituting,
or rerunning on another dataset would violate provenance and turn the proposed
validation into a different experiment. The frozen report is evidence of the
prior run, not a new independent OOS result.

The machine-readable decision is:

```text
data/evidence/owner_execution_decision_2026-09-19.json
```

Current status:

```text
lineage: UNRECOVERABLE_FROM_REPOSITORY / Desktop state not determinable here
preregistration: CREATED
new OOS validation: BLOCKED_MISSING_IMMUTABLE_SOURCE
candidate promotion: BLOCKED
live trading: DISABLED
```

The next minimum evidence is recovery of the exact immutable source and its
provenance manifest, followed by one execution of the preregistered OOS check.
No strategy search, parameter changes, trial reset, or capital exposure is
authorized before then.
