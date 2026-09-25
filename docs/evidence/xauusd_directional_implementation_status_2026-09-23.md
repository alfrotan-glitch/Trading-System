# H-DIR-01 implementation and data-access status — 2026-09-23

**Experiment: NOT RUN / ACCESS BLOCKED.** The next-step decision and complete
hypothesis/gates were first recorded in
[`xauusd_directional_next_step_2026-09-23.md`](../xauusd_directional_next_step_2026-09-23.md).
This page records implementation **after** that decision; it does not change
any feature, horizon, cost, threshold, statistic or stopping rule in the
preregistration. The previous volatility result remains `INCONCLUSIVE`.

## What was built (offline research only)

- `src/qts/research/xauusd_directional.py`: bid/ask event-study math at the
  locked 256/1024 quote horizons; global nonoverlapping anchor identity;
  sign-balanced high-versus-low outcomes; both endpoint spreads plus $0.02;
  one-quote delay; tercile, mirror, gap and horizon checks; fixed block
  bootstrap, within-state/time-block sign-shuffle control, and Holm across
  exactly four predeclared tests. No trading/strategy path exists in the module.
- `src/qts/research/xauusd_directional_view.py`: separate input boundary.
  It will read **only** an independently pinned discovery-only manifest,
  require original row indices 0 through 70,834,425 without gaps, check all
  Parquet row-group timestamp bounds and part digests *before* accessing any
  bid/ask, then guard the actual timestamps again. A full zip, mixed boundary
  part, unpinned view, changed digest, missing statistics, or incomplete view
  fails closed; an unexpected locked timestamp explicitly **invalidates** the
  attempt instead of claiming that the span remained closed. It never repairs
  rows or infers a clock/session.
- `scripts/run_xauusd_directional.py`: explicit manual invocation only; no
  release download, ZIP extraction, CI trigger, or archive fallback. Without a
  separately approved view authority and discovery-only view it records
  `NOT RUN`, not an observed failure or positive directional result.
- `tests/test_xauusd_directional.py`: synthetic quote and Parquet fixtures
  cover sign/state boundary cuts, quote-side costs, lag, batch invariance,
  raw gaps, time-cutoff refusal before price access, bad/mixed/unpinned input,
  bootstrap/shuffle determinism, material floors and fail-closed verdicts.

## Why the real measurement has not started

The [independent, metadata-only boundary audit](xauusd_directional_boundary_audit_2026-09-23.md)
now proves that the exact Discovery split is **inside** original immutable
`part-000441.parquet`: global rows `[70,783,710, 70,916,415)` comprise
50,716 Discovery and 81,989 held-out rows. The [bounded JSON
evidence](../../reports/xauusd_discovery_boundary_audit.json) is from GitHub
Actions [run 35856015114](https://github.com/alfrotan-glitch/Trading-System/actions/runs/35856015114),
which checked the original ZIP checksum, acquisition manifest checksum and
ledger/dataset digest **without opening a single Parquet quote member**. The
sandbox never held the ZIP. The metadata job handled only opaque ZIP bytes,
ZIP directory metadata and the manifest, and never ran H-DIR-01.

No independent immutable row-group/page index or Discovery-only partition was
found. The acquisition ledger has part counts but lacks internal Parquet
bounds. Reading the mixed part to look for an inner row-group boundary or
slicing its Discovery rows would also open/decompress held-out quote bytes;
that is forbidden. Prior full-archive extraction/scanning workflows cannot
be used for this experiment. The **complete** Discovery prefix cannot be
qualified or made available safely through the known immutable parts. This is
an access **blocker**, not a negative measurement of H-DIR-01. Neither a
private Discovery-only view nor `docs/xauusd_directional_view_authority.json`
was created, so the H-DIR runner's separate-environment enforcement has **not
been established**; its missing-authority check still refuses the run.

A future attempt is eligible *only* if an independently authenticated existing
partition/index can provide all **70,834,426** original Discovery rows, each
with `time_msc < 1764563969254`, without opening/decoding held-out quote rows
at any stage. Do not rewrite/regenerate the canonical archive or skip the
50,716 rows inside the mixed part. Any such view would need independent
source-lineage verification, immutable per-part row/time bounds and SHA-256,
a pinned manifest authority separately reviewed in
`docs/xauusd_directional_view_authority.json`, and an isolated H-DIR runner
that has only that view mounted (no archive, held-out data or route to them).
None of those conditions holds now; **do not run the measurement**. A
self-asserted manifest inside a view is not authorization. Even a later
`SURVIVED_DISCOVERY_ONLY` verdict would require a separately governed
out-of-sample design, never Demo orders or strategy promotion here.

**Safety/accounting:** HELD-OUT CLOSED; Demo execution DISABLED; live LOCKED;
orders 0; no strategy; no measured H-DIR-01 outcome. Existing rejections and
volatility magnitude findings are not reopened. No trial-eligibility claim can
be made from the synthetic tests or the NOT RUN access report.
