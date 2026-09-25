# Data Source Audit

**Updated:** 2026-09-18
**Canonical machine evidence:** `data/evidence/data_source_audit.json`
**Additional provenance record:** `docs/data_provenance_xauusd_dukascopy.md`
**Audit status:** the checked-in JSON is a derived acquisition-era snapshot;
`src/qts/data/audit.py` and `src/qts/data/quality.py` now emit explicit role and
gap populations. The snapshot is retained for lineage and is not a current
quality certificate.

## Audited sources

The frozen inventory artifact records two dataset entries. It is retained for
acquisition/research lineage; the current code treats manifests and the
canonical store as primary and does not treat this snapshot as a current quality
certificate.

### 1. REAL acquired dataset (current completeness blocked)

- version `20260918-010+8f120133-1ba57af7`;
- `XAUUSD` / `15m`, 26,038 UTC mid-price OHLC bars, span 407.00 days
  (2025-08-06 00:00 → 2026-09-17 00:00 UTC close of last bar);
- source `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks`,
  class `REAL` — Dukascopy XAU/USD tick-derived 15-minute mid bars
  (`mid = (bid + ask) / 2`, per-bar tick counts), pinned upstream commit
  `4d6f15543e6285fad91fd57fe42f716bc7273075`, no upstream license;
- frozen acquisition snapshot: **12/12 pass** under the previous
  event-count-only gap check;
- current audited gap status: **FAIL for quality completeness**. The frozen
  inventory's legacy count is 1,493 unexpected missing 15m intervals (5.42%),
  while the current weekend-boundary-only recomputation is 1,785 intervals
  (6.42% of 27,823 active expected intervals), both above the unchanged 2%
  threshold. The pre-registered impulse artifact and its original adequacy
  record remain frozen historical evidence; no rerun was performed. The full
  root-cause and recovery disposition is in
  `docs/data_completeness_disposition.md`.
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

The frozen research run treated the real dataset as eligible for bar-based
research on XAUUSD 15m within its declared window and cost assumptions, but the
current audited completeness result is **FAIL** and blocks a current quality
PASS. It is **not** execution-realism evidence: there is no continuous
spread/tick history, no broker session metadata, and derivations rest on a
third-party mirror without a license. The preserved research conclusion must
stay regime- and window-conditional (the pre-registered impulse study returned
`REGIME_DEPENDENT` / `BLOCK`); no rerun or promotion occurred.

The synthetic fixture supports only labelled mechanism validation.

## Planned expansion

Continue to improve, without weakening any gate:

- a licensed or first-party source for the same instrument with continuous
  bid/ask and broker session semantics (fills, latency, spreads);
- longer history (the 2-year regime target is not met by 407 days);
- cross-instrument coverage (e.g. EURUSD/BTC) for generality claims;
- forward observation of real broker quotes through the order-free DEMO_FORWARD
  protocol (no real session is present in the current canonical store) to replace
  declared cost assumptions with measurements.

The provider catalog is an acquisition plan, not evidence of availability or
quality.

**Never substitute:** synthetic, paper, shadow, demo, imputed, estimated, or
model-derived values for claim-eligible market observations.
