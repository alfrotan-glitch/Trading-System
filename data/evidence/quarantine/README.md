# Quarantined Evidence — NOT valid market or execution evidence

Nothing in this directory may be cited as current real-market evidence,
used to satisfy a forward-evidence gate, or displayed as DEMO execution
reality.

## demo_forward_observations.json (quarantined 2026-09-17)

Violations found during the evidence-integrity audit:

1. **Fabricated execution metrics** — every "demo_fill" record carries
   `slippage_bps: 2.5` and `latency_ms: 120` (constant synthetic values),
   and `actual_price` differs from `requested_price` by exactly +0.05 on
   every record. No real broker produced these; no order was ever sent.
2. **Fabricated broker state** — `broker_response: "FILLED"` with fills and
   P&L for orders that were never submitted (`order_send` was never called).
3. **Wrong symbol lineage** — records say `XAUUSD`; the verified broker
   symbol is `XAUUSD@`.
4. **Stale price regime** — prices cluster near 2000 (Jan-2020 fixture
   territory), inconsistent with any live session at generation time.
5. **False provenance** — records are labeled `source=REAL DEMO` despite
   being synthetic; under the provenance model they are UNVERIFIED at best.

Under the canonical provenance model these records are classified
**UNVERIFIED / FABRICATED-ORIGIN** and are excluded from every claim.

Replacement: real observations live in the canonical SQLite observation
store (`data/sqlite/forward_observatory.db`) written by the readiness-gated
OBSERVE-ONLY collector with explicit provenance, session identity, and
timestamp lineage. JSON files under `data/evidence/` are derived exports
only.
