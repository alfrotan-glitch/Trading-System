# Data Source Audit

**Updated:** 2026-09-18
**Canonical machine evidence:** `data/evidence/data_source_audit.json`

## Audited source

The current canonical inventory contains one registered dataset:

- version `20260918-010-572728d9`;
- `XAUUSD` / `1H`, 500 UTC OHLC bars, approximately 20.83 days;
- source `SYNTHETIC:fixture:XAUUSD_1H_500.csv`, class `SYNTHETIC`;
- fixture quality checks pass;
- tick, bid/ask, measured spread, broker session/fill metadata, real-volume
  semantics, licensing metadata, survivorship universe, and execution history:
  `UNAVAILABLE`.

The source audit is derived from canonical manifests and bars. It does not
invent a provider, treat high-low as spread, or use source-catalog claims as
acquired data. Raw broker Desktop evidence is not present in this checkout.

## Claim consequence

The dataset is suitable only for labelled mechanism validation. Research
readiness blocks real-market claims because the source class is synthetic,
depth is below 5,000 bars, and span is below 180 days. No cross-instrument or
regime generalization is supportable.

## Planned expansion

Acquire provenance-qualified, licensed history with declared instrument,
population, timeframe, horizon, session/timestamp basis, bid/ask/tick/cost
fields, and enough depth/span. Preserve raw bytes and checksum, ingest through
the canonical pipeline, then regenerate all evidence. The provider catalog is
an acquisition plan, not evidence of availability or quality.

**Never substitute:** synthetic, paper, shadow, demo, imputed, estimated, or
model-derived values for claim-eligible market observations.
