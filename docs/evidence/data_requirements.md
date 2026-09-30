# Data Requirements Matrix
Version: 0.1.0
Updated: 2026-09-18

**Current inventory (see `data/evidence/data_inventory.json`)**: one REAL,
acquired dataset `20260918-010+8f120133-1ba57af7` — XAUUSD 15m, 26,038
tick-derived mid OHLC bars, 407.00 days (2025-08-06 → 2026-09-17 UTC). The
frozen acquisition snapshot reported 12/12 quality checks and readiness READY,
but the preserved inventory's legacy gap audit records 1,493 unexpected
15m intervals (5.42%). The current conservative model finds 1,785 intervals
(6.42% of active expected coverage), so the hardened completeness quality gate
is FAIL. Provenance and the full disposition are in
`docs/data_completeness_disposition.md`.
A 1H aggregation of the same bars was rejected by the existing ingest gate and
is not registered. The synthetic 1H fixture remains registered, labelled
SYNTHETIC, and is mechanism-validation-only.

| Research Type | Required Data | Current Availability | Missing | Scientific Consequence | Justification |
|---------------|---------------|----------------------|---------|------------------------|---------------|
| Trend research (SMA) | OHLC 1H, 500+ bars | REAL XAUUSD 15m, 26,038 bars / 407 d (no registered 1H — aggregation rejected by the gap gate) | 1H series, multi-year regimes | Claims must be stated for the 15m series/window only | Trend needs multi-regime |
| Breakout (Donchian) | OHLC 1H, high-low accurate | REAL 15m mid OHLC | Bid/ask for true breakout | Breakout at mid may not be executable at bid/ask | Execution at next bar open uses proxy spread |
| Mean reversion (Bollinger) | OHLC 1H, close | REAL 15m mid OHLC, 407 d | Multi-timeframe, longer span | Reversion may be regime-window specific | Need longer to test |
| Momentum | Close returns 1H | REAL 15m close returns | No bid/ask, no cross-asset | Momentum may be correlated with spread | Spread not measured continuously |
| Volatility (ATR) | Range + close | REAL 15m range, tick counts | Real tick for ATR accuracy | Volatility clustering measurable but mid-based | Mid range understates executable range |
| Spread-sensitive | Real bid/ask/spread history | **No continuous bid/ask**; 23 event windows measured (median 1.73 bps) | Continuous spread/tick history | **Blocks execution research** | Cannot measure true cost continuously |
| Intraday (1m/5m) | 1m OHLC, 5000+ bars | No 1m/5m data; 15m available | 1m history | Cannot research 1m/5m intraday | Timeframe not eligible (quality insufficient) |
| Microstructure | Tick bid/ask/size/type | No tick history (23 event tick windows only, supplementary) | Continuous tick history | Impossible | Requires Dukascopy tick at scale |
| Execution research | Bid/ask at decision, fill timestamps, latency | No real fill observations | ExecutionRealityStore empty | Cannot claim realism | Need forward observatory live capture |
| Slippage research | Spread + fill price | Declared assumptions + 23 event windows | Real slippage distribution | Cost stress is proxy 1.0/1.5/2.0×, not measured | ExecutionRealityStore shows 0 real obs |
| Latency research | Submission→ack timestamps | No live broker | Latency measurements | Cannot measure | Need MT5 live |
| Tick-based strategy | Tick last/bid/ask | No continuous tick | Tick | Not eligible | Requires tick |
| Multi-timeframe | 1H + 15m + 4H | 15m registered (+ 1H aggregation rejected by gate) | Registered 1H, 4H | Cannot test MTF structure | Need additional registered timeframes |
| Cross-asset | XAUUSD + EURUSD/BTC | Only XAUUSD | EURUSD/BTC history | Cannot test generality | Need second market |
| Regime research | Volatility/trend time series | REAL 15m, 407 days | Multi-year regimes (2 y target) | Regime coverage incomplete; R3 ≥180 d passes, 2 y target unmet | Need 2 years |
| Forward observation | Real MT5 demo quotes with provenance | Canonical store: 0 real observations; `simulate_observation` is TEST-ONLY SYNTHETIC | Real Windows/MT5 observation session | No session evidence yet | Structural collector exists; no real session has run |

**Reasoning**: Each requirement derives from the strategy's reliance on a
specific market feature (spread-sensitive needs real spread; microstructure
needs tick). The inventory now contains one REAL dataset whose depth/span meet
the block-level minimums for bar research, plus the unchanged synthetic fixture.

**Result**: The frozen REAL 15m artifact has sufficient recorded depth/span for
its historical run, but the current audited completeness result is **FAIL**
(the preserved legacy count is 1,493 unexpected intervals / 5.42%; current
conservative semantics find 1,785 / 6.42%, versus the unchanged 2% limit). The
frozen research evidence is preserved and not rerun. **R5**, continuous
spread/tick data, multi-year regime coverage, cross-asset generality, and
licensed provenance remain unavailable; current promotion/readiness remains
**BLOCKED**. The completeness root cause and recovery outcome are formally
recorded; no gate is weakened.
