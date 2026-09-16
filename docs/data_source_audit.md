# Data Source Audit
Generated: 2026-09-16

## Audit Method
`src/qts/data/audit.py` `audit_data_sources()` inspects `SqliteParquetDataStore` manifests, `data/raw`, `data/curated`, checks licensing, depth, timestamp, bid/ask, spread, tick, survivorship, adjustments, broker differences.

## Available Sources (as of 2026-09-16)
| Version | Instrument | Timeframe | Rows | Start | End | Checksum | Source label | Bid/Ask | Spread | Tick | Timestamp | Survivorship | Depth |
|---------|------------|-----------|------|-------|-----|----------|--------------|---------|--------|------|-----------|--------------|-------|
| `<checksum-derived id>` (established by `qts data bootstrap`) | XAUUSD | 1H | 500 | 2020-01-01 | 2020-01-21 | sha256 of fixture bytes | **SYNTHETIC:fixture:XAUUSD_1H_500** | false | proxy high-low only | false | UTC | single symbol no issue | 500 bars (~20.8 days) |

Version IDs are content-checksum derived (never hardcoded/date-stamped) and are **not tracked in git**: `data/manifests/` and `data/curated/` are gitignored, and a clean clone establishes the dataset via `qts data bootstrap` (idempotent, fail-closed, truthful `SYNTHETIC` labeling). Raw files: `data/raw` empty on clean clone. Curated: partitioned Parquet per version. Fixtures: `data/fixtures/XAUUSD_1H_500.csv` (tracked).

## Per Source Details
- **Licensing/availability**: synthetic fixture (GBM-generated), internal, no external licensing, **not production market data** — labeled `SYNTHETIC`, never `REAL`.
- **Historical depth**: 500 bars (~20 days 1H) — insufficient for credible multi-regime inference.
- **Timestamp quality**: UTC, monotonic, tz_aware PASS, gap_count 0, missing 0.2%.
- **Bid/ask**: not available — limitation.
- **Spread**: only high-low proxy, not real broker spread.
- **Tick**: not available.
- **Survivorship**: XAUUSD metal single symbol, no survivorship bias but single market.
- **Corporate adjustments**: not applicable.
- **Broker differences**: mock vs real MT5 not distinguished — limitation.

## Comparison & Choice
Only one structurally identical dataset available — choice is forced. Cannot compare breadth.

## Limitations Explicitly Reported
- Only 500-row XAUUSD 1H single market, single timeframe, single regime period (Jan 2020).
- No bid/ask, no tick, spread proxy only → execution-aware research limited.
- No cross-asset, no lead/lag, no multi-timeframe depth.
- Historical depth far below minimum 5000 bars (6 months 1H) ideally 2 years.
- Not multi-regime (no 2020-2024 varied volatility).
- Synthetic-like CSV not production.

## Minimum Expansion Needed (for credible research)
- Historical depth: 5000+ bars (6 months 1H) ideally 2 years (~17520 1H bars).
- Symbols: XAUUSD + EURUSD + perhaps BTC for cross-asset generality.
- Timeframes: 1H + 15m or 1M for multi-timeframe structure.
- Regimes: include high/low volatility periods 2020-2024.
- Execution: real spread, bid/ask, tick from MT5 history or FirstRate/Dukascopy with licensing cleared, UTC timestamp, survivorship documented.

## Recommendation
Acquire at least 2 years XAUUSD 1H with real bid/ask, plus 1 year 15m, plus EURUSD 1H for robustness, from broker MT5 history export (if available) or licensed vendor, Store via `qts data ingest --path ... --instrument XAUUSD --timeframe 1H`.

## Never Substitute
Do not silently substitute convenient synthetic for real market data — GBM vs real microstructure invalidates execution assumptions (see `experiment_governance.md`).

## Machine Evidence
`data/evidence/data_source_audit.json` (generated via `audit_data_sources()`).
