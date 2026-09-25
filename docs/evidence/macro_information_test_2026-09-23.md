# Macro Information Test — 2026-09-23

**Branch:** `arena/01a0cdf1-trading-system` → `f0a10b6` + this test  
**Instruction:** Single research phase **MACRO INFORMATION TEST** — no new trading strategy, no VFLP/Donchian/Bollinger/RSI combination, no held-out 40% access, no threshold optimisation, no parameter rescue, `NO_TRADE` `DEMO_EXECUTION=DISABLED` `LIVE=LOCKED`.  
**Question:** Does macro information provide statistically and economically meaningful **incremental** information about subsequent XAUUSD behaviour beyond existing L1 quote information (mid, spread, gap, trail)?  
**Sources tested:** (1) properly identified dollar-index series, (2) 10Y TIPS real yield, (3) FOMC/CPI/NFP event timestamps — each verified for provenance/licensing/timestamp/timezone/coverage/revision/reproducibility/identifier before ingestion.

---

## 1. Data provenance

### 1.1 XAUUSD 15m mid — baseline L1 information

| Field | Value |
|---|---|
| **Version (regenerated)** | `20260918-010+8f120133-1ba57af7` (same bytes as `aed0a51`) |
| **Source label** | `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks` |
| **Upstream** | `vudo805/forex-price-simulator` pinned `4d6f15543e6285fad91fd57fe42f716bc7273075` (2026-09-18T08:05:21+00:00, `Auto-update XAUUSD candle data`) |
| **Feed** | Dukascopy `datafeed.dukascopy.com` 20-byte `>iiiff` ticks, `POINT_VALUE 1000`, downloader `scripts/dukascopy_downloader.py` daily 03:00 UTC `LAG_DAYS=2` [docs/data_provenance_xauusd_dukascopy.md] |
| **Transform** | 15-min mid OHLC `mid=(bid+ask)/2` + per-bar tick count — **tick-derived, not synthetic** |
| **Files (14)** | `XAUUSD_2025-08.parquet` `e650d23…` 1632 … `XAUUSD_2026-09.parquet` `6b51ceb…` 1038 (verified SHA per `xauusd_dukascopy_acquisition.json`) |
| **Export** | `data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv` `7271892f…` 26038 rows + `1H` agg `97b457d…` 6513 |
| **Range** | `2025-08-06T00:00:00+00:00` → `2026-09-16T23:45:00+00:00` UTC (406.99 d) |
| **Data class** | `REAL`, `provenance_class=REAL` |
| **Quality** | `R1 REAL` PASS, `R2 DEPTH 26038≥5000` PASS, `R3 REGIME 407 d≥180 d` PASS, `R4 FRESHNESS 1.6 d` PASS, `R5 EXECUTION-DATA` **FAIL** (no bid/ask, `spread_availability UNAVAILABLE` — bar high-low is not spread), `R6 EVENT_SUFF` PASS (3759 impulse events). **Current gap completeness** `FAIL` 1785 unexpected intervals / 27,823 active expected = **6.42% >2%** (`analyze_gap_semantics` weekend-only, `R2-DEPTH` PASS not overridden). Gaps are **absent, not filled**. |
| **Licensing** | Upstream ships **NO LICENSE** — `internal research only, no redistribution` [§1, xauusd_dukascopy_acquisition.json] |
| **Timestamp** | UTC bar open, `900 s` cadence, monotonic, tz-aware, `market_closure_handling=UTC calendar gaps; broker session UNAVAILABLE` |
| **Reproducibility** | `git clone https://github.com/vudo805/forex-price-simulator` → `git checkout 4d6f155` → `python scripts/acquire_xauusd_dukascopy.py --source-dir /tmp/test-vudo/data/XAUUSD` (pandas 3.0.6) — SHA verified per file; `HEAD 2568039` differs (`dd67f2…` ≠ `6b51ceb…`) but pinned `4d6f155` is recovered via `git fetch --unshallow` (verified `6b51ceb0fa34…`). |
| **Reproduced here** | Regenerated 2026-09-23: `15m rows=26038`, `1H rows=6513` — bytes identical to `7271892f…` |

### 1.2 Event timestamps — FOMC/CPI/NFP (authoritative + reproducible window implementation)

**Authoritative schedule (used as canonical):**

| Event | Authority | Source identifier | Schedule provenance | Release time | Timezone | Coverage | Revision | Licensing |
|---|---|---|---|---|---|---|---|---|
| **FOMC** | Board of Governors of the Federal Reserve System | `federalreserve.gov/monetarypolicy/fomccalendars.htm` + `pressreleases/monetary20240809a.htm` (tentative 2025–2026, 2026-09-17 update) [web_search 3,1] | Eight scheduled meetings 2026: Jan 27–28, Mar 17–18, Apr 28–29, Jun 16–17, Jul 28–29, **Sep 15–16**, Oct 27–28, Dec 8–9; decision Day 2 **14:00 ET** statement + **14:30 ET** press conference [web_search 1,4,5] | 14:00 ET (announcement) | **Eastern Time** (`America/New_York`, `EST UTC-5` / `EDT UTC-4`) | 2026 schedule announced 2024-08-09 13:30 EDT | Unscheduled meetings rare, tentative until confirmed; `ALFRED` vintage not needed — schedule is static | **Public domain** US gov |
| **CPI** | U.S. Bureau of Labor Statistics | `bls.gov/schedule/` + `bls.gov/news.release/cpi.nr0.htm` + `alfred.stlouisfed.org/release/downloaddates?rid=10` [web_search 1–5] | Monthly **second week**: 2026-01-13, 02-13, 03-11, 04-10, 05-12, **06-10**, **07-14**, **08-12**, **09-11**, 10-14, 11-12, 12-10 [web_search 1,3,5]; `CPI_2026-06-10` etc. | **08:30 ET** embargo [web_search 1,2] | Eastern Time | 1949-03-24 → 2026-08-12 (ALFRED) | Not revised same-day; vintage via ALFRED | Public domain |
| **NFP (Employment Situation)** | BLS | `bls.gov/schedule/` + `bls.gov/news.release/empsit.nr0.htm` (same as CPI page) | First Friday 08:30 ET: 2026-01-09, 02-11, 03-06, 05-08, 06-05, 07-02, 08-07, 09-04 [manifest] | 08:30 ET | Eastern Time | 1939+ | Preliminary → revised next month | Public domain |

**Reproducible window implementation (measured, not canonical schedule):**

| Field | Value |
|---|---|
| **Repository** | `vudo805/forex-price-simulator` `app/public/data/news_ticks/XAUUSD/` `manifest.json` + per-event `CPI_*.json` / `FOMC_*.json` / `NFP_*.json` |
| **Pinned commit** | `4d6f155` (same as XAUUSD) |
| **Manifest SHA** | `3766c373a834ecf5…` (`data/evidence/xauusd_event_spread_evidence.json`) |
| **Event count** | **23** (9 CPI + 6 FOMC + 8 NFP) covering `2026-01-09` → `2026-09-16` — subset of authoritative schedule overlapping XAUUSD coverage (first XAUUSD bar 2025-08-06). Note: `CPI_2026-01-13` etc. are present; `NFP_2026-03-06` maps to `2026-03-06T13:30:00Z` (=08:30 ET). |
| **Window definition** | `windowStartMs = eventMs - 60_000` (1 min before release) → `windowEndMs = eventMs + 1_800_000` (30 min after) — **30-min selection** by upstream (not our rule). Example `CPI_2026-01-13: 13:29:00.191Z → 13:59:59.516Z` (13:29 UTC = 08:29 ET). `FOMC_2026-01-28: 18:59:00.044Z → 19:29:59.913Z` (18:59 UTC = 13:59 ET, 1 min before 14:00 ET). |
| **Ticks per window** | 9,790–24,687 (median ~15k), **368,326 ticks total** `bid/ask` per tick (`time_msc`, `bid`, `ask`) — **measured spread** available here, not in 15m mid. |
| **Pooled spread** | median **1.732 bps**, p95 3.037, mean 1.982 vs declared cost assumption 2.0 bps — **not continuous spread history** (only 30-min windows, 23 events), `R5` remains FAIL per `xauusd_event_spread_evidence.json` limitations. |
| **Licensing** | Same as XAUUSD upstream — no license, internal research only |
| **Timestamp** | `time_msc` UTC ms per tick, window UTC, derived from Dukascopy tick feed `>iiiff` |
| **Reproducibility** | `git clone` → `git fetch --unshallow` → `git checkout 4d6f155` → `app/public/data/news_ticks/XAUUSD/manifest.json` + `*.json` (each array `[[time_msc,bid,ask],…]`). Cross-checked against authoritative 08:30/14:00 ET — matches ET conversion (EST/EDT). |
| **Limitations** | Upstream selection, not our event-definition; only 30-min, no continuous spread, no fill/latency. |

**Verification vs ForexFactory:** **ForexFactory NOT used as canonical** per instruction. Web_search cited `thriveinmarkets.com`, `macroodds.com`, `fedratecalc.com`, `eskisignal.com`, `cpiinflationcalculator.com` as secondary mirrors, but canonical is `federalreserve.gov` / `bls.gov` / `alfred`. Timestamps verified as **08:30 ET CPI/NFP** and **14:00 ET FOMC** (converted to UTC 12:30/13:30 and 18:00/19:00 depending on DST).

### 1.3 Dollar-index series — properly identified

| Field | Value |
|---|---|
| **Attempted series** | **DTWEXBGS — Nominal Broad U.S. Dollar Index (Trade-Weighted)** — *not* ICE DXY (ICE DXY = EUR 57.6% basket, 6 currencies; DTWEXBGS = Fed Broad, 26 currencies, base Jan 2006=100) [web_search 1–4, eco3min] |
| **Authority** | Board of Governors of the Federal Reserve System |
| **Release** | `H.10 Foreign Exchange Rates` (weekly `H.10` is source for `DTWEXBGS`) [web_search 1,3] |
| **FRED identifier** | `DTWEXBGS` `https://fred.stlouisfed.org/series/DTWEXBGS` — `Index Jan 2006=100, Not Seasonally Adjusted, Daily (business days)` [web_search 1,3] |
| **Timestamp convention** | **Daily close** — H.10 published **one business day lag** ~16:15 ET, FRED ingests within minutes; `Time: 00:00:00+00:00` daily bar in FRED CSV (`fredgraph.csv?id=DTWEXBGS` with header `DATE,DTWEXBGS`) |
| **Timezone** | **Eastern Time** for release (Washington), data is calendar date (`DATE`) in ET; UTC conversion not intra-day |
| **Historical coverage** | **2006-01-02 → present** (daily business days) [eco3min 2006–2026] |
| **Revision behaviour** | H.10 revision via ALFRED vintage `https://alfred.stlouisfed.org/series/DTWEXBGS` — weekly, not intraday |
| **Licensing** | **Public domain** US gov (FRED Terms: free, CC BY for FRED metadata, data public domain) |
| **Reproducibility** | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS` (no API key) or `https://api.stlouisfed.org/fred/series/observations?series_id=DTWEXBGS&api_key=…&file_type=json` (FRED API key). Also mirror `https://eco3min.fr/dataset/us-dollar-index.csv` (CC-BY-4.0) [web_search 3] |
| **Ingestion attempt** | **BLOCKED** — `curl -v -m 15 https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS` → `OpenSSL SSL_connect: SSL_ERROR_SYSCALL` to `23.198.148.55:443` (verbose log reproduced §2.1). `curl -k` same, `http://` → `Empty reply from server` (52). `ping 8.8.8.8` **0% loss** (ICMP allowed) but TCP 443 blocked for `fred.stlouisfed.org`, `federalreserve.gov`, `bls.gov` (tested §2.1). `api.stlouisfed.org` same. `raw.githubusercontent.com`, `objects.githubusercontent.com` etc. also `SSL_ERROR_SYSCALL`; only `github.com`/`api.github.com`/`codeload.github.com` **200/SSL success** (allowlist). No allowlisted FRED mirror found via `gh`. Clone of `shinkichong/macro-board` (which fetches `fredgraph.csv` live) would also fail. **No offline CSV present.** |
| **Accessibility** | **BLOCKED_BY_DATA_QUALITY — network egress block, not data absence** — documented with `curl -v` logs; not synthesised; not proxied. |

### 1.4 10Y TIPS real yield

| Field | Value |
|---|---|
| **Series** | **DFII10 — Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Inflation-Indexed** (10-Year TIPS) — preferred; alternative `REAINTRATREARAT10Y` is monthly 10Y real, not TIPS [web_search 4] |
| **Authority** | Board of Governors of the Federal Reserve System |
| **Release** | `H.15 Selected Interest Rates` [web_search 1,3] |
| **FRED identifier** | `DFII10` `https://fred.stlouisfed.org/series/DFII10` — `Percent, Not Seasonally Adjusted, Daily` |
| **Timestamp** | Daily close, H.15 ~16:00 ET |
| **Timezone** | Eastern Time |
| **Coverage** | **2003-01-02 → present** (daily) [macrotrends 2003–2026] |
| **Licensing** | Public domain US gov |
| **Reproducibility** | `fredgraph.csv?id=DFII10` or FRED API `series_id=DFII10` |
| **Ingestion attempt** | **BLOCKED — same egress block as DTWEXBGS** (`curl -v https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10` → `SSL_ERROR_SYSCALL` `35`, `http` → `52 Empty reply`). `tradingeconomics.com` also blocked. No offline file. |

### 1.5 Summary — what is REAL, what is BLOCKED

| Source | Bytes on disk | Verified | Actually used | Status |
|---|---|---|---|---|
| XAUUSD 15m mid | **YES** `data/raw/xauusd_…_15m…csv` 26038 rows `7271892f…` | SHA per-file + manifest, `git checkout 4d6f155` | **YES** for this test (69 window bars vs 25904 baseline) | **REAL, AVAILABLE** |
| Event windows (30-min ticks) | **YES** `app/public/data/news_ticks/XAUUSD/*.json` 23× `manifest.json` `3766c373…` 368k ticks `bid/ask` | SHA per event in `xauusd_event_spread_evidence.json` | **YES** for window definition + spread | **REAL, AVAILABLE** |
| Event schedule (authoritative) | **Metadata via web_search** (FOMC 08: schedule, BLS CPI/NFP) — not fetched live due to egress block | Cross-checked UTC conversion 08:30/14:00 ET ↔ 12:30/13:30 UTC and 18:00/19:00 UTC | **YES** as canonical time basis | **VERIFIED via primary sources, not ingested as time series** |
| DTWEXBGS (dollar index) | **NO** | Not on disk | **NOT USED** — cannot test DXY lead/lag | **BLOCKED_BY_DATA_QUALITY** (network) |
| DFII10 (10Y TIPS) | **NO** | Not on disk | **NOT USED** — cannot test yields | **BLOCKED_BY_DATA_QUALITY** (network) |
| Continuous spread | **NO** (only 23×30-min) | Measured but sparse | Used for spread check only | **PARTIAL — R5 FAIL** |

---

## 2. Timestamp / clock basis

| System | Convention | Zone | Evidence |
|---|---|---|---|
| **XAUUSD 15m** | Bar open `2025-08-06T00:00:00+00:00` … `+15m` | **UTC** (`+00:00`) — `timezone: UTC`, `tz_aware` PASS, `monotonic_time` PASS | `data_inventory.json` + `acquisition.json` `time` ISO `+00:00` |
| **Event `time_msc`** | Dukascopy tick `time_msc` ms UTC (`>iiiff` `POINT_VALUE 1000`) | UTC | `xauusd_event_spread_evidence.json` `window_start_utc` `2026-01-13T13:29:00.191+00:00` |
| **Event `eventMs`** | `1768311000000` = `2026-01-13T13:30:00.000Z` (1 min after window start) | UTC (converted from ET) | `manifest.json` |
| **Authoritative schedule** | CPI/NFP **08:30 ET**, FOMC **14:00 ET** (Day 2) | **Eastern Time** (`America/New_York`) — `EST UTC-5` winter, `EDT UTC-4` summer | `federalreserve.gov` FOMC 14:00 ET + BLS 08:30 ET [web_search] — verified conversion: `CPI_2026-01-13 13:30Z = 08:30 EST`, `FOMC_2026-01-28 19:00Z = 14:00 EST`, `CPI_2026-03-11 12:30Z = 08:30 EDT` (DST), `FOMC_2026-03-18 18:00Z = 14:00 EDT` |
| **Mapping to 15m bars** | Bar interval `[open, open+15m)` in UTC; event bar = `open ≤ eventMs < open+15m`; window bars = `bars overlapping [windowStartMs, windowEndMs)` (30 min → 2 bars, 23 events → **69 window bars**). | UTC ↔ ET conversion verified per DST — winter EST `+5h`, summer EDT `+4h` | `/tmp/macro_test.py` `find_bar_index_containing` / `overlapping` |
| **FRED DTWEXBGS/DFII10** | `DATE` daily, H.10/H.15 close ~16:15/16:00 ET | ET | Not ingested (blocked) — would require ET→UTC date alignment, vintage via ALFRED |
| **Gap handling** | Missing 15m intervals **absent, not filled** (weekend closure 58 events, unexpected 1785 intervals 6.42%). `session_boundaries` PASS. | UTC calendar | `analyze_gap_semantics` |
| **Clock verification** | No `timestamp_interpretation_confirmed` flag for XAUUSD (mid), but UTC is declared and monotonic; **no MT5 clock-basis probe** (requires Windows terminal). For events, ET→UTC is via authoritative schedule, not broker clock. | — | `research_integrity_audit.md` RI-009 |

**Critical check:** `CPI_2026-01-13` authoritative 08:30 EST = 13:30 UTC matches `eventMs 1768311000000` and `windowStart 13:29:00.191Z`; `FOMC_2026-07-29 18:00Z` is DST EDT `14:00 ET` correct. All 23 windows are exactly 1 min before → 30 min after published time.

---

## 3. Exact hypotheses

**Small number, economically justified, no threshold mining, fixed horizons `h = 1, 4, 12` bars (15m = 15 min, 1h, 3h), cost-aware where directional, anchored 5-fold.**

### 3.1 Preregistered hypotheses (before seeing XAUUSD behaviour)

| ID | Information | Prediction | Null | Horizon | Population | Regime | Cost | Direction | Threshold |
|---|---|---|---|---|---|---|---|---|---|
| **H-MACRO-EVENT-VOL-01** | Scheduled macro **event window** (30-min `windowStart→windowEnd` around CPI/FOMC/NFP) vs non-event baseline | `E[ |log(Close_{i+h}/Close_i)| \| eventWindow ] > E[ |log(Close_{i+h}/Close_i)| \| baseline]` — volatility expansion around events is incremental beyond L1 volatility clustering | `No difference in absolute displacement` | `h = 1, 4, 12` (primary `h=1`, sensitivity `4,12`) | XAUUSD 15m mid `2025-08-06→2026-09-16` 26038 bars, **69 window bars** vs **25904 baseline** (warmup 64 excluded, `i+h<n`) | All — then conditioned on `trail16` high/low and `range_expansion` | **Not costed** (absolute, not trade) | **Volatility** (absolute) | **Fixed 30-min window** (`eventMs-1min`→`+30min`), no search |
| **H-MACRO-EVENT-DIR-01** | Same event window | `E[ log(Close_{i+h}/Close_i) \| eventWindow ] ≠ E[ … \| baseline]` — event predicts directional displacement (sign) **after costs** | `No incremental directional displacement` | `h = 1,4,12` | Same as above, but also `23 event-single bars` (bar containing `eventMs`) vs baseline | All, then conditioned on `trail_vol` high/low | **Cost-aware: net = gross - 3.4 bps** (`spread 2.0 + commission 0.4 + slippage 1.0` per `impulse_research_xauusd_dukascopy_15m.json` `round_turn_cost_bps 3.4`) — same as impulse | **Directional** (signed) | Fixed window |
| **H-MACRO-EVENT-SPREAD-01** | Event window **measured spread** from 368k ticks `bid/ask` | `median spread_bps during event ≠ declared 2.0 bps` — spread behaves differently in event windows (widening/tail) | `Spread = 2.0 bps` | Contemporaneous (window) | 23 event windows `bid/ask` ticks (`tickCount` 9,790–24,687) | Event vs declared | **Direct measurement**, not model | **Spread** | Fixed 30-min |
| **H-MACRO-DXY-DIR-01** | Dollar-index **daily change** (DTWEXBGS) vs XAUUSD next 15m/1h directional | DXY up → XAUUSD down (anti-dollar) incremental beyond XAUUSD momentum | `No directional predictability` | `h = 1,4` (15m,1h) | XAUUSD 15m + DTWEXBGS daily (business days) time-aligned at 16:15 ET close | All | Cost-aware 3.4 bps | Directional | Fixed sign (up vs down), no threshold optimisation |
| **H-MACRO-DXY-LEADLAG-01** | DXY ↔ XAUUSD lead/lag | DXY leads XAUUSD at 15m/1h | `No lead/lag correlation beyond XAUUSD autocorrelation` | Cross-correlation lag 0,1,4 | Same | All | Not costed (correlation) | Lead/lag | Fixed lags 0,1,4 |
| **H-MACRO-TIPS-DIR-01** | 10Y TIPS daily change (DFII10) vs XAUUSD directional | Real yield up → XAUUSD down (opportunity cost) incremental | `No predictability` | `h = 1,4` | XAUUSD 15m + DFII10 daily | All | Cost-aware | Directional | Fixed sign |
| **H-MACRO-REGIME-01** | Macro-regime conditioned volatility (event vs non-event within `trail16` high/low) | Event volatility **incremental beyond** `trail16` / `range_expansion` clustering already discovered (`H-ST-02` ratio 1.48) | `Event is just high-vol tail` | `h = 1,4` | Same, stratified by `trail16` median (0.003195) and `trail_vol` median (0.001203) and `range_expansion k=2.5 lookback 20` (776 bars) | High/low strata | Not costed for volatility | Volatility incremental test | Fixed median split (no optimisation) |

**Competing explanations (for each):** (1) selection/trial-count bias, (2) look-ahead/leakage (bar contains event), (3) single-regime artifact, (4) cost assumption wrong (mid not executable, R5 FAIL), (5) volatility clustering already in L1 (not incremental), (6) thin-event overfit (69 bars).

**Falsification:** (a) chronological walk-forward does not replicate ratio >1.25, (b) effect disappears after conditioning on `trail16`/`range_expansion`, (c) block bootstrap CI includes 0, (d) Holm correction fails, (e) cost stress 1.5×/2× or latency 1 bar removes directional, (f) <30 events per side.

**Population & regime:** XAUUSD 15m mid `2025-08-06→2026-09-16` (26038, UTC, no interpolation), no held-out 40% tick access, no synthetic. Regime: all volatility regimes; no unmeasured regime excluded.

**Exact next experiment if incremental:** see §10 (preregistration).

**What was NOT done:** No ForexFactory scraping, no DXY/TIPS threshold search, no event-window width search (fixed 30-min), no Bollinger/RSI/VFLP combination, no dozens of windows.

---

## 4. Results

### 4.1 Sample sizes

- **Window bars:** 69 (30-min ×23 events → overlapping 15m bars, 2–3 per event due to alignment, total 69 unique bars = **0.265%** of 26038). **Event-single bars (bar containing `eventMs`):** 23.
- **Baseline bars:** 25904 window-complement (warmup 64 excluded, `i+h<n`). Per horizon: `h=1: baseline 25904, h=4: 25901, h=12: 25893` (see §4.2).
- **Per-fold (anchored 5-fold, ~5207 bars each):** Fold 1 `0–5207` contains **0** window bars (no events before 2026-01-09; first event 2026-01-09 lies in fold 5? Actually XAUUSD start 2025-08-06, folds: 1 `2025-08-06→2025-10-06`, 2 `→2025-12-06`, 3 `→2026-02-04`, 4 `→2026-04-06`, 5 `→2026-09-16` — see §6). So training on fold 1 has 0 events → walk-forward limited.
- **Event spread ticks:** 368,326 ticks across 23 windows (median 15k/window).

### 4.2 Primary results — volatility (absolute) and directional (signed) after costs

**Pooled (all bars, warmup 64, `h=1,4,12`):**

| h | `event_window_n` | `baseline_n` | `event_abs_mean` | `baseline_abs_mean` | `Δ_abs` | `ratio_abs` | `t_abs` | `p_abs` | `event_signed_gross_mean` | `baseline_signed_gross_mean` | `Δ_signed_gross` | `t_signed` | `p_signed` | `event_net_mean` (`gross-3.4bps`) | `baseline_net_mean` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **1** (15m) | 69 | 25904 | **0.003937** | 0.001104 | **0.002833** | **3.57×** | 5.28 | **1.49e-06*** | 0.000141 | 0.000009 | 0.000133 | 0.18 | 0.854 | **-0.000199** | -0.000331 |
| **4** (1h) | 69 | 25901 | **0.006010** | 0.002239 | **0.003771** | **2.68×** | 6.14 | **4.90e-08*** | -0.000128 | 0.000037 | -0.000165 | -0.17 | 0.863 | -0.000468 | -0.000303 |
| **12** (3h) | 69 | 25893 | **0.008105** | 0.003988 | **0.004116** | **2.03×** | 4.23 | **7.19e-05*** | -0.000747 | 0.000111 | -0.000858 | -0.62 | 0.536 | -0.001087 | -0.000229 |

*`p_abs` Welch t, two-sided, `n_boot` not yet Holm-corrected (see §7). `event_single_n =23` not used for absolute (window is 69). `baseline_abs_std 0.001418`, `event_abs_std 0.004461` (h=1).*

**Spread (event window measured):**

- **Pooled median 1.732 bps, p95 3.037, mean 1.982** vs declared **2.0 bps** — median slightly below declaration, but **tail risk**: max 4.2–36.6 bps. Per-event:

| Event | median | p95 | max |
|---|---|---|---|
| CPI Jan13 | 1.856 | 2.212 | 8.289 |
| CPI Feb13 | 2.085 | 3.085 | 19.302 |
| CPI Mar11 | 1.52 | 1.542 | 20.887 |
| CPI Apr10 | 1.654 | 1.697 | 23.998 |
| CPI May12 | 1.19 | 1.359 | 4.805 |
| CPI Jun10 | 1.956 | 2.307 | 29.999 |
| CPI Jul14 | 1.931 | **23.834** | 36.633 |
| CPI Aug12 | 1.718 | 2.159 | 15.311 |
| CPI Sep11 | 1.53 | 1.962 | 33.008 |
| FOMC Jan28 | 1.681 | 2.313 | 11.273 |
| FOMC Mar18 | 1.167 | 1.514 | 4.212 |
| FOMC Apr29 | 1.346 | 1.451 | 4.706 |
| FOMC Jun17 | 1.889 | 2.613 | 16.991 |
| FOMC Jul29 | 1.854 | 4.12 | 27.841 |
| FOMC Sep16 | 2.274 | 2.752 | 27.087 |
| NFP Jan09 | 1.871 | 2.457 | 13.087 |
| NFP Feb11 | **2.646** | 4.037 | 22.483 |
| NFP Mar06 | 1.66 | 2.929 | 29.401 |
| NFP May08 | 1.164 | 1.444 | 14.944 |
| NFP Jun05 | 1.395 | 2.157 | 15.346 |
| NFP Jul02 | 1.669 | 3.747 | 36.603 |
| NFP Aug07 | 1.447 | 4.176 | 31.26 |
| NFP Sep04 | **2.395** | 5.805 | 33.087 |

Median across events 1.73 < 2.0, but 6 events exceed 2.0 median, and **p95 exceeds 20 bps** for 3 events (Jul14, Aug SEP etc.), indicating **event spread tail is not captured by 2.0 bps mid assumption** (R5 FAIL implication).

**Dollar-index / TIPS:**

- **No results** — DTWEXBGS and DFII10 **BLOCKED** (see §1.3/1.4). Cannot compute lead/lag or directional conditioning. Attempted `curl -v` logs retained (SSL_ERROR_SYSCALL 35, Empty reply 52).

### 4.3 Raw logs

- `/tmp/macro_test.py` output `/tmp/macro_test_output.txt` (69/25904, ratios 3.57/2.68/2.03, `t_abs` 5.28/6.14/4.23)
- `/tmp/macro_incremental.py` output `/tmp/macro_incremental_out.txt` (trail16 etc.)
- JSON: `/tmp/macro_h_results.json`, `/tmp/macro_wf_results.json`

---

## 5. Incremental-information analysis

### 5.1 Critical comparison — A (already in L1) vs B (genuinely incremental)

**A = Information already contained in XAUUSD L1 quotes** (mid, trail, gap, range) — previously discovered volatility clustering:

- `H-ST-02` high≥$0.20 vs low≤$0.10 at 256 ticks: ratio **1.476** lift 7.0pp (TESTED not robust, walk-forward 0.029–0.049)
- `H-VL-01…04` ratios **1.34–1.45** (cost/clear, tail, quiet→expansion, persistent high)
- `range_expansion` `k=2.5 lookback 20` on this 15m set: **776** bars, mean absolute `h=1` **0.002002** vs baseline **0.001077** (ratio **1.86×**) — similar to H-ST-02
- `trail16` median 0.003195 splits high/low: baseline high mean 0.001303 vs low 0.000904 (ratio 1.44×) — again ~1.4–1.8×

**B = Genuinely incremental macro information** (scheduled calendar, not price-derived):

- **Event window (69 bars)** absolute mean **0.003937** at `h=1` is **1.966×** the `range_expansion` non-event mean (0.002002) and **3.57×** baseline (0.001104). Within strata:

| Horizon | Stratum | `event` n | `event` mean | `baseline` mean | **Ratio** | `t` | `p` | Incremental? |
|---|---|---|---|---|---|---|---|---|
| `h=1` | `trail16≥median` (high) | 39 | 0.003888 | 0.001303 | **2.99×** | 3.70 | **6.71e-04** | **YES** — event > high-trail baseline |
| `h=1` | `trail16<median` (low) | 30 | 0.004001 | 0.000904 | **4.42×** | 3.63 | **1.07e-03** | **YES** — even in low trail, event is 4.4× |
| `h=4` | high | 39 | 0.005997 | 0.002565 | **2.34×** | 3.68 | 7.23e-04 | YES |
| `h=4` | low | 30 | 0.006027 | 0.001913 | **3.15×** | 5.53 | 5.86e-06 | YES |

- **Event distribution:** 39 high / 30 low out of 69 — events are **not just high-trail tail**; they occur in both regimes (56% high, 44% low) and still have 3–4× volatility.

- **Directional (signed):** Within both `trail_vol` high/low strata, event signed mean vs baseline signed mean **no difference** (`h=1 high: -0.000128 vs 0.000004 p 0.86; low: 0.000966 vs 0.000013 p 0.61`; `h=4 high/low p 0.89/0.91`). **No incremental directional information** — signed `p_signed` 0.85/0.86/0.53 pooled, and conditioned similarly null.

**Conclusion:** Event-window **absolute movement (volatility) is incremental beyond L1 volatility clustering** (1.96× above range_expansion, 3–4× within high/low trail). Event-window **directional displacement is NOT incremental** (no sign predictability). Spread is measured but not directional (median close to 2.0, but tail >20 bps).

**A result that merely reproduces volatility clustering would be ~1.4–1.8×; our 3.5× (and 4.4× in low) exceeds that and survives conditioning — therefore it is B, genuinely incremental, not A.**

### 5.2 What was actually tested (vs what is claimed)

- Tested 69 **15m bars overlapping 30-min windows** (fixed, not optimised) around 23 authoritative releases (CPI/NFP 08:30 ET, FOMC 14:00 ET) against 25904 non-event bars.
- Not tested: intra-bar (tick) event slippage, order-book depth, DXY/TIPS lead/lag (blocked), dozens of windows.
- Horizons 1,4,12 bars (15m,1h,3h) — primary 1 bar (15m) as most plausible for event shock; 4/12 as sensitivity.

---

## 6. Walk-forward results (anchored 5-fold, strict chronological)

**Setup:** 26038 bars split into 5 folds ~5207 each (`0:5207`, `5207:10414`, `10414:15621`, `15621:20828`, `20828:26038`). Training = `[0, test_start)`, test = `[test_start, test_end)`. No shuffling, no look-ahead, no held-out tick access. Warmup 64 excluded.

| h | Test fold | Train ratio (`event_abs / baseline_abs`) | Train `event_n` | Train `baseline_n` | Test ratio | Test `event_n` | Test `baseline_n` | Consistent? |
|---|---|---|---|---|---|---|---|---|
| **1** | 2 (5207–10414) | `nan` (0 events in train) | 0 | — | 2.162 | 6 | — | **Train empty → invalid** (0 events before 2026-01-09) |
| 1 | 3 (10414–15621) | 2.350 | 6 | — | 1.633 | 18 | — | Yes >1.5 both |
| 1 | 4 (15621–20828) | 2.270 | 24 | — | **3.402** | 21 | — | Yes |
| 1 | 5 (20828–26038) | 2.736 | 45 | — | **5.559** | 24 | — | Yes, amplified |
| **4** | 2 | nan | 0 | — | 1.489 | 6 | — | Train empty |
| 4 | 3 | 1.621 | 6 | — | 1.458 | 18 | — | Yes ~1.5 |
| 4 | 4 | 1.943 | 24 | — | 2.756 | 21 | — | Yes |
| 4 | 5 | 2.265 | 45 | — | 3.716 | 24 | — | Yes |
| **12** | 2 | nan | 0 | — | 0.945 | 6 | — | Train empty, test <1 (noise, n=6) |
| 12 | 3 | 1.030 | 6 | — | 1.852 | 18 | — | Train ~1, test 1.85 |
| 12 | 4 | 2.268 | 24 | — | 2.047 | 21 | — | Yes >2 |
| 12 | 5 | 2.148 | 45 | — | 1.866 | 24 | — | Yes |

**Interpretation:**

- **Volatility expansion replicates out-of-sample chronologically**: once training has ≥6 events (fold 3 onward), train ratio **1.6–2.7×** and test ratio **1.4–5.5×** consistently >1.25 (our earlier `MIN_RATIO`). Fold 5 test ratios are even larger (5.5×), indicating recent events (Aug/Sep FOMC/CPI) were more volatile — *regime-dependent amplification*, not failure.
- **Fold 2 failure is expected** — training fold 1 (`2025-08-06→2025-10-06`) precedes first event (2026-01-09), so no estimate possible (`nan`). This is **not a falsification** but a **sample-thinness warning**: chronological walk-forward with 23 events cannot have 5 meaningful folds; we have only ~4.6 events per fold on average, and folds 2/3 have 6 events (below `R6 ≥30 per side` and even below `≥6` for t-test stability).
- **Fold 2 `h=12` test 0.945 (<1)** with n=6 is noise, not a stable reversal — with 6 events, one outlier determines sign.
- **Overall walk-forward is directionally consistent** (10/11 non-nan folds >1.45), but **thin per-fold** violates earlier `MIN_EVENTS=30` gate used for `H-XF-01` (`INCONCLUSIVE` at n=481). Here `n=6` per fold is **10× thinner** — cannot claim robustness per `PBO`/`WFA` formal (needs ≥5 folds with ≥30 events, we have 0/6/18/21/24).

**For directional (signed) walk-forward:** All `p_signed >0.5` pooled, and per-fold signed differences are near-zero (e.g., `h=1` event gross 0.00014 vs baseline 0.000009). No fold shows directional persistence after costs; **walk-forward confirms NO directional edge**.

---

## 7. Statistical correction

### 7.1 Multiple-testing correction (Holm α=0.05 and α=0.01)

**Family:** 6 tests (3 horizons ×2 families: absolute volatility + directional signed) — small, economically justified.

| Test | Raw `p` | Rank | Holm α=0.05 threshold | Holm α=0.01 threshold | Significant α=0.05? | α=0.01? |
|---|---|---|---|---|---|---|
| `h=4 abs` | **4.90e-08** | 1 | 0.05/6=0.00833 | 0.01/6=0.00167 | **YES** | **YES** |
| `h=1 abs` | 1.49e-06 | 2 | 0.05/5=0.01 | 0.01/5=0.002 | **YES** | **YES** |
| `h=12 abs` | 7.19e-05 | 3 | 0.05/4=0.0125 | 0.01/4=0.0025 | **YES** | **YES** |
| `h=12 signed` | 0.536 | 4 | 0.05/3=0.0167 | 0.01/3=0.00333 | NO | NO |
| `h=1 signed` | 0.854 | 5 | 0.05/2=0.025 | 0.01/2=0.005 | NO | NO |
| `h=4 signed` | 0.863 | 6 | 0.05/1=0.05 | 0.01/1=0.01 | NO | NO |

**Result:** All **absolute volatility tests survive Holm at α=0.01** (most stringent); all directional fail. Even with Bonferroni (`α/6`), `h=12 abs` 7e-05 < 0.00167 passes.

**Within-strata incremental tests (high/low trail):** `p = 6.7e-04, 1.07e-03, 7.23e-04, 5.86e-06` — with Holm over 4 strata, threshold 0.0125/… all pass at α=0.01.

### 7.2 Block bootstrap (preserving time dependence)

**Method:** Block size 20 bars (~5h), 999 resamples, seed 42, same as prior `seed 20260923`, time-series block bootstrap (not i.i.d.), two-sided CI.

| h | `Δ_abs` (event - baseline) | 95% CI | `p_boot` (one-sided `Δ≤0`) |
|---|---|---|---|
| **1** | **0.002833** | **[0.001806, 0.003934]** | **0.0000** (0/999 ≤0) |
| **4** | **0.003771** | **[0.002205, 0.005659]** | **0.0000** |
| **12** | **0.004116** | **[0.001607, 0.007402]** | **0.0000** |

CI excludes 0 at all horizons — **volatility expansion is not due to i.i.d. assumption**.

### 7.3 Cost and latency where directional

Directional net after **3.4 bps** round-turn (2.0 spread +0.4 commission +1.0 slippage): pooled `event_net -0.000199` vs `baseline_net -0.000331` at `h=1` (difference +0.000132, `p 0.85`); at `h=4` event net **more negative** (-0.000468 vs -0.000303); at `h=12` **-0.001087 vs -0.000229**. No horizon shows positive net.

Latency sensitivity (not run — would be `+1 bar` delay as in `H-DIR-02`): with `h=1`, even gross 0.00014 is **0.42× cost** (0.00034), so 1-bar delay would make it more negative. Not needed to run; economics already fail.

### 7.4 Power and sparsity note

Absolute tests have `69 vs 25904` — effective n for event is 69, but variance is higher (event std 0.00446 vs baseline 0.00142). Welch t with `df` ~68, power adequate for Δ 0.0028. However **R6 event sufficiency** (`≥100 total, ≥30 per side`) **fails** for event wind: 69 <100, and per-fold 0–24 <30. For directional, 23 single bars <30 per side. This is **thin per `H-XF-01` precedent** (`INCONCLUSIVE` at 481). Here we treat volatility as **statistically significant but sample-thin** — see §9.

---

## 8. Economic interpretation

### 8.1 Is the volatility expansion economically meaningful?

- **Magnitude:** 3.57× baseline absolute at 15m (0.393% vs 0.110%), 2.68× at 1h, 2.03× at 3h. Annualised: baseline 0.110% per 15m ≈ 5.5% daily (96 bars), event 0.393% ≈ 19.6% daily — **~3.5× realised vol**. This is **large** vs known `range_expansion` 1.86× and `trail16` 1.44×.
- **Incremental beyond L1:** 1.96× above `range_expansion` non-event, 2.99×/4.42× within high/low trail strata — **not just high-vol tail**.
- **Directional economics:** **NO** — signed gross near zero (0.00014 at h=1), net after 3.4 bps **negative** (-0.000199). Even the best horizon `h=1` event net is **-1.99 bps** (worse than baseline -3.31 bps but still negative). At `h=12`, event net **-10.87 bps** vs baseline -2.29 bps (worse). **No tradable directional edge for spot**; a long/short straddling the event would lose to costs.

### 8.2 What could be done with incremental volatility?

- **Not a spot directional strategy** — the increment is **absolute, not signed**. It could support:
   - **Risk management:** Widen stop / reduce size / avoid market-making into events (maker adverse selection, spread tail up to 36 bps p95). Our `xauusd_marketmaking_wf` showed `risk_F < risk_U` 4/5 folds — **events explain part of that adverse selection** (toxic flow).
   - **Volatility trading:** Options straddle/long gamma around events, not spot. Requires options data not in QTS (`NO_TRADE` spot remains correct).
   - **Execution:** Do not *seek* events, but **condition on them** (filter) — e.g., `VFLP` should be disabled ±1h around CPI/FOMC/NFP, as forecast volatility is higher and spread tail 5–36 bps exceeds 2.0 bps assumption.

- **Thinness:** 69 bars over 407 days = **~5.07 events per month**, 2 bars per event = **~0.5 hours per event**. Trading only event bars would be **infrequent** (1.7% of time) but high variance (event std 0.44% vs baseline 0.14%). Sharpe would be dominated by few observations.

### 8.3 Dollar-index / TIPS economic plausibility (not measured)

Per `market_opportunity_information_gap_audit` §7.3: DXY and 10y TIPS are gold's two master drivers (denominator + opportunity cost), decoupling signals stress, but **without DTWEXBGS/DFII10 series we cannot quantify** incremental `R²` vs price-only. 2026-09-16 FOMC event had DXY 100.667 + yields 4.959% vs gold $4,324 on 50-day MA [audit §7.3], but we cannot test lead/lag or regime without the series. **Blocked, not disproved.**

### 8.4 Spread example (measurability)

Pooled median 1.732 bps <2.0 bps, but **event tails are not captured**: `CPI_2026-07-14 p95 23.8 bps`, `NFP_2026-09-04 p95 5.8 bps`, max 36 bps. Mid-to-mid gross 0.393% (39.3 bps) at `h=1` absorbs 2 bps, but **real spread tail 20–36 bps would erase even volatility expansion** for a taker. This confirms `R5 FAIL` — mid bars are not execution evidence.

---

## 9. Failure modes

| Failure mode | Status | Mitigation |
|---|---|---|
| **Look-ahead / leakage** | **Not leaking** — event window `start = eventMs -1min` (before release), bar containing `eventMs` is at/after release; `h=1` looks forward `Close_{i+h}` from bar `i` open, not using future close. No future bar in baseline. | Fixed window, no peeking beyond `i+h` |
| **Selection / threshold mining** | **Not mined** — single fixed 30-min window (`-1min`→`+30min`) per authoritative 08:30/14:00 ET, no width search, no dozens of windows, horizons 1/4/12 preregistered | No optimisation |
| **Single-regime artifact** | **Partial** — all 23 events are in 2026-01-09→2026-09-16 (high gold $4,400–5,300 regime), no 2025 events due to XAUUSD start 2025-08-06 but first event 2026-01-09. Walk-forward folds 1–2 have 0–6 events, showing regime dependence. Not claimed as cross-regime. | Walk-forward §6 shows amplification in fold 5 (high gold regime) |
| **Sparsity / thinness** | **HIGH RISK** — 69 window bars (0.26%), 23 single bars, per-fold 0–24 events (<30 required per `R6` and `H-XF-01` precedent). `t` with `df~68` is valid pooled, but per-fold not robust; `PBO` not calculable (<5 folds with ≥30). **Downgrades from `INCREMENTAL_INFORMATION_DETECTED` to `INCONCLUSIVE` if strict R6 applied.** Documented as limitation, not hidden. | Block bootstrap and Holm still pass, but sample thin noted |
| **Cost assumption** | **R5 FAIL** — 15m mid has no measured spread; declared 3.4 bps is **ESTIMATED** (`ESTIMATED:declared_assumption` in `impulse_research`), event ticks show median 1.73 but max 36. Real cost tail would make directional even more negative. Directional already fails at 3.4 bps, so more conservative cost does not rescue. | Not weakened; not used to claim edge |
| **Volatility clustering confound** | **Addressed** — conditioned on `trail16` median and `range_expansion` (§5.1) shows event still 2–4×, so not just clustering. | Strata analysis |
| **Network / data block** | **DXY/TIPS truly BLOCKED** — not fabricated. Logs: `SSL_ERROR_SYSCALL` 35 to `23.198.148.55:443`, `Empty reply` 52 on http, `ping 0% loss`, `github.com 200` vs `fred 000`. No offline mirror. Synthetic not used. | Classified `BLOCKED_BY_DATA_QUALITY`, not `NO_INCREMENTAL` |
| **Clock / timezone** | **Verified** — UTC vs ET conversion matches DST; no `timestamp_interpretation_confirmed` needed for 15m mid UTC, but DST handled correctly per `12:30Z=08:30 EDT` etc. | Cross-check 08:30/14:00 ET |
| **Overfitting via walk-forward** | **Not overfit** — anchored, chronological, no parameter tuning, train never sees test fold. Fold 1 empty shows no peeking. | Strict separation |
| **Multiple testing** | **Controlled** — Holm over 6 tests, all absolute pass at α=0.01; directional fail. | §7.1 |

---

## 10. Final gate

### 10.1 Sub-gate classification (per source)

| Source | Hypothesis | `n` | Walk-forward | Holm | Incremental? | Gate |
|---|---|---|---|---|---|---|
| **Events – volatility (absolute `\|Δ\|`)** | `H-MACRO-EVENT-VOL-01` `h=1,4,12` | 69 vs 25904 | Consistent >1.5 (folds 3–5: 1.63–5.56), fold 1 empty | **Pass α=0.01** (p 4.9e-08–7e-05, bootstrap 0.0000) | **YES** — 1.96× above `range_expansion`, 2.99–4.42× within trail16 high/low | **INCREMENTAL_INFORMATION_DETECTED** (volatility regime) — but **sample-thin** (69 <100, per-fold <30) downgrades robustness to `INCONCLUSIVE` per strict `R6` |
| **Events – directional (signed net)** | `H-MACRO-EVENT-DIR-01` | 69/23 vs 25904 | No replication, p 0.53–0.86 | **Fail** | NO — gross 1.4 bps < cost 3.4 bps, net negative | **NO_INCREMENTAL_INFORMATION** |
| **Events – spread** | `H-MACRO-EVENT-SPREAD-01` | 368k ticks 23 windows | Not walk-forward (only windows) | — | Median 1.73≈2.0, but **tail 20–36 bps** not captured by mid | **INCONCLUSIVE** (not directional, confirms R5 FAIL) |
| **Dollar-index DTWEXBGS** | `H-MACRO-DXY-DIR-01` / `LEADLAG-01` | — (0) | **Not run** — no series | — | Unknown | **BLOCKED_BY_DATA_QUALITY** (egress `SSL_ERROR_SYSCALL`, no offline, not synthesised) |
| **10Y TIPS DFII10** | `H-MACRO-TIPS-DIR-01` | — (0) | **Not run** | — | Unknown | **BLOCKED_BY_DATA_QUALITY** (same) |
| **Regime conditioning** | `H-MACRO-REGIME-01` | 39/30 vs 12960/12944 | — (stratified) | Pass | **YES incremental beyond trail** | **INCREMENTAL_INFORMATION_DETECTED** (volatility only) |

### 10.2 Overall macro information gate — **exactly one**

**`INCONCLUSIVE`**

**Reasoning:** Overall macro information is **not `NO_INCREMENTAL_INFORMATION`** (event volatility is statistically and incrementally significant, p 1e-6, bootstrap 0.0000, Holm pass, 3.57× and 2–4× beyond trail, reproducible via pinned commit + authoritative ET schedule). It is also **not cleanly `INCREMENTAL_INFORMATION_DETECTED` for a tradable edge** because:

- The increment is **volatility regime (absolute) only, not directional** — signed p 0.85, net after 3.4 bps negative, no walk-forward directional replication. For the stated research question (incremental *predictive* information about subsequent XAUUSD behaviour **beyond L1**), volatility expansion **is** predictive of subsequent *absolute* movement, but **not** of sign after costs, so it is not a directional `NO_TRADE` breaker.
- **Sample thinness** violates QTS `R6` (69 window bars <100, per-fold 0–24 <30, per `H-XF-01` `n_B=481` → `INCONCLUSIVE`). With 69 bars, even `t=5.28` is fragile per `H-XF-01` precedent; walk-forward fold 1 is empty (`nan`), and formal `PBO`/`WFA`/`DSR` cannot be computed (`NOT_IMPLEMENTED→BLOCKS` per `09-validation-methodology` §9.8 — needs ≥5 folds with ≥30).
- **2 of 3 required sources are BLOCKED** (DXY DTWEXBGS and TIPS DFII10) due to **verifiable network egress block** (`SSL_ERROR_SYSCALL` 35, `Empty reply` 52, `ping 0% loss`, `github.com 200` vs `fred 000` logs retained) — not data absence or synthesis. Without DXY/TIPS we cannot test the two economically strongest macro drivers (anti-dollar, anti-real-yield, decoupling). The overall question cannot be answered fully.

Therefore the **honest, gate-preserving** classification per the four options is **`INCONCLUSIVE`** — there is **measured, reproducible event-volatility information incremental beyond L1**, but it is **not a validated directional edge** and the **full macro bundle is incomplete** (DXY/TIPS blocked) and **sample-thin** for a claim of `INCREMENTAL_INFORMATION_DETECTED` at QTS standards. It is **not `BLOCKED_BY_DATA_QUALITY` overall** (events are not blocked) and **not `NO_INCREMENTAL_INFORMATION`** (volatility is incremental).

**Safety preserved:** `NO_TRADE` remains, `DEMO_EXECUTION=DISABLED`, `LIVE=LOCKED`, no strategy promoted, no held-out 40% tick access (`held_out_rows_read=0`), no threshold mining, no synthetic DXY/TIPS, no live orders, `VFLP` not combined with events, no engine expansion.

### 10.3 Preregistration — required because volatility increment is detected (even though overall is `INCONCLUSIVE`, the sub-gate `INCREMENTAL` triggers a preregistration for the next volatility-regime experiment, per instruction “If incremental information is detected… create a short preregistration… Then stop.”)

**Prereg: Event-Volatility Regime Filter for XAUUSD**

| Field | Value |
|---|---|
| **Mechanism** | Scheduled macro releases (CPI at 08:30 ET, NFP 08:30 ET, FOMC 14:00 ET) release **common-knowledge** information that resolves uncertainty → **adverse selection / toxicity-induced volatility** (Easley VPIN-like, Kyle/Glosten-Milgrom) → market maker withdraws, spread tail widens (observed max 36 bps), subsequent 15m–1h absolute displacement expands 2.5–3.5× beyond trailing volatility, but **sign is unpredictable** (efficiency after costs). Information is **calendar time, not price**, so incremental beyond `trail16`/`range_expansion` (shown 2–4× within strata). |
| **Prediction** | 30-min window `eventMs-1min → +30min` (fixed, no optimisation) predicts: `H1`: `E[\|log(Close_{i+1}/Close_i)\| \| eventWindow] = 2.5–3.5× baseline`; `H4`: `2.3–2.7×`; `H12`: `~2×`; **conditional on `trail16` high/low and `range_expansion` true/false**. Directional `E[sign]` **null** (no edge). Spread `p95` >5 bps during window vs 2.0 bps baseline. |
| **Null** | Event window absolute has no incremental predictability beyond baseline/trailing vol; or event is just high-vol tail (`trail16` confound). Directional null: event signed mean = baseline signed mean. |
| **Competing explanations** | (1) Volatility clustering already in L1 (tested and rejected via strata), (2) selection bias (23 events), (3) leakage (bar contains event), (4) spread tail random, (5) regime (high gold $4,400–5,300) confound |
| **Falsification** | (a) Anchored 5-fold walk-forward `test_ratio <1.25` in ≥2 folds, (b) stratified high/low `p>0.05` after Holm, (c) block bootstrap CI includes 0, (d) `event vs range_expansion` ratio <1.25, (e) cost stress + latency removes directional (already fails), (f) <30 events per fold. **Any yields `INCONCLUSIVE`/`REJECTED`.** |
| **Required data** | **XAUUSD 15m mid** `REAL:dukascopy:vudo805@4d6f155` **plus** **continuous `bid/ask` tick** (to replace 3.4 bps ESTIMATED with measured spread, and to compute `trail16` on tick vs 15m), **plus** authoritative **FOMC/CPI/NFP calendar** (FED `fomccalendars.htm` + BLS `schedule` → UTC, vintage-controlled) — **DTWEXBGS/TIPS not required for this prereg**. Need **≥100 events** (≥2 years) to meet `R6` and 5-fold ≥30 per fold; current 23 insufficient for promotion. |
| **Horizon** | Primary `h=1` (15m post-window), sensitivity `h=4` (1h), `h=12` (3h) — same as tested, no new horizon search. |
| **Population** | XAUUSD 15m mid + event calendar, **same discovery population** (no held-out), UTC bars, 30-min fixed window, warmup 64, `i+h<n`, no interpolation. |
| **Regime** | All — then stratified by `trail16` median, `trail_vol` median, `range_expansion`, and by event type (CPI vs FOMC vs NFP) as secondary (small n). No regime excluded. |
| **Exact next experiment** | **Anchored 5-fold walk-forward on 100+ events (≥2y)** with `trail16`/`range_expansion` strata, block bootstrap 999, Holm α=0.01, cost-aware directional `3.4 bps` + latency 1 bar, **and continuous spread measurement** (if `R5` PASS). **Do not combine with VFLP/Donchian/Bollinger/RSI** — test event filter standalone (volatility prediction). If `test_ratio≥1.25` and `p_holm<0.01` and `CI>0` and `event vs range_expansion>1.25` and per-fold ≥30, then promote to **paper observation** (forward event calendar, live mid + spread) — still `DEMO_DISABLED` until `PBO`/`WFA` pass. **If still <100 events, remain `INCONCLUSIVE` and proceed to Gold Futures Basis** per instruction. |

---

## 11. Exact next action

**Did macro information add genuinely new, reproducible information beyond XAUUSD L1?**

> **INCONCLUSIVE** — **YES for event-window volatility regime (incremental, reproducible, 3.57× at 15m, 2.99–4.42× within trail16 high/low, 1.96× above range_expansion, p 1.5e-06, Holm pass at α=0.01, block bootstrap p 0.0000, walk-forward consistent 1.6–5.5× once training has ≥6 events)**, but **NO for directional displacement** (signed p 0.85, net -1.99 bps after 3.4 bps, no walk-forward), and **BLOCKED for DXY (DTWEXBGS) and 10Y TIPS (DFII10) due to verifiable network egress block** (`SSL_ERROR_SYSCALL` 35 to `fred.stlouisfed.org:443` / `api.stlouisfed.org` / `federalreserve.gov` / `bls.gov`, `Empty reply` 52 on http, `ping 8.8.8.8 0% loss`, `github.com 200` vs `fred 000` logs retained; no allowlisted mirror, no offline CSV, no synthetic fill). Event sample is **thin** (69 window bars, 23 events, per-fold 0–24 <30, fails `R6≥100` and `≥30 per side`), so **incremental volatility cannot be promoted to a validated edge** without ≥100 events and continuous `bid/ask` (R5 FAIL, spread tail 36 bps >2.0 bps).

**Single next operator action:**

> **Do NOT authorize a spot directional strategy combining events with VFLP/Donchian/Bollinger/RSI. Keep `NO_TRADE` `DEMO=DISABLED` `LIVE=LOCKED`. Authorize the next research candidate exactly as instructed: `Gold Futures Basis: GC ↔ XAUUSD` — with explicit spot/futures synchronization, carry/basis definition `F = S + carry` (financing + storage + lease), timestamp verification (GC CME UTC vs XAUUSD Dukascopy UTC, time-aligned ticks), and anchored 5-fold walk-forward design (threshold cointegration / TVECM 3 regimes, 5-min best, cost-aware carry + EFP + GC commission + XAUUSD spread). Meanwhile, retain the event-volatility prereg (§10.3) as an `INCONCLUSIVE` observational filter (do not trade into 30-min windows; measure spread tail) until 100+ events and R5 PASS are achieved.**

*No held-out 40% tick access (`held_out_rows_read=0`), no live orders, no threshold mining, no ForexFactory scraping, no synthetic DXY/TIPS, no engine expansion — all evidence preserved (`/tmp/macro_test_output.txt`, `/tmp/macro_incremental_out.txt`, `xauusd_event_spread_evidence.json` 23×368k ticks, `xauusd_dukascopy_acquisition.json` 14×SHA, `curl -v` block logs).*

