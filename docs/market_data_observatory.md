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

There are **two** canonical dataset versions in this checkout.

**Real, claim-eligible (registered 2026-09-18):**

- `20260918-010+8f120133-1ba57af7`, `XAUUSD`, `15m`, 26,038 UTC mid-price
  OHLC bars built from Dukascopy bid/ask ticks (`mid = (bid + ask) / 2`, with
  per-bar tick counts);
- source `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks`,
  data class `REAL`, checksum `sha256:1ba57af7d9d034d9`;
- range 2025-08-06 00:00 through 2026-09-17 00:00 UTC (close of last bar),
  407.00 days;
- 12/12 quality checks pass; research readiness `READY`; the pre-registered
  impulse adequacy gate passes R1–R4 and R6 (R5 execution-data remains FAIL,
  non-blocking — no continuous spread/tick history in the canonical bars);
- provenance, checksums, gaps, licensing limits, and the exact
  original/processed checksums are recorded in
  `docs/data_provenance_xauusd_dukascopy.md`;
- eligibility: bar-based XAUUSD 15m research **within this window and with
  declared cost assumptions** — not execution-realism or microstructure
  evidence.

**Synthetic, mechanism-only (unchanged):**

- `20260918-010+c83567cb-572728d9`, `XAUUSD`, `1H`, 500 UTC OHLC bars;
- source `SYNTHETIC:fixture:XAUUSD_1H_500.csv`, data class `SYNTHETIC`;
- range 2020-01-01 through 2020-01-21 20:00 UTC, approximately 20.83 days;
- the fixture's 12 quality checks pass;
- bid/ask, ticks, measured spread, broker session hours, real-volume
  semantics, broker artifacts, and execution history are `UNAVAILABLE`;
- eligibility: `MECHANISM_VALIDATION_ONLY`, not real-market claim evidence.

An aggregated 1H series derived from the real 15m bars was exported and
**rejected by the existing ingest quality gate** (276 abnormal intraday gaps
> 2 % of bars). It is not registered; the gate was not weakened. The previous
2,000-row/second-inventory references are retired from current claim-bearing
documentation. Duplicate raw/curated representations are not independent
observations.

Machine-readable exports:

- `data/evidence/data_inventory.json`
- `data/evidence/data_source_audit.json`
- `data/evidence/data_quality_summary.json`
- `data/evidence/historical_depth.json`
- `data/evidence/data_source_catalog.json`

`data_quality_summary.json` and `historical_depth.json` were generated for the
synthetic-fixture era and do not yet include the REAL dataset; the per-dataset
canonical records are `data_inventory.json`, `data_source_audit.json`, and the
research artifacts under `data/evidence/`.

## Requirements and missing evidence

A claim-grade dataset must declare instrument/population, timeframe, horizon,
license/source lineage, timestamp basis, depth/span, quality, session
semantics, and the cost fields needed by the hypothesis. The **real dataset**
satisfies the block-level minimums for bar research:

- provenance class `REAL` (Dukascopy tick-derived), not `SYNTHETIC`;
- 26,038 bars ≥ 5,000-bar minimum;
- 407.00 days ≥ 180-day span minimum;
- 12/12 quality checks pass; no fabrication or interpolation;
- freshness within the 7-day gate at run time.

It still lacks: measured continuous bid/ask/spread (only 23 supplementary
event windows), broker session/fill/latency data, real-volume semantics,
survivorship universe, a license (upstream repository states none), multi-year
regime coverage (2-year target unmet), and second-instrument breadth. The
**synthetic fixture** fails claim readiness on provenance, depth, span, and
cost history and remains mechanism-validation-only.

The source catalog describes possible acquisition paths (including MT5
history/forward capture and external historical providers), but catalog
metadata is not evidence that any source has been acquired or validated. The
registered Dukascopy-lineage dataset was acquired outside that catalog route
(pinned third-party mirror) and is recorded in
`docs/data_provenance_xauusd_dukascopy.md`; the catalog's Dukascopy row
therefore still describes an un-ingested provider-API path and was left
unchanged.

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

1. **What is available?** One REAL 26,038-bar XAUUSD 15m Dukascopy-derived
   dataset (407 days) plus the unchanged 500-bar synthetic 1H fixture.
2. **What is missing?** Continuous bid/ask/spread and broker session semantics,
   licensing, multi-year regime coverage, second-instrument breadth, and
   measured execution reality.
3. **Which sources can fill gaps?** The source catalog is a planning list;
   acquisition and licensing must be recorded before use.
4. **How far back does current data reach?** 407 days for the real dataset
   (below the 2-year regime target); a synthetic fixture spanning ~20.83 days.
5. **Is real execution data present?** No; forward store has zero observations.
6. **Can current data establish cost-sensitive edge?** Only under declared
   assumptions — no continuous measured spread/slippage/latency/fill
   distribution is present (R5-EXECUTION-DATA FAIL).
7. **Can safe forward observation run without capital?** Yes, only through the
   readiness-gated, order-free DEMO_FORWARD collector on a real terminal.
8. **Which hypotheses should be revisited?** Only after acquisition: the
   registered mechanism families can be preregistered against the expanded
   population and regimes.
9. **Which claims are impossible now?** Real-market profitability,
   microstructure/execution edge, broad regime robustness, cross-instrument
   generality, and LIVE readiness.
10. **Decision?** Bar research on XAUUSD 15m is unblocked (the pre-registered
    impulse study returned `REGIME_DEPENDENT` / `BLOCK` — no promotion);
    execution-realism research remains `BLOCKED_INSUFFICIENT_DATA`;
    operational posture `KEEP NO_TRADE`.

**Next action:** keep the registered real dataset immutable, run remaining
pre-registered research against it with unchanged gates, and acquire a
licensed/first-party source with continuous bid/ask for the R5 and execution
research blocks.
