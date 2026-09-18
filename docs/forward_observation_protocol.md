# Forward Observation Protocol

Updated 2026-09-18. **Observation only; DEMO execution disabled, LIVE locked.**

## Current objective

The next phase is **FO-R1: research-grade market observation**, not strategy execution or simulated fills. Its design, launch scope, quality criteria and research handoff are specified in:

- [Current state and research roadmap](current_state.md)
- [FO-R1 research observation plan](forward_observation_research_plan.md)
- [Current FO-R1 boundary status](forward_observation_status.md)
- [Hardened evidence-verification boundary](session_evidence_verification_boundary.md)
- [Raw-evidence history hygiene](session_evidence_history_hygiene.md)
- [Canonical authorities](canonical_authorities.md)

The FO-R1 **engineering boundary is hardened**: collision-safe append-only storage,
durable acquisition accounting, research snapshot support, integrity checks and
bounded publication are implemented. FO-R1 is not yet a completed real-market
observation campaign: no real Windows/MT5 session is present in repository
evidence, and the operator must still run the readiness-gated order-free
protocol. The research-plan document retains its historical design checklist;
this page and `forward_observation_status.md` state what is closed today.

## Existing real-source observation path

`POST /api/observe/start` (Desktop: **Start Observation (No Orders)**) requires a fresh passing 14-check readiness report. The collector polls:

```text
MT5Adapter.ticks → MarketDataProvider.get_tick
  → ObservationTick → ForwardObservatory canonical SQLite store
```

The collector is structurally order-free and safety-tested. Readiness does **not** enable DEMO execution. No execution engine, order submission or promotion step is needed to collect quotes. Invalid/stale/future/out-of-contract ticks are refused under the existing validation rules; do not weaken those rules for coverage.

The current readiness path requires a demo account, so genuine broker-sourced observations carry **DEMO provenance**, not REAL-account provenance. Calling these real market observations does not justify relabelling them REAL, switching to a funded account or claiming they reproduce every live-account quote.

This is latest-quote polling at a default requested interval of 1 s, **not complete broker tick capture**. Actual cadence includes processing time. Duplicate standing quotes are skipped. No trading signal, NO_TRADE signal record, hypothetical order, hypothetical fill, simulated slippage or submission/ack latency belongs in FO-R1. Quote age and processing duration are not execution latency.

## Canonical storage and derived evidence

Canonical source: `data/sqlite/forward_observatory.db`, with `observation_ticks`, `observation_sessions` and an empty-for-this-phase `observation_signals` table. Full quote payloads and session identity are stored here. Derived manifests such as `data/evidence/forward_observation_manifest.json` are regenerable views, not primary evidence or completeness certificates.

`ForwardObservatory.simulate_observation(...)` is for testing only. Its SYNTHETIC observations never count as forward market evidence. Other legacy paper/shadow/simulation schemas do not expand this phase's zero-signal, zero-order scope.

## Session audit transfer

On the Desktop that owns the observation store:

```bat
qts evidence export-session <session-id>
REM default output: data/evidence/exports/<session-id>.session_evidence.json
```

The v1 artifact contains session metadata, source-store declarations, selected projections of all exported rows, per-row SHA-256 values, an ordered chain and default first/last five full samples. Session metadata is allowlist-sanitized. Full payloads and prices for nonsampled rows are **not included**, and full samples/prices/metadata are **not hash-bound by the row chain**.

Verify a privately transferred artifact with:

```sh
qts evidence verify path/to/session.session_evidence.json
```

The hardened verifier derives available summaries from rows, checks duplicated representations, binds endpoint samples to their rows and refuses observable contradictions. It does not mutate the input.

### Four evidence boundaries

1. **Internal structural consistency:** independently checkable from exported fields.
2. **Canonical-store facts:** the exporter queries its SQLite source, but an artifact-only auditor has not inspected that database. Integrity, table inventory, signals and omitted original raw-stamp pairs remain declarations at this boundary.
3. **Desktop/MT5 physical origin:** operator-attested, not authenticated by a path, version label or unsigned hash chain.
4. **Unsupported claims:** complete tick capture, absence of lost/overwritten records, dropped-duplicate counts not included in the artifact, accurate clocks, broker-wide zero orders, true prices or an economic edge are not proved by `CONSISTENT`.

The hash chain detects inconsistencies relative to its supplied root; it cannot detect a fully rewritten self-consistent file without an independent trust anchor. Exported monotonicity does not establish arrival-order monotonicity because the exporter sorts rows.

A private, complete, independently verifiable research snapshot plus durable
acquisition diagnostics is a **separate versioned contract** from the v1 audit
artifact. Snapshot support and the acquisition ledger are implemented in the
repository, but no real observation session has been captured or independently
reviewed here. Do not extend v1 ad hoc; preserve compatibility and use the
versioned research-snapshot contract.

## Transfer and safety policy

Review exports for data-policy compliance even when metadata is sanitized. Transfer raw evidence only through an access-controlled channel outside Git. `*.session_evidence.json` is ignored repository-wide; neither this ignore rule nor normal file deletion guarantees removal from existing public Git history/caches.

No export, verification result, dataset-size milestone or research finding enables trading. **DEMO remains disabled; LIVE remains locked; all existing execution and risk gates remain in force.**
