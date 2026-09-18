# Market Data Observatory

**Updated:** 2026-09-18
**Decision:** `KEEP NO_TRADE`; acquire claim-eligible data before interpreting
strategy results.

## Purpose

The observatory answers what data is present, what is missing, which source
claims are supportable, how far history extends, and how forward observations
can be collected without risking capital. It separates source facts from
research conclusions and never turns a proxy into a broker measurement.

## Canonical architecture

- `src/qts/data/provider.py`: provider → raw preservation → validation →
  normalization → canonical manifest.
- `src/qts/data/inventory.py` and `data/evidence/data_inventory.json`:
  one row per canonical dataset version.
- `src/qts/data/quality.py`: strict OHLC/timestamp/invariant checks.
- `src/qts/observability/forward_observatory.py`: one append-only SQLite store
  for DEMO_FORWARD observation sessions and provenance.
- `src/qts/execution/demo_comparison.py`: paper/shadow event alignment;
  DEMO execution metrics are unavailable because DEMO_EXECUTION is disabled.
- Derived JSON exports are inspection artifacts, not primary evidence stores.

## Current canonical inventory

There is **one** canonical dataset version in this checkout:

- `20260918-010-572728d9`, `XAUUSD`, `1H`, 500 UTC OHLC bars;
- source `SYNTHETIC:fixture:XAUUSD_1H_500.csv`, data class `SYNTHETIC`;
- range 2020-01-01 through 2020-01-21 20:00 UTC, approximately 20.83 days;
- the fixture's 12 quality checks pass;
- bid/ask, ticks, measured spread, broker session hours, real-volume
  semantics, broker artifacts, and execution history are `UNAVAILABLE`;
- eligibility: `MECHANISM_VALIDATION_ONLY`, not real-market claim evidence.

The previous 2,000-row/second-inventory references are retired from current
claim-bearing documentation. Duplicate raw/curated representations are not
independent observations.

Machine-readable exports:

- `data/evidence/data_inventory.json`
- `data/evidence/data_source_audit.json`
- `data/evidence/data_quality_summary.json`
- `data/evidence/historical_depth.json`
- `data/evidence/data_source_catalog.json`

## Requirements and missing evidence

A claim-grade dataset must declare instrument/population, timeframe, horizon,
license/source lineage, timestamp basis, depth/span, quality, session
semantics, and the cost fields needed by the hypothesis. The current fixture
fails claim readiness because:

- provenance is `SYNTHETIC`, not `REAL`, `HISTORICAL`, or `BROKER-DERIVED`;
- 500 bars is below the 5,000-bar research minimum;
- 20.83 days is below the 180-day span minimum;
- there is no measured bid/ask or execution-cost history;
- one instrument/timeframe cannot support broad population or regime claims.

The source catalog describes possible acquisition paths (including MT5
history/forward capture and external historical providers), but catalog
metadata is not evidence that any source has been acquired or validated.

## Forward observation boundary

`ForwardObservatory` writes sessions, ticks, and signals to
`data/sqlite/forward_observatory.db`. `data/evidence/forward_observation_manifest.json`
is only a derived export. Current store state is zero active sessions, zero
ticks/signals, and zero real-market ticks.

`DEMO_FORWARD/OBSERVE_ONLY` may record real MT5 demo-account market data after
fresh readiness checks. The collector has no order path. `DEMO_EXECUTION` is
disabled by policy, so no fill, slippage, latency, account, reconciliation,
P&L, or execution-comparison value is inferred from observation readiness.

## Quality, versioning, and locking

Dataset changes create a new immutable version/checksum. Raw inputs remain
preserved and synthetic provenance remains explicit. Timestamp and future/stale
checks are fail-closed. Research locks discovery/validation partitions and
records access attempts. Non-finite stress results are invalid blocking
measurements, never favorable sentinels.

## Research decision — ten questions

1. **What is available?** One 500-bar synthetic XAUUSD 1H fixture.
2. **What is missing?** Claim-eligible history, depth/span, population breadth,
   broker/session semantics, bid/ask/ticks, and measured costs.
3. **Which sources can fill gaps?** The source catalog is a planning list;
   acquisition and licensing must be recorded before use.
4. **How far back does current data reach?** About 20.83 days; insufficient for
   the declared 180-day minimum.
5. **Is real execution data present?** No; forward store has zero observations.
6. **Can current data establish cost-sensitive edge?** No measured spread,
   slippage, latency, or fill distribution is present.
7. **Can safe forward observation run without capital?** Yes, only through the
   readiness-gated, order-free DEMO_FORWARD collector on a real terminal.
8. **Which hypotheses should be revisited?** Only after acquisition: the
   registered mechanism families can be preregistered against the expanded
   population and regimes.
9. **Which claims are impossible now?** Real-market profitability,
   microstructure/execution edge, broad regime robustness, and LIVE readiness.
10. **Decision?** `BLOCKED_INSUFFICIENT_DATA` / `KEEP NO_TRADE`.

**Next action:** acquire and register provenance-qualified history, then
regenerate the complete evidence bundle from that single canonical source.
