# Session evidence v1: verification boundary and hardening

Review date: 2026-09-18. No trading advancement is authorized by this work.

## Four distinct evidence layers

1. **Artifact-internal structure.** The verifier recomputes row digests, the ordered chain and every summary derivable from the exported rows. It cross-checks repeated representations and available endpoint payloads. `CONSISTENT` means those checks passed, not authenticity or complete runtime evidence.
2. **Canonical Desktop SQLite store.** The exporter queries the observation store and emits declarations about its integrity, tables, signals and original raw stamp pairs. An auditor with only the artifact has not queried that database. Comparing those declarations to each other is not independently verifying the source store, accessor columns or database contents.
3. **Operator-attested origin.** The file's physical Desktop/MT5 origin remains an operator attestation. Paths, code-version labels and DEMO/REAL labels are not authenticated identity proofs. This Desktop-supplied artifact has **DEMO-labelled rows**, not REAL-labelled rows.
4. **Unsupported claims.** v1 cannot prove collection completeness, dropped duplicates, collection failure counts, exact full-store duplicate keys, actual broker orders, clock accuracy, or trading eligibility. Full original `(mt5_time_msc, mt5_time)` pairs and full payloads are omitted for nonsampled ticks. Prices, full samples and metadata are outside the row hash chain. Anyone can rewrite the file and recompute the unsigned chain; no external trust anchor or signature is supplied.

All verdicts, including unreadable/malformed-file refusals, carry these limits. Verification has no connection to execution permission and never promotes observation evidence to eligibility.

## Weaknesses found and fixes

| Weakness | Hardening |
|---|---|
| Provenance totals could say `REAL: 1` while rows contained 1,327 DEMO observations. Other duplicated summaries could also lie. | Recompute provenance histogram, symbols, timestamp-basis histogram, offsets, first/last event times and monotonicity from rows. Compare every duplicated summary exactly. Counter types are strict nonnegative integers, not booleans or floats. Returned provenance totals are derived, not aliases of input counters. |
| Contamination/symbol/basis checks trusted summaries instead of examining every row. | Check every row, including nonsampled rows with correctly recomputed digests. Reject disallowed provenance, symbol drift, unknown normalization bases and invalid offsets. UTC fallback must use zero offset. |
| Monotonicity relied on a declared zero. | Parse aware timestamps and compare actual instants, not lexicographic ISO strings; reject real regressions, even with valid hashes and a declared zero. |
| Distinct/duplicate counts could contradict the row count. | Check count algebra, reject declared stored duplicates and repeated observable exported stamp pairs; check available original sample stamp pairs. Do **not** claim reconstruction of omitted full-store raw keys. Repeated whole-second stamps alone are not treated as duplicate ticks. |
| Samples were checked only for symbol/provenance membership, not for correspondence to endpoint rows. | Match each sample to its position and every projected field, including both timestamps, raw time, offset, basis, provenance and symbol; check session identity, cardinality, ordering, overlapping payload agreement and duplicate sample IDs. |
| Nested sample timestamp provenance could disagree with the sample and row. | Cross-check raw seconds/milliseconds, offset, broker symbol and basis; recompute normalization using the adapter's real timestamp-selection rules. Validate adapter receipt time does not follow observation receipt. |
| Sample prices could contradict their own midpoint/spread. | Validate finite decimal values and available bid/ask, midpoint and spread arithmetic. This is arithmetic consistency, **not** a claim that prices are authenticated or hash-bound. |
| Order-free fields could contradict metadata/counter fields, and hidden order tables could be declared in the inventory. | Require both order-possible flags to be strictly false; both signal counters to agree and equal zero; order-table summary to match the declared inventory and be empty. Validate required observation tables and the integrity declaration. These remain declarations, not evidence from a database read. |
| Session lifecycle declarations were not cross-checked. | Check status, start/end/export chronology, matching nested lifecycle timestamps, receipt-time bounds, ACTIVE terminal-field absence and ENDED/error contradictions. Do not require broker events to start after collection begins or pretend remote and local clocks are identical. |
| `samples += last` mutated the caller's first-sample list. | No input mutation; verification is repeatable and output summaries are independently constructed. Test both positive and refused calls. |
| Missing/wrong nested shapes could pass or raise exceptions; bool-as-int, NaN/Infinity and duplicate JSON keys were not handled safely. | Strict v1 object shapes, required fields, container/scalar types, aware timestamps and finite numbers. Duplicate JSON keys rejected at file load. Malformed input, JSON cycles, decimal overflow and read failures become `REFUSED`; CLI exits 1. No permissive default values substitute for absent required sections. |
| Hash descriptors could advertise a different algorithm or claim wider coverage. | Enforce v1's SHA-256 algorithm and canonical row/chain descriptors; require indexed canonical row fields and the exact ordered root. Reject unknown structural fields rather than silently accepting contradictory extensions. |
| Sanitization checked only string-valued credential keys. | Enforce credential redaction regardless of value type, login masking, unknown-metadata redaction and agreement with `meta_redacted_keys`. |
| Documentation implied all counters/source-store checks were independently verified. | Narrow module documentation and every verdict to the actual observable boundary above. No claim of source-store access or authenticated runtime origin. |

The verifier refuses on the first concrete violation. It does not silently repair artifacts, substitute summaries, rehash submitted rows, normalize contradictory copies or grant a partial pass.

## Compatibility and positive paths

The format remains `qts.session_evidence.v1`; existing Desktop bytes are not rewritten. The original supplied artifact was re-read from the upload commit **in memory**, reverified as `CONSISTENT` under the hardened implementation, and checked for no mutation. No raw fixture was added to the repository.

- Artifact: `FS-5a9542.session_evidence.json`
- File SHA-256: `61ba66e9e36ac04221ae4e2615e740d3758999eb52e6d885d894dd669782145c`
- Recheck: 1,327 rows, all DEMO-labelled; zero reported violations.
- Original four probe types now return `REFUSED`: false provenance counter, contradictory sample timestamp, contradictory order flag and contradictory signal counter.

Positive coverage includes empty and short sessions, ACTIVE/ENDED/ENDED_ON_ERRORS sessions, configurable endpoint counts including overlapping endpoints and legacy zero-count behavior, mixed DEMO/REAL labels with matching summaries, canonical/broker symbol aliases, sanitized metadata, timezone-equivalent event ordering, and adapter timestamp fallbacks (seconds-only, absent/zero millisecond stamps, milliseconds-only and raw time supplied in milliseconds). No automatic refusal is based on negative event-to-receipt latency, which can reflect clock skew.

The old synthetic test helper had its own 7 ms contradiction: `mt5_time_msc = base*1000 + 7` but `broker_event_time = base - offset`. The helper now uses `base - offset + 0.007`; a dedicated negative test proves the old mismatch is refused. This corrects test data rather than weakening timestamp verification.

## Regression validation

`tests/test_session_evidence_export.py` contains 190 cases (14 original plus 176 added cases), including parameterized adversarial cases. Semantic row probes independently recompute their own SHA-256 values and chain so failures cannot be attributed only to stale checksums.

Commands:

```sh
pytest
ruff check src tests
ruff format --check src tests
mypy src/qts
bandit -q -r src/qts -c pyproject.toml
```

Final validation: **707 passed, 17 skipped**, with two dependency deprecation warnings. Ruff check, Ruff format check, mypy (110 source files), and Bandit all passed. The sandbox DEMO authority reported `DISABLED` / `execution_permitted=false`; LIVE readiness reported `ready=false`. These are sandbox observations, not an inspection of the operator's Desktop state.

The full Python suite and existing safety-boundary tests remain the release checks. Optional environment-dependent skips do not constitute Desktop/MT5 runtime proof. No execution implementation, gate, config, risk authority, confirmation, acknowledgement or LIVE lock is changed by this patch.
