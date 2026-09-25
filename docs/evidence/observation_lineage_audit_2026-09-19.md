# Existing MT5 observation lineage audit — 2026-09-19

## Decision

Do **not** automatically schedule another FO-R1 run. The existing manifest was
audited first. It is useful engineering evidence and a bounded DEMO quote
observation, but it does not close R5 and is not currently independently
re-verifiable from this repository.

## What is present

`data/evidence/forward_observation_manifest.json` describes session `FS-f374b6`:

- DEMO / OBSERVE_ONLY / `XAUUSD@`
- 2026-09-18 13:56:27.342045Z through 19:41:21.015311Z
- 13,222 recorded ticks; 615 duplicates skipped
- 0 signals, 0 orders, no execution path, no realized PnL
- one reported server offset of +10,800 seconds
- one timestamp basis: `broker-normalized(measured-m1-bar)`
- spread summary: min 0.4591, average 0.5670, max 1.1944 bps
- termination: `ENDED_ON_ERRORS`, due to stale tick age 35.1 seconds versus a 5-second limit

The manifest is a derived JSON export. It names
`data\\sqlite\\forward_observatory.db` as the canonical store, but that
machine-local database is not present here. No corresponding committed
`session_evidence.json`, `research_snapshot.json`, acquisition ledger, or
verifier-result artifact for `FS-f374b6` was found.

## What this proves

Subject to the artifact's own declarations, it supports that a prior
observe-only DEMO pipeline recorded real-time-looking MT5 observations for
`XAUUSD@`, measured a nonzero spread sample, submitted no orders, and stopped
fail-closed on stale data. It is useful evidence of pipeline operation and a
realistic quote/spread observation window.

It does **not** prove source-store integrity, Desktop origin, complete
collection, absence of dropped ticks, clock accuracy, broker schedule
semantics, latency, order acceptance, fills, slippage, market impact, or
execution profitability. It cannot establish R5 because there are no realized
fills or controlled execution observations. The `ENDED_ON_ERRORS` terminal
condition also means it is not a clean complete session.

The timestamp basis is more specific than a generic UTC fallback, but it is a
pipeline normalization declaration, not independent proof of broker clock
accuracy. MetaQuotes UTC documentation establishes the MT5 returned-data basis;
it does not authenticate this export or prove the broker's session clock.

## Re-verification result

Re-verification under the current hardened verifier cannot be performed for
`FS-f374b6` from this checkout: the required session artifact and canonical
SQLite store are absent. The manifest alone is not the v1 session-evidence
contract accepted by `verify_session_export`, and it contains no row hash chain,
source-store integrity declaration, sample correspondence set, or verifier
result. No historical file was rewritten or repaired.

The historical manifest is therefore preserved as **bounded historical
observation evidence, not R5-authoritative evidence**. Its refusal reason is
absence of the independently verifiable evidence layer and its terminal stale-
data failure, not evidence that the observations were fabricated.

## Does it define the next experiment?

Yes, at the design level: it identifies the exact failure mode to measure
(staleness/continuity) and demonstrates that quote spread can be observed while
orders remain unreachable. It does not supply the acceptance data for R5.

The next milestone is **lineage recovery / verification**, not an automatic
new observation:

1. On the operator machine, locate the original `FS-f374b6` v1 session export,
   research snapshot, canonical DB, and acquisition ledger.
2. Copy only bounded derived artifacts into the repository's evidence boundary;
   do not upload the raw database or rewrite the historical export.
3. Run the current read-only `verify_session_export` and, if applicable,
   `verify_research_snapshot_file`. Record the exact verdict and file hashes.
4. If verification passes, use the session for pipeline-health and spread
   context, while still keeping R5 FAIL because no fills/slippage/latency
   experiment exists.
5. If artifacts are missing or refused, preserve this manifest as historical
   evidence and run only the minimum new observe-only session required by a
   preregistered R5 experiment: quote continuity/freshness, measured collection
   latency, and explicitly defined cost observations. No strategy search or
   capital exposure follows either outcome.

This decision keeps zero-capital safety and all existing research gates intact.
