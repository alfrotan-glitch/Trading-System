# XAUUSD historical completeness disposition

**Audit date:** 2026-09-18
**Status:** `AUDIT_COMPLETE_NO_RESEARCH_RERUN`
**Recovery outcome:** **`RECOVERABLE ONLY BY NEW ACQUISITION`**
**Machine evidence:** [`data/evidence/xauusd_completeness_disposition.json`](../data/evidence/xauusd_completeness_disposition.json)
**Recovery-candidate manifest:** [`data/evidence/xauusd_recovery_candidate_manifest.json`](../data/evidence/xauusd_recovery_candidate_manifest.json)

This is a P0 data-integrity disposition. It does not weaken the 2% gate,
rewrite the frozen REAL snapshot, change the locked research partition, reset
trial accounting, rerun the impulse study, search for a strategy, or enable an
execution mode.

## 1. Root cause and complete interval accounting

The pinned upstream snapshot has 14 monthly files and 26,038 15-minute rows.
Its timestamps are unique, strictly increasing, and UTC-normalized. The source
export and QTS-derived exports are byte-for-byte unchanged:

| Artifact | SHA-256 |
|---|---|
| Frozen 15-minute export | `7271892fa9bacf2a4ad20655d6a019020a4aaf057510e769bb42c5ba59d0a074` |
| Frozen 1-hour aggregation | `97b457d6ac42743613a6ee48cf6a02c5fe4475e648fc4c1575003ca5e6c624b0` |

The frozen inventory's `1,493` unexpected slots are preserved exactly. Their
legacy decomposition is:

| Population | Slots | Classification | Disposition |
|---|---:|---|---|
| Recurring daily NY-close / low-liquidity gaps | 1,098 | Source absence / upstream feed policy | Not silently forgiven by QTS; new authoritative acquisition would be needed if bars are required |
| 2025-09-01 and 2026-05-25 afternoon gaps | 28 | Source absence / explicitly documented upstream holiday policy | No QTS loss; acquisition required to replace |
| 2025-12-24/25 and 2025-12-31/2026-01-01 | 213 | Source absence / upstream holiday-closure policy | No QTS loss; acquisition required to replace |
| Upstream rolling refresh/update loss | 154 | Upstream acquisition/update loss | Not QTS ingestion or transformation loss; only part is recoverable from upstream history |
| **Total frozen unexpected population** | **1,493** |  |  |

The frozen legacy closure heuristic treated 58 long closure events as expected.
The current QTS model is deliberately more conservative: it recognizes only 57
weekend-boundary closure events without an explicit session calendar. On the
same frozen source this independently yields 1,785 unexpected slots:

```text
1,785 = 1,098 recurring + 28 documented holiday + 213 Christmas/New Year
      + 292 Easter-period absence + 154 upstream update loss
```

The additional 292 slots are not a reclassification used to obtain PASS. They
are the known Easter-period absence that the upstream policy treats as a
holiday closure but QTS does not forgive without explicit schedule evidence.
The 1,493 frozen figure remains unchanged historical evidence; the current
conservative gate uses 1,785.

There is no evidence of timestamp/UTC normalization loss, QTS ingestion loss,
or QTS aggregation/transformation loss. The `MT5` value in the legacy manifest
is a storage/partition namespace, not an execution venue. The historical source
is Dukascopy-derived and has no MT5 broker execution identity.

## 2. Why the 154-slot upstream category is not QTS loss

The upstream downloader is fail-open for timeout, 404, and LZMA/decode errors.
The rolling updater replaces bars in its refresh window with the newly fetched
result. A timeout or empty response can therefore replace previously present
bars with an incomplete result. Upstream commit `2d3a3dc` explicitly documents
the same timeout-induced silent-gap mechanism and the earlier repair of about
130 gaps.

Comparing the upstream auto-update history shows the relevant bars present in
earlier parquet snapshots and absent after later refreshes. The direct example
is `XAUUSD_2026-09.parquet`: the current pinned `4d6f155` snapshot removed 16
bars on 2026-09-11 relative to `8f01de6`. This proves the failure is upstream
snapshot/update loss, not a QTS transformation loss.

## 3. Recovery result

Earlier immutable upstream parquet snapshots provided authoritative rows for
140 of the 154 slots in the update-loss category. Those rows were materialized
in a separate candidate version, without interpolation, forward-fill,
synthetic values, or modification of the frozen version:

- Candidate version: `20260918-recovery-140-e563c57e`
- Candidate rows: `26,178`
- Candidate CSV SHA-256: `e563c57e7bdee0b1a311c1f88fc9c45311fb24d364866c0aa98600198131b67d`
- QTS candidate checksum: `sha256:7f28bf03bdbb4f90`
- Source: earlier upstream parquet commits, recorded in the candidate manifest
- Candidate quality result: **FAIL**, 1,645 unexpected slots / 27,823 active expected slots = **5.91%**

The remaining 14 slots in that update-loss category were not present in the
inspected historical parquet snapshots. The source-absence populations also
remain unresolved at the raw-feed level. Representative raw Dukascopy endpoint
probes failed with TLS/SSL EOF; no raw ticks were saved, ingested, or used to
claim `NOT RECOVERABLE`. Therefore the overall recovery outcome is
`RECOVERABLE ONLY BY NEW ACQUISITION`, not `RECOVERABLE` and not `NOT
RECOVERABLE`.

The candidate is a new immutable **recovery candidate**, not a replacement:
it is not in the canonical research registry, is not research-eligible, and
cannot unlock the frozen study. The unlicensed upstream source bytes are not
committed to this repository; the candidate hash and source-commit lineage are
committed as its provenance record.

## 4. Gate definition and independent verification

The completeness gate is based on integer-derived active-span coverage, not gap
event count and not a rounded display percentage:

```text
active_span_expected_intervals = observed_bars + unexpected_missing_intervals
active_span_missing_fraction  = unexpected_missing_intervals / active_span_expected_intervals
PASS                          = fraction <= 0.02
```

Recognized closure intervals are excluded only when covered by the default
weekend-boundary policy or explicit schedule evidence. Unknown holidays remain
unexpected. The implementation compares the unrounded fraction; it cannot turn
2.004% into PASS by displaying `2.00%`.

The adversarial fixtures now cover:

- one large missing block;
- many isolated gaps, including 102 isolated omissions across 5,000 nominal slots;
- gaps spanning a weekend/session boundary;
- mixed closure and unexpected gaps;
- exactly 2%: 1 missing of 50 expected, PASS;
- below 2%: PASS;
- above 2%: 1 missing of 49 expected, FAIL;
- zero active-span coverage / empty input, FAIL closed;
- full coverage, PASS.

The direct impulse adequacy API now includes the same blocking
`R0-DATA-COMPLETENESS` check, so a caller cannot bypass the shared 2% policy.

## 5. Dataset lifecycle and research impact

Dataset lifecycle states are explicit and immutable:

```text
ACQUIRED_FROZEN → QUALITY_FAILED → RESEARCH_BLOCKED
                         └──────→ RECOVERY_CANDIDATE → QUALITY_FAILED → RESEARCH_BLOCKED
```

`RESEARCH_ELIGIBLE` is available only to a new immutable version that passes
all applicable quality, provenance, field-semantics, depth, span, and research
requirements. `RETIRED` is terminal. A failed version is never mutated or
promoted by editing an evidence file.

The frozen REAL impulse evidence, locked partition, cumulative trial ledger,
`REGIME_DEPENDENT / BLOCK` status, and `R5=FAIL` limitation are preserved. The
corrected completeness result means the frozen result is historical event-study
evidence and is currently blocked from a fresh real-market claim; the study was
not rerun.

Evidence roles remain separate:

- **Historical source:** Dukascopy-derived upstream XAU/USD feed;
- **Historical execution target/venue:** `null`;
- **MT5:** legacy dataset/storage namespace only for this history;
- **DEMO_FORWARD:** separate broker observation evidence, never relabelled REAL;
- **DEMO_EXECUTION:** `DISABLED BY POLICY`;
- **LIVE:** `LOCKED`;
- **NO_TRADE:** unchanged.

The Windows + MT5 `DEMO_FORWARD` observe-only milestone is **independent of
historical REAL completeness**, because it uses a separate broker/demo
observation path and does not validate or repair the historical dataset. It is
not started by this audit and cannot authorize orders or LIVE.

## 6. Exact disposition and one next milestone

No source bars were acquired from raw Dukascopy during this audit. No frozen
artifact was rewritten. No research or execution was rerun.

**The one next milestone is:** run the existing Windows + MT5
`DEMO_FORWARD`/observe-only protocol with zero orders, after the operator
completes its separate readiness and safety checks. This remains an observation
milestone only; it does not promote the historical candidate, enable
`DEMO_EXECUTION`, or unlock `LIVE`.

See [`docs/research_integrity_audit.md`](research_integrity_audit.md) for the
verification record and artifact policy.
