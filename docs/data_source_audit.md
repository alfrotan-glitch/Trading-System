# Data Source Audit

**Updated:** 2026-09-18
**Canonical machine evidence:** `data/evidence/data_source_audit.json`
**Additional provenance record:** `docs/data_provenance_xauusd_dukascopy.md`

## Audited sources

The canonical inventory now contains two registered datasets.

### 1. Real dataset (claim-eligible)

- version `20260918-010+8f120133-1ba57af7`;
- `XAUUSD` / `15m`, 26,038 UTC mid-price OHLC bars, span 407.00 days
  (2025-08-06 00:00 → 2026-09-17 00:00 UTC close of last bar);
- source `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks`,
  class `REAL` — Dukascopy XAU/USD tick-derived 15-minute mid bars
  (`mid = (bid + ask) / 2`, per-bar tick counts), pinned upstream commit
  `4d6f15543e6285fad91fd57fe42f716bc7273075`, no upstream license;
- quality checks: **12/12 pass**;
- research readiness: **READY** (class REAL, rows ≥ 5,000, span ≥ 180 days,
  quality passed); the pre-registered impulse adequacy gate passes R1–R4 and R6;
- tick, continuous bid/ask, measured spread, broker session/fill metadata,
  real-volume semantics, licensing metadata, survivorship universe, and
  execution history: `UNAVAILABLE` in the canonical bars.
  A supplementary file of 23 event-window bid/ask spreads (median 1.73 bps)
  exists as evidence (`data/evidence/xauusd_event_spread_evidence.json`) but is
  event-selected and does not change R5.

### 2. Synthetic fixture (mechanism validation only)

- version `20260918-010+c83567cb-572728d9`;
- `XAUUSD` / `1H`, 500 UTC OHLC bars, approximately 20.83 days;
- source `SYNTHETIC:fixture:XAUUSD_1H_500.csv`, class `SYNTHETIC`;
- fixture quality checks pass; real-market claim eligibility remains blocked
  (synthetic provenance, depth < 5,000 bars, span < 180 days).

The audit is derived from canonical manifests, bars and quality checks. It does
not invent a provider, treat high-low as spread, or use source-catalog claims as
acquired data. Raw broker Desktop evidence is not present in this checkout.

## Claim consequence

The real dataset is claim-eligible for bar-based research on XAUUSD 15m within
its declared window and for the cost assumptions it declares. It is **not**
execution-realism evidence: there is no continuous spread/tick history, no
broker session metadata, and derivations rest on a third-party mirror without a
license. Research conclusions must stay regime- and window-conditional
(the pre-registered impulse study returned `REGIME_DEPENDENT` / `BLOCK`).

The synthetic fixture supports only labelled mechanism validation.

## Planned expansion

Continue to improve, without weakening any gate:

- a licensed or first-party source for the same instrument with continuous
  bid/ask and broker session semantics (fills, latency, spreads);
- longer history (the 2-year regime target is not met by 407 days);
- cross-instrument coverage (e.g. EURUSD/BTC) for generality claims;
- forward observation of real broker quotes (already available as DEMO_FORWARD
  with zero orders) to replace declared cost assumptions with measurements.

The provider catalog is an acquisition plan, not evidence of availability or
quality.

**Never substitute:** synthetic, paper, shadow, demo, imputed, estimated, or
model-derived values for claim-eligible market observations.
