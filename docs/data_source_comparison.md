# Data Source Comparison
Generated: 2026-09-16 — `data/evidence/data_source_catalog.json`

| Provider | Depth | Granularity | Bid/Ask | Tick | Timezone | Licensing | Access | Reliability | Quality | Mapping | Timestamp | Limitations | Cost | Research Suitability | Execution Suitability |
|----------|-------|-------------|---------|------|----------|-----------|--------|-------------|---------|---------|-----------|-------------|------|----------------------|----------------------|
| **dukascopy** | 2003+ FX | tick,1m,1H,1D | ✅ | ✅ | UTC/Geneva | Free personal, no redistribution | https://dukascopy.com + dukascopy-node | High | Good FX | XAU/USD needs verify | UTC | FX only, not broker spread | Free | High FX/cross | Medium XAUUSD |
| **firstrate** | 2003+ | tick,1s,1m,1H | ❌ | ✅ | UTC | Paid, no redistribution | firstratedata.com bulk | High | Excellent mid | XAUUSD standard | UTC | Cost $300/yr, mid only, SYNTHETIC spread | $$$ | High MTF | Medium mid only |
| **mt5_history** | 1-2yr 1m, 5yr 1H (broker) | 1m,5m,15m,1H | ❌ | ❌ | Server UTC+2 | Broker terms personal | MT5 History Center CSV | Broker-specific | Best XAUUSD OHLC if live capture for spread | XAUUSD as is | Server→UTC DST | Limited depth, no historical bid/ask, need forward for spread | Free with account | High XAUUSD regime | High if forward capture |
| **binance** | 2017+ BTC | tick,1s,1m,1H | ❌ | ✅ | UTC | Public CC BY | api.binance.com + zip | High crypto | Excellent crypto | BTCUSDT not XAUUSD | UTC ms | Crypto only, not XAUUSD | Free | High cross-asset | Medium crypto |
| **truefx** | 2009+ majors | tick bid/ask | ✅ | ✅ | UTC | Free personal | truefx.com downloads | Medium | Good FX | XAU/USD | UTC ms | FX only, XAUUSD verify | Free | Medium-High FX exec | High FX bid/ask |

**Selection reasoning**: Not chosen because free — chosen based on scientific suitability and reproducibility. For XAUUSD execution realism, **mt5_history + live forward capture** is best (broker-specific spread). For depth/cross-market, **dukascopy** (FX) + **binance** (crypto) for regime diversity. For institutional MTF, **firstrate** if budget allows but mid only → spread must remain SYNTHETIC. **No source chosen yet** — catalog is research, not yet ingested beyond synthetic. `data/evidence/data_source_catalog.json` machine-readable preserves provider comparison.

**Not yet ingested**: External sources require download/API, licensing cleared, symbol mapping, timestamp conversion — not yet fetched; current inventory remains synthetic proxy, explicitly labeled.

**Next step**: Acquire mt5_history 2yr XAUUSD 1H + 1m via MT5 export, plus dukascopy EURUSD 1H for cross-market, verify TrueFX XAUUSD availability.

