# Market Data Observatory
Version: 0.1.0 — 2026-09-16

## Purpose
Production-quality observatory answering: What data do we have, what is missing, what fills gaps, which sources trustworthy, how far history extends, how execution reality measured, how forward observations collected without risking capital.

## Architecture
`src/qts/data/inventory.py` → `data/evidence/data_inventory.json` (per dataset audit)
`src/qts/data/provider.py` → provider-neutral pipeline Provider→RawStorage→Validation→Normalization→Canonical→Manifest→Evidence (raw preserved, immutable dataset ID)
`src/qts/domain/value_objects.py` Tick extended with bid/ask/last/size/type/session, Bar strict invariants
`src/qts/execution/reality.py` ExecutionRealityStore
`src/qts/observability/forward_observatory.py` ForwardObservatory (safe, no capital)
`src/qts/regime/observatory.py` RegimeObservatory (transitions)
Desktop: Data Observatory, Data Source Lab, Market Monitor, Forward Observatory, Data Lineage

## Data Landscape Audit (Phase 1)
Generated via `src/qts/data/inventory.py` `generate_inventory()` for every dataset:
- source, provider, instrument, timeframe, date_range, row/tick count, timezone (UTC), timestamp resolution (second, 1m inferred), OHLC yes, bid no, ask no, spread proxy SYNTHETIC, volume tick-proxy SYNTHETIC, tick vs real volume, missingness 0.2% (1/501), duplicates false, gaps gap_count 0 missing_pct 0.2 common_delta 3600s, session coverage XAUUSD 24h minus weekend, market-closure handling synthetic ignores closures, broker artifacts none, checksum sha256, ingestion method `Provider csv → Raw Storage → Validation → Normalization → Canonical`, preprocessing 1.0.0, provenance `Raw data/fixtures/XAUUSD_1H_500.csv checksum ... → curated part-0.parquet`.

Current inventory (2 datasets):
- 572728d9 XAUUSD 1H 500 rows 2020-01-01→2020-01-21
- 86ca2f9c XAUUSD 1H 2000 rows 2020-01-01→2020-03-24
- (b0c05dca/cc66608a synthetic test artifacts, not research-eligible)

Machine-readable: `data/evidence/data_inventory.json`.

## Data Requirements Matrix (Phase 2)
`docs/data_requirements.md` matrix: Research Type → Required Data → Availability → Missing → Scientific Consequence.

## External Data-Source Research (Phase 3)
`docs/data_source_comparison.md` + `data/evidence/data_source_catalog.json` (5 providers: dukascopy, firstrate, mt5_history, binance, truefx) with historical depth, granularity, bid/ask, tick, timezone, licensing, API, reliability, quality, mapping, timestamp behavior, limitations, cost, suitability.

## Ingestion Architecture (Phase 4)
`src/qts/data/provider.py` `DataProvider` abstract `fetch`→`parse`, implementations `CsvProvider`, `SyntheticProvider` (labeled SYNTHETIC), catalog `EXTERNAL_CATALOG`, function `ingestion_pipeline` steps: fetch raw copy → raw checksum → parse → validate (12 checks) → normalize UTC sort quantize → write canonical Parquet → manifest immutable ID → evidence JSON with raw preserved. Never overwrites raw.

## Tick / Bid-Ask Support (Phase 5)
`src/qts/domain/value_objects.py` `Tick` has bid/ask/bid_size/ask_size/event_time, validates ask≥bid, computes mid/spread. Extended to `last`, `tick_type`, `session` in `forward_observatory.ObservationTick`. Synthetic spread explicitly labeled `SYNTHETIC` in inventory `spread_availability: proxy via high-low (SYNTHETIC)`, never manufactured bid/ask labeled as historical.

## Execution-Reality Data (Phase 6)
`src/qts/execution/reality.py` `ExecutionObservation` records signal_price, expected (bid/ask at decision), requested/submission/broker_ack/fill timestamps, requested/filled volume, realized price, spread, slippage_bps, latency_ms, rejection, partial fill, market_state, source REAL/SYNTHETIC etc. `ExecutionRealityStore` SQLite `execution_observations`, `summary()` reports real vs synthetic counts, avg/max slippage, rejections, partials, and note "cannot claim realism without observations". Machine evidence `data/evidence/execution_reality.json`.

## Forward Market Observatory (Phase 7)
`src/qts/observability/forward_observatory.py` `ForwardObservatory` `observation_ticks`/`observation_signals`/`observation_sessions` SQLite. Records live quotes (bid/ask/mid/spread/volatility/session/regime/freshness/anomaly), signals (side, strategy_id, theoretical vs executable bid/ask, hypothetical fill, slippage model, latency, NO_TRADE reason, regime), no live trading, `simulate_observation` for testing, `to_manifest` → `data/evidence/forward_observation_manifest.json` with sample ticks/signals, sessions count.

## Market Regime Observatory (Phase 8)
`src/qts/regime/observatory.py` `RegimeObservation` trend_strength, realized_vol, vol regime low/normal/high, range_chop, spread_regime, session, acceleration, compression/expansion, shock_event, liquidity_proxy. `RegimeObservatory` stores, `transitions()` detects vol regime changes, `summary()` distribution, `to_json` → `data/evidence/market_regime_observations.json`.

## Cross-Market (Phase 9) & Timeframe (Phase 10)
`docs/cross_market_research.md` evaluates FX/metals/crypto candidates for genuine behavior diversity, not sample size. `docs/timeframe_research.md` investigates 1m/5m/15m/1H/4H/1D/tick eligibility via data quality, cost sensitivity, frequency, slippage, signal decay — timeframe eligible only if quality sufficient.

## Historical Depth (Phase 11)
Documented statistical reasoning: minimum backtest length via PSR inversion `minimum_backtest_length` in `src/qts/research/statistical.py` — for sharpe 0.5 need ~200 bars for PSR 0.95, but regime coverage requires 5000+ bars multi-year. For each symbol/timeframe report available vs required, effective sample, independent obs, regime coverage, remaining uncertainty. Blocks overconfidence.

## Data Quality Stress Testing (Phase 12)
`src/qts/data/quality.py` 12 checks plus adversarial stress in `tests/test_data_quality_stress.py`: missing bars, duplicates, timestamp shifts, timezone errors, bid/ask inversion, zero price, impossible spread, stale ticks, out-of-order, session contamination, future leakage, symbol remapping, partial coverage — corrupted dataset fail-closed.

## Versioning / Locking (Phase 13)
Every dataset immutable: changing preprocessing → new dataset version (new checksum), not mutate previous. `store.write_bars` creates new version ID, `manifest.version` checksum, `preprocessing_version`, `schema_version`. Research evidence always identifies exact checksum. Locked tests remain inaccessible during discovery via `LockedTestPartitioner` frozen.

## Research Reboot (Phase 14)
Classify datasets by research readiness (eligible 1H only), select highest-quality universe (572728d9 500 rows — still limited, explicitly reported), document selection, create new manifests, run null/placebo controls, rerun only justified hypotheses (trend/breakout families), preserve cumulative trial count 75 (no reset), preserve multiple-testing history where materially related.

## New Edge Discovery After Upgrade (Phase 15)
Autonomous `campaign_engine` reactivated after data layer validated, revisits hypotheses, rejects old assumptions, discovers new mechanisms (state-machine, event shock, multi-timeframe, vol-normalized), explores exits/filters/multi-timeframe/execution-aware, but enforces trial accounting, DSR/PBO/PSR/RealityCheck/SPA/null/placebo/cost/slippage/regime/perturbation/forward — no promotion without gates.

## Forward Paper/Shadow (Phase 16)
`qts run --mode paper` / `--mode shadow` forward observation records every signal/NO_TRADE/hypothetical entry/bid-ask/fill/exit/costs/slippage/regime/drawdown/expectancy; compares research simulation vs paper vs shadow vs real, measures agreement via `execution_consistency`.

## Desktop UI (Phase 17)
Data Observatory (inventory table), Data Source Lab (provider catalog comparison), Market Monitor (live quotes spread/vol regime freshness anomalies), Forward Observatory (sessions/signals/NO_TRADE/hypothetical fills/slippage), Data Lineage (raw→processed→manifest→experiment→strategy→validation graph).

## Research Quality Gate (Phase 18)
Before discovery: reports DATA QUALITY (12/12 PASS but synthetic spread), DATA DEPTH (500 insufficient for 5000 needed), DATA DIVERSITY (single symbol/timeframe), EXECUTION REALISM (synthetic spread, no real tick), REGIME COVERAGE (single Jan 2020), OUT-OF-SAMPLE COVERAGE (walk-forward 5 folds but limited), TRIAL COUNT 75, STATISTICAL EVIDENCE (DSR 0.12 fail) → **BLOCK**.

## No Fake Data Rule (Phase 19)
Distinguishes REAL/SYNTHETIC/SIMULATED/ESTIMATED/IMPUTED/BROKER-DERIVED/MODEL-DERIVED — UI badges, reports, machine evidence explicitly label `SYNTHETIC` for high-low proxy, never synthetic as real.

## Final Research Decision (Phase 20) — 10 Questions
1. **What is the highest-quality data we have?** 86ca2f9c 2000 rows XAUUSD 1H synthetic proxy UTC 2020-01-01→2020-03-24 (572728d9 500 rows primary) — OHLC PASS but spread SYNTHETIC, 0 real tick/bid-ask.
2. **What is still missing?** Real bid/ask/spread history, tick (bid/ask/last/size/type/session), depth 5000+ bars multi-year, multi-symbol (EURUSD/BTC), multi-timeframe (1m/15m/4H), execution timestamps/volumes.
3. **Which external sources fill these gaps?** Dukascopy (FX tick/1m free), FirstRate (1m/tick paid, mid only), MT5 history + forward capture (best for XAUUSD broker spread), Binance (crypto tick free), TrueFX (FX bid/ask tick free) — catalog `data_source_catalog.json` documents depth/granularity/licensing/cost.
4. **How far back in history can we go?** Via Dukascopy 2003+ (FX), MT5 1-2yr 1m / 5yr 1H, FirstRate 2003+ 1m; for XAUUSD 1H 5000 bars requires ~7 months ~ 2yr to cover regimes; currently 500 vs 5000 required → `historical_depth.json` pass false, uncertainty high.
5. **Have we collected real spread/bid-ask execution datasets yet?** No — 0 real execution observations; synthetic high-low proxy labeled SYNTHETIC, cannot claim execution realism; need live MT5 tick capture.
6. **Does any existing data allow realistic execution-cost research?** No — mid-price only; spread/slippage/latency research requires bid/ask at decision, fill timestamps; current `execution_reality.json` shows 0 real, cost stress 1.0/1.5/2.0× remains proxy.
7. **Can we run safe forward observation now without risking capital?** Yes — `ForwardObservatory` simulates 12 ticks, records quotes/spreads/vol/session/signals/NO_TRADE/hypothetical fills no capital, `forward_observation_manifest.json` proves safety; real live capture ready when MT5 connected but still hipothetical only.
8. **Which hypotheses remain untested and deserve revisiting after data expansion?** Volatility clustering, time-of-day/session, event shock, vol-normalized entries, multi-timeframe confirmation after real tick/15m acquired.
9. **Which claims are impossible to establish with current data?** True micro-structural edge, spread-sensitive, tick/microstructure, intraday microstructure, slippage distribution without real bid/ask/tick history.
10. **Decision?** **KEEP NO_TRADE** — insufficient DATA DEPTH/DIVERSITY/EXECUTION REALISM/REGIME COVERAGE/STAT EVIDENCE (DSR 0.12) to justify paper → shadow → live; preserve capital, continue forward observation, acquire MT5 Dukascopy data, reboot research with preserved N=75.

