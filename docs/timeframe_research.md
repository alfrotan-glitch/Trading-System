# Timeframe Research

**Updated:** 2026-09-18
**Decision:** the REAL 15m dataset passes the pre-registered REAL-claims
adequacy gate (provenance, depth, span, freshness, event count) and is
claim-eligible for the registered studies; the resulting impulse conclusion is
`REGIME_DEPENDENT` / `go_block BLOCK` (no promotion). No other timeframe is
claim-eligible in the current checkout.

## Current availability

| Timeframe | Registered data | Current interpretation |
|---|---|---|
| 15m | One REAL Dukascopy tick-derived XAUUSD mid OHLC dataset (`20260918-010+8f120133-1ba57af7`), 26,038 bars, 407 days | REAL-claims adequacy passed (provenance/depth/span/freshness/events); R5 execution-cost data (continuous bid/ask/tick spread) `FAIL`; 407 days is below the 2-year target. |
| 1H | One 500-bar synthetic XAUUSD fixture | Mechanism validation only; blocked for claims by provenance/depth/span. |
| 1m, 5m, 4H, 1D, tick | None in the canonical inventory | `UNAVAILABLE`; do not infer from the 15m or 1H datasets or silently resample as observed data. |

The 15m dataset is tick-derived mid OHLC (mid = (bid+ask)/2) and carries no
continuous bid/ask field, so measured execution-cost evidence remains
`UNAVAILABLE`. The 1H fixture passes its OHLC schema checks but does not provide measured
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

**Next action:** keep the registered REAL 15m history immutable. For any
additional timeframe or multi-timeframe hypothesis, declare the target first,
acquire an independent provenance-qualified history, and test it only under a
new preregistration; do not infer it from the 15m or synthetic 1H records.
