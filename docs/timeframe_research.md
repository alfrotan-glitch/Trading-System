# Timeframe Research

**Updated:** 2026-09-18
**Decision:** no timeframe is claim-eligible in the current checkout.

## Current availability

| Timeframe | Registered data | Current interpretation |
|---|---|---|
| 1H | One 500-bar synthetic XAUUSD fixture | Mechanism validation only; blocked for claims by provenance/depth/span. |
| 1m, 5m, 15m, 4H, 1D, tick | None in the canonical inventory | `UNAVAILABLE`; do not infer from the 1H fixture or silently resample as observed data. |

The 1H fixture passes its OHLC schema checks but does not provide measured
bid/ask, tick, broker session, or execution-cost evidence. A resampled series
would be a new synthetic/model-derived artifact and would not become real
higher/lower timeframe data.

## Eligibility contract

A timeframe is **eligible only if quality sufficient**: a multi-timeframe or timeframe-specific hypothesis must have an independent,
provenance-bound dataset for every timeframe it uses. Each version must pass
timestamp/quality checks and meet the declared depth/span/population contract.
Cost-sensitive claims also require measured bid/ask/tick or explicitly declared
model assumptions that are not mistaken for observations.

## Acquisition plan

Acquire and license the requested timeframe from a declared provider, preserve
the raw source and checksum, ingest through `DataProvider`, validate it, create
an immutable manifest, and regenerate inventory/source-audit/readiness evidence.
The provider catalog is a plan only; no catalog row is proof of acquisition.

**Next action:** declare the target hypothesis timeframe and acquire its
provenance-qualified history before testing timeframe or multi-timeframe edge.
