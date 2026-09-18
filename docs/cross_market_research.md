# Cross-Market Research
Version: 0.1.0 — 2026-09-16

## Why Beyond XAUUSD
Current research evidence remains single-symbol: one REAL XAUUSD 15m history
(26,038 bars, approximately 407 days) plus an unchanged synthetic XAUUSD 1H
fixture. The REAL impulse result is `REGIME_DEPENDENT / BLOCK`; independent
market/timeframe generality is untested.

## Embedded vs Genuinely Diverse
- **Not diverse**: XAUUSD vs XAUEUR (same underlying).
- **Diverse**: XAUUSD (metal safe-haven, volatile) vs EURUSD (FX mean-reverting, high liquidity) vs BTCUSDT (crypto 24/7, high vol) — different drivers, sessions, shocks.

## Evidence-Based Selection
- **Evidence for**: We have only XAUUSD; need EURUSD (dukascopy 2003+, free tick/1m, high quality, need verify) + BTC (binance free tick) to test cross-asset robustness; cross-market would catch spurious XAUUSD-only pattern.
- **Evidence against**: Adding markets for sample-size alone without behavior difference is padding; must show that strategy passes XAUUSD but fails EURUSD (or vice versa) indicates overfit.
- **Current status**: No independent cross-asset data is ingested. XAUUSD is
  the only instrument, with the REAL 15m dataset and synthetic 1H fixture
  described above. The source catalog remains a planning list; research gate
  BLOCK remains until independently licensed diversity is present and tested.

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
Cross-market research is not yet possible with the current single-symbol
population. It is a future breadth milestone after the current R5/observation
status is addressed; any EURUSD/BTC acquisition must be separately licensed,
versioned, preregistered and tested with unchanged safety/statistical gates.

