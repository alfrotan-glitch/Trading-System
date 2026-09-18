# Cross-Market Research
Version: 0.1.0 — 2026-09-16

## Why Beyond XAUUSD
Current inventory: single symbol XAUUSD, single timeframe 1H, single month (Jan 2020) → insufficient regime/diversity; generality untested.

## Embedded vs Genuinely Diverse
- **Not diverse**: XAUUSD vs XAUEUR (same underlying).
- **Diverse**: XAUUSD (metal safe-haven, volatile) vs EURUSD (FX mean-reverting, high liquidity) vs BTCUSDT (crypto 24/7, high vol) — different drivers, sessions, shocks.

## Evidence-Based Selection
- **Evidence for**: We have only XAUUSD; need EURUSD (dukascopy 2003+, free tick/1m, high quality, need verify) + BTC (binance free tick) to test cross-asset robustness; cross-market would catch spurious XAUUSD-only pattern.
- **Evidence against**: Adding markets for sample-size alone without behavior difference is padding; must show that strategy passes XAUUSD but fails EURUSD (or vice versa) indicates overfit.
- **Current status**: No cross-asset data yet ingested — `data_inventory.json` shows only XAUUSD; `data_source_catalog.json` documents dukascopy (FX), binance (crypto) as candidates; research gate BLOCK until diversity present.

## Which Markets To Acquire (Prioritized)
1. EURUSD 1H (dukascopy free, 2003+, tick, high reliability, XAUUSD correlation moderate, tests FX mean reversion) — priority high
2. BTCUSDT 1H (binance free, 2017+, 24/7, high vol, tests trend) — secondary
3. XAGUSD (if XAU edge, test silver) — tertiary

## Procedure
- Acquire via `provider.py` `DataProvider` (dukascopy/binance), `ingestion_pipeline` preserves raw, immutable dataset ID, quality 12 checks, `data_inventory.json` entry per market.
- Generate eligibility: only markets with quality PASS and regime coverage >6 months eligible for research.
- Cross-market validation: strategy must pass holdout on second market (not training market) with DSR gate — otherwise reject as spurious.

## Desktop
Data Observatory multi-symbol view, Data Source Lab provider comparison, Research Lab holdout comparison across markets.

## Conclusion
Cross-market not yet possible with current single-symbol data; next step acquire EURUSD + BTC, then reboot research (Phase 14) with updated universe, null/placebo controls per market.

