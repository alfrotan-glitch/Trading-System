# Data Source Comparison
Generated: 2026-09-16 — `data/evidence/data_source_catalog.json`

**Status:** the provider table is a historical/planning catalog, not evidence
that any provider route or license has been acquired. Licensing descriptions
are unverified metadata and must not be read as permission to redistribute or
commercially use data. The separately acquired Dukascopy-derived dataset has no
upstream LICENSE and is restricted to internal research pending legal review;
see the provenance record.

| Provider | Depth | Granularity | Bid/Ask | Tick | Timezone | Licensing | Access | Reliability | Quality | Mapping | Timestamp | Limitations | Cost | Research Suitability | Execution Suitability |
|----------|-------|-------------|---------|------|----------|-----------|--------|-------------|---------|---------|-----------|-------------|------|----------------------|----------------------|
| **dukascopy** | 2003+ FX | tick,1m,1H,1D | ✅ | ✅ | UTC/Geneva | Free personal, no redistribution | https://dukascopy.com + dukascopy-node | High | Good FX | XAU/USD needs verify | UTC | FX only, not broker spread | Free | High FX/cross | Medium XAUUSD |
| **firstrate** | 2003+ | tick,1s,1m,1H | ❌ | ✅ | UTC | Paid, no redistribution | firstratedata.com bulk | High | Excellent mid | XAUUSD standard | UTC | Cost $300/yr, mid only, SYNTHETIC spread | $$$ | High MTF | Medium mid only |
| **mt5_history** | 1-2yr 1m, 5yr 1H (broker) | 1m,5m,15m,1H | ❌ | ❌ | Server UTC+2 | Broker terms personal | MT5 History Center CSV | Broker-specific | Best XAUUSD OHLC if live capture for spread | XAUUSD as is | Server→UTC DST | Limited depth, no historical bid/ask, need forward for spread | Free with account | High XAUUSD regime | High if forward capture |
| **binance** | 2017+ BTC | tick,1s,1m,1H | ❌ | ✅ | UTC | Public CC BY | api.binance.com + zip | High crypto | Excellent crypto | BTCUSDT not XAUUSD | UTC ms | Crypto only, not XAUUSD | Free | High cross-asset | Medium crypto |
| **truefx** | 2009+ majors | tick bid/ask | ✅ | ✅ | UTC | Free personal | truefx.com downloads | Medium | Good FX | XAU/USD | UTC ms | FX only, XAUUSD verify | Free | Medium-High FX exec | High FX bid/ask |

**Selection reasoning**: Not chosen because free — chosen based on scientific suitability and reproducibility. For XAUUSD execution realism, **mt5_history + live forward capture** is best (broker-specific spread). For depth/cross-market, **dukascopy** (FX) + **binance** (crypto) for regime diversity. For institutional MTF, **firstrate** if budget allows but mid only → spread must remain SYNTHETIC. `data/evidence/data_source_catalog.json` machine-readable preserves provider comparison.

## Acquired 2026-09-18 — Dukascopy-derived XAUUSD 15m mid history

The first REAL dataset is now registered
(`20260918-010+8f120133-1ba57af7`; provenance record
`docs/data_provenance_xauusd_dukascopy.md`). It was acquired from the pinned
GitHub mirror `vudo805/forex-price-simulator` @
`4d6f15543e6285fad91fd57fe42f716bc7273075`, whose daily job fetches Dukascopy
XAU/USD ticks and publishes 15-minute **mid** OHLC bars (mid = (bid+ask)/2)
with per-bar tick counts. This matches the catalog's Dukascopy row (tick-derived,
UTC, deep) while staying reachable from this environment (bash egress is
GitHub/PyPI-only; Dukascopy cannot be fetched directly, and the `bi5` endpoint
returns an opaque LZMA binary through the page fetcher).

Why this source, over the alternatives actually evaluated:

- **tick-derived, not ordinary OHLC** — mid prices come from real bid/ask ticks,
  satisfying the "prefer tick-derived" requirement;
- **same instrument/day semantics** — XAU/USD spot, UTC timestamps, 15-minute
  cadence; no session-timezone guessing;
- **verifiable bytes** — all 14 monthly parquet files pinned by SHA-256 and
  re-verified from a fresh clone; the dataset checksum is recorded in the
  manifest;
- **honest gaps** — missing bars stay absent (no interpolation);
- rejected alternatives: `FX-Data/FX-Data-XAUUSD-DS` (2011–2018, ends 2018 →
  fails freshness), `datxbt/xauusd-research-ORB` (derived, no continuous
  history), `Sai310421/xauusd-duka-feed` (same upstream lineage as the chosen
  source — corroboration only), `alexgabrielbarbu90-hue/xauusd-data` (weak
  alignment to the chosen source; not usable as a verifier), `histdata.com`
  (download route unverified), `Tolux5000` / `CoderABD7000` / `MSeyyidDev`
  (insufficient or non-continuous).

Known limits of the acquisition: **no upstream LICENSE** (internal research
use only), derived mid rather than executable bid/ask, 407 days (below the 2-year
regime target), and no broker session/fill metadata. A 1H aggregation of the
same bars was rejected by the existing gap gate and is not registered.

**Next step**: acquire a licensed/first-party source with continuous bid/ask and
broker session semantics (mt5_history + forward capture), longer history for the
2-year regime target, and a second instrument (e.g. EURUSD/BTC) for generality.

