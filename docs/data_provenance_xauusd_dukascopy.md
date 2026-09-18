# Provenance — XAUUSD 15m Dukascopy-Derived Mid History (vudo805 mirror)

**Updated:** 2026-09-18
**Machine evidence:** `data/evidence/xauusd_dukascopy_acquisition.json`,
`data/evidence/xauusd_event_spread_evidence.json`,
`data/evidence/data_inventory.json`, `data/evidence/data_source_audit.json`
**Acquisition script:** `scripts/acquire_xauusd_dukascopy.py`

This document is the provenance record for the first REAL, claim-eligible dataset
registered in QTS. It states what the bytes are, where they came from, how they
were verified, and what they do **not** support. Nothing here is a broker
measurement and nothing here overrides an existing gate.

## 1. Source and lineage

- **Upstream repository:** `vudo805/forex-price-simulator`
- **Pinned commit:** `4d6f15543e6285fad91fd57fe42f716bc7273075` (committed
  2026-09-18T08:05:21+00:00, "Auto-update XAUUSD candle data")
- **Source path:** `data/XAUUSD/XAUUSD_<YYYY-MM>.parquet` (14 monthly files, ~69 MB)
- **Upstream feed:** Dukascopy **XAU/USD** tick data (`datafeed.dukascopy.com`,
  20-byte `>iiiff` records, `POINT_VALUE` XAUUSD = 1000) fetched by the upstream
  project's downloader (`scripts/dukascopy_downloader.py`,
  `.github/workflows/update-data.yml`, daily 03:00 UTC cron, `LAG_DAYS = 2`,
  refresh window 5 days).
- **Upstream transform:** 15-minute **mid-price OHLC** bars built from real
  bid/ask ticks — `mid = (bid + ask) / 2` — plus the integer tick count per bar.
  The dataset is therefore **tick-derived**, not synthetic and not ordinary
  vendor OHLC.
- **Instrument identity:** XAU/USD spot gold (CFD quote), USD per troy ounce.
- **Venue field in QTS:** `MT5` — the system's trading-venue namespace
  (the existing synthetic fixture is registered the same way). It is **not** a
  claim that these bars were captured from an MT5 broker; the actual feed is
  recorded in the manifest `source` label:
  `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks`.

## 2. Registered dataset

| Field | Value |
|---|---|
| Version | `20260918-010+8f120133-1ba57af7` |
| Dataset checksum (processed) | `sha256:1ba57af7d9d034d9` |
| Instrument / venue / timeframe | XAUUSD / MT5 (namespace) / 15m |
| Bars | 26,038 |
| Range (UTC bar opens) | 2025-08-06 00:00 → 2026-09-16 23:45 (last close 2026-09-17 00:00) |
| Span | 407.00 days |
| Provenance class | `REAL` |
| Ingest input (gitignored raw) | `data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv` sha256 `7271892fa9bacf2a…` |
| Curated store | `data/curated/instrument=XAUUSD/venue=MT5/timeframe=15m/version=<version>/part-0.parquet` |

Per-bar semantics: `time` = UTC bar **open**; `close_time` = open + 900 s
(inferred by the existing ingest path); `open/high/low/close` = mid prices;
`volume` = **tick count** (not broker volume, not lot volume).

Missing observations stay missing. There is no interpolation, no forward-fill,
no synthetic bar and no substituted price anywhere in the ingest path
(`scripts/acquire_xauusd_dukascopy.py` refuses on NaN, duplicates,
non-monotonic timestamps, negative tick counts, or any hash mismatch).

## 3. Original and processed checksums

All 14 source parquet files are pinned by SHA-256 in
`scripts/acquire_xauusd_dukascopy.py`; any byte change is a different dataset
and is refused. A fresh `git clone https://github.com/vudo805/forex-price-simulator`
was re-verified against the pin on 2026-09-18 (HEAD `4d6f155…`, 14 files):

| File | SHA-256 (prefix) |
|---|---|
| XAUUSD_2025-08.parquet | `e650d23cc05194ec…` |
| XAUUSD_2025-09.parquet | `48f7e1d2f5fd2f94…` |
| XAUUSD_2025-10.parquet | `4533939d9c7ae6e9…` |
| XAUUSD_2025-11.parquet | `016517904b326a53…` |
| XAUUSD_2025-12.parquet | `e8ad92ba1b1bba37…` |
| XAUUSD_2026-01.parquet | `de17f9c531667812…` |
| XAUUSD_2026-02.parquet | `1978ce53545f31fd…` |
| XAUUSD_2026-03.parquet | `8fba205494b4a068…` |
| XAUUSD_2026-04.parquet | `f1b48a9c7c3b9dec…` |
| XAUUSD_2026-05.parquet | `f8ddcae5e23ce1dd…` |
| XAUUSD_2026-06.parquet | `6a404b415cb92194…` |
| XAUUSD_2026-07.parquet | `2f7751b028f18383…` |
| XAUUSD_2026-08.parquet | `5645380ddd0c1a4b…` |
| XAUUSD_2026-09.parquet | `6b51ceb0fa34f123…` |

Full digests and per-file row counts are in
`data/evidence/xauusd_dukascopy_acquisition.json → source.files`.

A 1-hour aggregation of the same bars is also exported
(`data/raw/xauusd_dukascopy_1h_mid_agg_20250806_20260916.csv`,
sha256 `97b457d6ac427436…`, rule: open = first 15m open, high = max, low = min,
close = last 15m close, volume = Σ ticks). It was **rejected by the existing
ingest quality gate** (`no_missing_bars`: 276 abnormal intraday gaps > 1.5×tf,
4.24 % > 2 % threshold) and is therefore **not registered**. The gate was not
weakened and the rejection is recorded in the acquisition evidence.

Supplementary measured spread evidence (same repo/commit,
`app/public/data/news_ticks/XAUUSD/`, manifest sha256
`3766c373a834ecf5…`): 23 event windows (9 CPI, 6 FOMC, 8 NFP) with real
bid/ask ticks, 368,326 ticks total, pooled spread median **1.73 bps**,
p95 3.04 bps, mean 1.98 bps; recorded in
`data/evidence/xauusd_event_spread_evidence.json`. This is **not** a continuous
spread history and is **not** wired into the adequacy gate — R5 remains FAIL.

## 4. Quality, gaps, duplicates, precision

- `qts data validate --version 20260918-010+8f120133-1ba57af7` → **12/12 PASS**
  (monotonic_time, tz_aware, no_future, ohlc_invariants, positive_prices,
  abnormal_spreads, no_duplicates, single_symbol, no_missing_bars,
  session_boundaries, no_broker_artifacts, volume_non_negative).
- Duplicates: **0** duplicate open timestamps; timestamps strictly increasing.
- Precision: prices are float64 mid values as published upstream (typically 4–6
  significant decimals); tick counts are integers.
- Gaps (two honest measures with different definitions):
  - canonical inventory (`data/evidence/data_inventory.json`, modal 900 s
    cadence, closure gaps excluded): 278 gaps, 58 closure gaps,
    max abnormal gap 102,600 s, 1,493 missing 15m intervals ≈ 5.42 % within the
    measured active span;
  - manifest span measure (`missing_data_stats`): 39,073 expected vs 26,038
    actual = 33.36 % of the calendar span has no bar — this is dominated by
    weekend/market closures, not unexplained holes.
- Gaps are genuine market closures / data unavailability and are left absent.

## 5. Reproducing the acquisition

```bash
git clone https://github.com/vudo805/forex-price-simulator /tmp/vudo805
git -C /tmp/vudo805 rev-parse HEAD   # must be 4d6f15543e6285fad91fd57fe42f716bc7273075
python scripts/acquire_xauusd_dukascopy.py --source-dir /tmp/vudo805/data/XAUUSD --ingest
qts data validate --version <printed version>
```

The script verifies every pinned SHA-256 before writing anything, exports the
CSVs, writes `data/evidence/xauusd_dukascopy_acquisition.json`, and registers
the dataset through the existing `ingest_csv(..., source=...)` pipeline
(the `qts data ingest` CLI has no provenance-label flag; the Python API is the
designed path). Registration writes to gitignored `data/curated/` and
`data/sqlite/qts.db`; re-running it is idempotent for the same source label and
export path.

## 6. Licensing and usage constraints

- The upstream repository carries **no LICENSE file** and states no license:
  treat the bytes as unlicensed third-party content.
- The system's own source catalog describes Dukascopy data as "free personal,
  no redistribution"; Dukascopy's current terms were **not re-verified** during
  this acquisition.
- Therefore: **internal research use only, no redistribution, no sublicensing**,
  no warranty of fitness. The dataset must not be published, shipped, or used
  to make external claims without a licensing review.

## 7. What this dataset supports — and what it does not

Supported (demonstrated by the run recorded in
`docs/research/impulse_continuation_report_xauusd_dukascopy_15m.md`):

- provenance-qualified real-market bar research on XAUUSD 15m bars (R1–R4, R6 of
  the pre-registered adequacy gate pass; 3,759 measured events, both sides);
- a genuine pre-registered impulse-continuation result in `REAL_CLAIMS` mode:
  `REGIME_DEPENDENT`, `go/block = BLOCK` (no promotion, no order path).

Not supported / unknown:

- **execution realism** — bars are mid; no continuous bid/ask, no broker fill,
  latency, or slippage; research costs remain declared assumptions
  (R5-EXECUTION-DATA FAIL, non-blocking). The 23 event windows are the only
  measured spreads and are event-selected.
- **broker semantics** — no MT5 session calendar, no broker spread or swap
  metadata; the `MT5` venue field is a namespace, not evidence.
- **multi-year regime generalization** — 407 days is below the 2-year target in
  `docs/data_requirements.md`; results are single-regime-window evidence.
- **cross-asset / cross-instrument** generality — XAUUSD only.
- **survivorship and corporate adjustments** — not applicable / unavailable for
  this instrument.
- **recency beyond LAG_DAYS=2** — the upstream refresh lags ~2 days; at run time
  the last bar was 1.6 days old (within the 7-day freshness gate).

The synthetic fixture (`20260918-010+…-572728d9`) remains registered and
labelled `SYNTHETIC`; it is unchanged and remains mechanism-validation-only.
