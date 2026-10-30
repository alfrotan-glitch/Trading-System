# CPI-acceleration gate — input failure; hypothesis inconclusive

- **Cycle:** `LH-XAUUSD-CPI-ACCELERATION-GATE-2026-10-19`
- **Frozen protocol:** `docs/research/preregistration_longhistory_cpi_acceleration_gate_2026-10-19.md`
- **Protocol SHA-256:** `3045b7be5b834b5e5815f74f11cf34dc7c0d4cf844c0ee100509aec7ea23f8d1`
- **Protocol amendment freeze:** `82638f7175e7620d5086b504b0bd72c1e2ac0af3`
- **Runner/test commit:** `0cdf928538a5682b835d9745457839796490d2a7`
- **Evidence:** `data/evidence/longhistory/cpi_acceleration_gate_discovery_dev.json`
- **Outcome:** **INCONCLUSIVE — source schema failed closed before CPI features or candidate returns were calculated.**

## What happened

The one authorized `--stage screen` invocation verified the preregistration hash and ancestry, verified the pinned Gold input, and then stopped at the CPI CSV schema check. The pinned World Bank data-package metadata describes `Country Name`, `Country Code`, `Year`, and `CPI` columns, but the downloaded CSV header did not match that frozen schema. The runner therefore returned `INCONCLUSIVE` before reading any numerical CPI values or calculating candidate/comparator outcomes. No strategy metric, DSR, or gate was calculated.

The downloaded CPI file was the exact preregistered blob (`datasets/cpi@3750e45064a99b0452deb1423a416e4d5473a58e`, Git blob SHA-1 `20c3e21ab08e993b9ab1eb1b2e4c442f43042b4a`; SHA-256 `182baa44c536079bea07bb8700c37c85441c3d7d5f8e6dd68fb92fcb4a7815e8`). This is a mismatch between the pinned file and its metadata contract, not permission to infer or substitute a different schema.

The evidence records `candidate_outcomes_calculated=false` and cumulative `N=359`. Accordingly, this failed input preflight does **not** add a completed configuration to the long-history DSR denominator. No CPI value was repaired, no alternate source/country/lag was substituted, and the candidate will not be rerun under this protocol.

## Repository-wide novelty audit

A review of the full existing research record after the preflight found that CPI inflation-regime conditioning had already been explored in Wave-9: `docs/research/expert_handbook_2026-10-17.md` §7 and `QTS_PROJECT_CONTROL.md` ARCH-071 record CPI YoY-level and six-month inflation-momentum gates as discovery-negative on the ≤1989 partitions. The registered annual-acceleration gate is another member of that already-explored inflation-gating family, not a sufficiently distinct new mechanism. This attempt should not be repeated even if a different CPI file/schema is found. The source failure occurred before values/outcomes, so this does not change the prior Wave-9 evidence or add a trial to N.

## Continuation-checkout provenance caveat

The execution evidence preserves the original protocol/runner identities (`82638f7…` and `0cdf928…`). In the current continuation checkout, `.git` is shallow and rooted at `f468b0c`; `git cat-file` cannot resolve those earlier commit objects. The protocol, runner, tests, and evidence files are preserved in the worktree, but a consolidation commit in this checkout cannot retroactively establish the earlier freeze ancestry. This further limits provenance; it does not justify rerunning the candidate.

## Safety and disposition

- No post-1999 price value was converted or used.
- No 2000+ evaluation metric, 730-day tick row, or locked holdout was accessed.
- No order was submitted; `strategy_promoted=false`; `LIVE=LOCKED`.
- This is neither a rejection nor evidence for an inflation edge. The hypothesis remains **INCONCLUSIVE** because the registered source contract failed before measurement.
- The source has no historical CPI release-vintage record in any event; even a successful backtest using this dataset would not have established point-in-time availability or justified validation/live use.
- Do not correct the loader, substitute a format/source, or rerun this candidate. Any new macro hypothesis requires its own preregistration and starts from the current `N=359`.
