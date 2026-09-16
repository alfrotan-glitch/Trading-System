# Timeframe Research
Version: 0.1.0 — 2026-09-16

## Eligibility Criterion
Timeframe eligible only if quality sufficient — no assumption that 1m/5m data exists just because 1H exists. Eligible only if quality sufficient.

| Timeframe | Required Resolution | Available | Quality | Frequency | Cost Sensitivity | Slippage | Signal Decay | Eligible? | Notes |
|-----------|---------------------|-----------|---------|-----------|------------------|----------|--------------|-----------|-------|
| 1m | 1m OHLC + tick (5000+ bars) | None | No tick, no 1m | Very high | Extreme (spread proportional) | High | Seconds | **No** — missing | Need dukascopy/mt5 1m |
| 5m | 5m OHLC (5000+ bars) | None | Missing | High | High | High | Minutes | **No** — missing | Need 5m |
| 15m | 15m OHLC (3000+ bars) | None | Missing | Medium | Medium | Medium | Minutes-hour | **No** — missing | Need 15m |
| 1H | 1H OHLC (500+ bars) | 500 bars 2020-01 | PASS OHLC, synthetic spread | Low | Low (0.5-1.5 spread / 2000 ≈ 0.025%) | Low | Hours | **Eligible only for trend/breakout research, limited depth** | Single month, not multi-year |
| 4H | 4H OHLC (500+ bars) | None (could resample 1H) | Synthetic via resample → SYNTHETIC | Low | Low | Low | Hours | **Provisionally eligible if resampled from validated 1H, but label SYNTHETIC** | Resampled not real 4H |
| 1D | 1D OHLC (250+ bars) | None | Missing | Very low | Low | Low | Days | **No** — gap 20 days insufficient | Need 2yr |
| tick | tick bid/ask/size/type/session >100k | None | Missing | Ultra-high | Ultra sensitivity | Ultra | Ms | **No** — no tick | Need dukascopy tick |

## Cost / Frequency / Slippage Quantified
- **1H**: spread 0.5-1.5 on 2000 ≈ 0.025-0.075%; with 500 bars, 50% win, cost stress 1.0/1.5/2.0× in cpcv (wfe=1.0) models; eligible but limited.
- **1m**: spread same but bar range smaller → cost proportionally larger; microstructure dominates; without real tick cannot measure.

## Multi-Timeframe Strategy
Eligibility requires both timeframes independently PASS quality; e.g., 1H trend + 15m entry needs both 1H and 15m datasets validated. Currently impossible (only 1H).

## Procedure
Acquire via `DataProvider` ingestion pipeline for each timeframe, validate 12 checks, `data_inventory.json` eligibility, `ForwardObservatory` records timeframe-specific regime.

## Desktop
Timeframe selector in Backtest view, Data Observatory timeframe column, Data Lineage shows resampling lineage SYNTHETIC if applicable.

## Conclusion
Only 1H minimally eligible (500 bars Jan 2020) for limited research; all other timeframes BLOCK until quality sufficient. Need mt5_history 1m + 15m + 4H to unlock MTF/timeframe diversity.

