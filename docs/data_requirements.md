# Data Requirements Matrix
Version: 0.1.0

| Research Type | Required Data | Current Availability | Missing | Scientific Consequence | Justification |
|---------------|---------------|----------------------|---------|------------------------|---------------|
| Trend research (SMA) | OHLC 1H, 500+ bars | OHLC 1H 500 bars synthetic XAUUSD | Depth, regime diversity | Cannot claim generality beyond Jan 2020 | Trend needs multi-regime |
| Breakout (Donchian) | OHLC 1H, high-low accurate | OHLC proxy | Bid/ask for true breakout | Breakout at mid may not be executable at bid/ask | Execution at next bar open uses proxy spread |
| Mean reversion (Bollinger) | OHLC 1H, close | OHLC 500 bars | Multi-timeframe, vol normalization | Reversion may be artifact of sample | Need longer to test |
| Momentum | Close returns 1H | Available | No bid/ask, no cross-asset | Momentum may be correlated with spread | Spread not real |
| Volatility (ATR) | Range + close | Proxy range | Real tick for ATR accuracy | Volatility clustering needs tick | Proxy underestimates |
| Spread-sensitive | Real bid/ask/spread history | **No bid/ask**, synthetic high-low proxy (SYNTHETIC) | Real spread, tick | **Blocks execution research** | Cannot measure true cost |
| Intraday (1m/5m) | 1m OHLC, 5000+ bars | No 1m data | 1m history | Cannot research intraday | Timeframe not eligible (quality insufficient) |
| Microstructure | Tick bid/ask/size/type | No tick | Tick history | Impossible | Requires Dukascopy tick |
| Execution research | Bid/ask at decision, fill timestamps, latency | No real observations | ExecutionRealityStore empty | Cannot claim realism | Need forward observatory live capture |
| Slippage research | Spread + fill price | Synthetic only | Real slippage distribution | Cost stress is proxy 1.0/1.5/2.0×, not measured | ExecutionRealityStore shows 0 real obs |
| Latency research | Submission→ack timestamps | No live broker | Latency measurements | Cannot measure | Need MT5 live |
| Tick-based strategy | Tick last/bid/ask | No tick | Tick | Not eligible | Requires tick |
| Multi-timeframe | 1H + 15m + 4H | Only 1H | 15m/4H | Cannot test MTF structure | Need additional timeframes |
| Cross-asset | XAUUSD + EURUSD/BTC | Only XAUUSD | EURUSD/BTC history | Cannot test generality | Need Second market |
| Regime research | Volatility/trend time series | Sample only Jan 2020 | Multi-year regimes | Regime coverage insufficient | Need 2 years |
| Forward observation | Live quotes/signals/NO_TRADE/hypothetical fills | ForwardObservatory simulated 10 ticks | Real live capture | Simulated not real | ForwardObservatory can run safely but currently simulated |

**Reasoning**: Each requirement derived from strategy's reliance on specific market feature (e.g., spread-sensitive needs real spread; microstructure needs tick). Current availability from `data_inventory.json` shows only synthetic OHLC 1H.

**Result**: Data quality PASS for OHLC but diversity/depth/execution realism FAIL → research quality gate BLOCK.

