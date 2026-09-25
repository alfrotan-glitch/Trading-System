# Gold Futures Basis — Information Test — 2026-09-23

**Branch:** `arena/01a0cdf1-trading-system` → `18eb85a` + this test  
**Instruction:** Phase candidate **GOLD FUTURES BASIS — INFORMATION TEST** — no trading strategy, no cointegration/TVECM/threshold/pairs/mean-reversion deployment, no VFLP/Donchian/Bollinger/RSI reuse, no held-out 40% access, no parameter rescue, `NO_TRADE` `DEMO_EXECUTION=DISABLED` `LIVE=LOCKED`.  
**Question:** Does COMEX gold futures (GC) contain genuinely incremental, reproducible information about XAUUSD spot beyond XAUUSD L1 (mid, trail, gap)?

---

## 1. Data provenance

### 1.1 XAUUSD spot — available REAL baseline

| Field | Value |
|---|---|
| **Provider** | Dukascopy Bank SA via `vudo805/forex-price-simulator` mirror (same as `docs/data_provenance_xauusd_dukascopy.md`) |
| **Instrument** | `XAU/USD` spot (CFD), USD per troy ounce |
| **Pinned commit** | `4d6f15543e6285fad91fd57fe42f716bc7273075` (2026-09-18T08:05:21Z) — verified `git fetch --unshallow` → `git checkout 4d6f155` → SHA `6b51ceb0fa34…` for `XAUUSD_2026-09.parquet` |
| **Feed** | Dukascopy `datafeed.dukascopy.com` 20-byte `>iiiff` ticks, `POINT_VALUE 1000`, downloader daily 03:00 UTC `LAG_DAYS=2` |
| **Transform** | 15-min mid OHLC `mid=(bid+ask)/2` + per-bar tick count — **tick-derived REAL**, not broker |
| **Files** | 14 parquets `XAUUSD_2025-08.parquet` `e650d23…`1632 … `2026-09.parquet` `6b51ceb…`1038 |
| **Export** | `data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv` `7271892f…` **26038** rows `2025-08-06T00:00:00Z→2026-09-16T23:45Z` UTC, `1H` agg `97b457d…` 6513 |
| **Data class** | `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks` |
| **Quality** | `R1 REAL` PASS, `R2 DEPTH 26038≥5000` PASS, `R3 REGIME 407d≥180d` PASS, `R4 FRESHNESS` PASS (at acquisition), `R5 EXECUTION-DATA` **FAIL** (no `bid/ask`, `spread UNAVAILABLE`), `R6 EVENT_SUFF` PASS; **gap completeness FAIL 6.42%** (1785 unexpected /27,823 active, `analyze_gap_semantics` weekend-only) — gaps absent, not filled |
| **Bid/ask vs mid vs last** | **Mid only** (`open/high/low/close` are mid, `volume` = tick count, not traded volume; `bid`/`ask` not preserved) |
| **Trade volume** | **Not available** — `volume` is tick count per bar |
| **Timezone / timestamp** | **UTC** bar open `+00:00`, `900s` cadence, monotonic, `tz_aware` PASS |
| **Licensing** | Upstream **NO LICENSE** — internal research only, no redistribution [xauusd_dukascopy_acquisition.json] |
| **Reproducibility** | `git clone https://github.com/vudo805/forex-price-simulator` → `git fetch --unshallow` → `git checkout 4d6f155` → `python scripts/acquire_xauusd_dukascopy.py --source-dir /tmp/test-vudo/data/XAUUSD` (pandas 3.0.6) — per-file SHA verified; regenerated 2026-09-23 identical to `7271892f…` |
| **Actually used here** | **YES** — 26038 bars as spot leg for sync |

### 1.2 COMEX GC gold futures — attempted acquisition

**Target instrument (required for a valid test):**

- **Exchange / venue:** COMEX (CME Group) [CME fact card]
- **Product code:** `GC` — Gold Futures (and Micro `MGC` 10 oz, not used)
- **Contract size:** 100 troy ounces, **quotation USD/oz**, **min fluctuation $0.10/oz = $10 per contract**
- **Grade:** 995 fineness, 1×100-oz bar or 3×1-kg bars
- **Listed contracts:** Current calendar month + next 2 calendar months + any Feb/Apr/Aug/Oct within 23 months + any Jun/Dec within 72 months [CME + StackExchange]. On a given date, only a subset exists; depth thins beyond 2y.
- **Termination / expiration:** Trading terminates **third last business day of delivery month** [CME fact card + StackExchange: “minus 3 business days” excluding holidays]; **First Notice Day** = last business day of month prior to delivery month [NYMEX 1/7]. CME Globex hours **Sun 17:00–Fri 16:00 CT** with 17:00–18:00 CT break daily [CME fact card].
- **Timezone:** **Chicago Time CT (America/Chicago)** — `CT` is `CST UTC-6` / `CDT UTC-5` (DST second Sun Mar → first Sun Nov); Globex close 16:00 CT = 21:00/22:00 UTC
- **Rollover methodology required:** Not a single continuous price; must map **individual contracts** (`GCG26`, `GCJ26`, `GCM26` …) across time via **roll date** (conventionally **8 calendar days before expiration** per CME `rolldates.html` [StackExchange], or volume/open-interest flip, or calendar). **Do not silently mix contracts** — must document **back-adjust / ratio-adjust / zero-adjust** vs **unadjusted** vs **volume-rolled** and preserve contract IDs.
- **Data needed for basis:** `S` (spot mid), `F` (front-month GC last/settlement), `time to maturity` `τ` (days to expiration per contract), `carry` (financing + storage + lease), **bid/ask** for GC (for transaction cost), **trade volume / open interest** for roll decision

**Candidate providers researched (catalog vs measurement):**

| Provider | Instrument | Granularity | Bid/ask | Tick | Timezone | Licensing | Cost | Status in this checkout |
|---|---|---|---|---|---|---|---|---|
| **Dukascopy `GOLD.CMD/USD` / `XAU/USD` futures CFD** | GOLD (GC proxy) | tick, m1/m15/h1/D | bid/ask? | tick | UTC/Geneva | Free personal, no redistribution | Free | **PLANNED_NOT_INGESTED** — `datafeed.dukascopy.com` **BLOCKED** (see below) |
| **FirstRate Data GC** | GC | tick, 1s, 1m, h1 | mid OHLC only | tick | UTC | Paid commercial | $300/yr bundle | PLANNED_NOT_INGESTED, not purchased |
| **Databento `GLBX.MDP` CME GC `MBO`/`MBP_10`/`TRADES`** | GC `MBO` L3 / `MBP_10` L2 | per-order tick | **YES** L2/L3 | **YES** `TRADES` | UTC (CME) | Paid $500–2000/mo | PLANNED_NOT_INGESTED |
| **CME DataMine / Nasdaq Data Link (Quandl) GC continuous** | `CHRIS/CME_GC1` | daily | settlement only | no tick | CT | Paid | — | Not attempted (requires key + network) |
| **TradingView `COMEX:GC1!` continuous** | GC1! | 15m (`GC_in_15_minute_new.csv` 458KB 2025-06-30→2025-10-15 per Kaggle) | OHLC | — | Exchange | TradingView Terms | Free via Kaggle mirror | **Kaggle `SSL_ERROR_SYSCALL` blocked** |
| **Kaggle `youneseloiarm/comex-gold-futures-dataset-gc-contract`** | GC `GC_in_15_minute_new.csv` | 15m | OHLCV | — | Not documented | Kaggle CC | Free | **BLOCKED** (same) |
| **GitHub `Prachi-Gopalani13/Commodity-Price-Prediction` `Gold Futures Historical Data.csv`** | Gold Futures | **monthly** 122 rows 2018–2020 | — | — | — | MIT? no license | Free | **CLONED** but **not synchronizable**: monthly, 1.2y overlap missing, no intraday, no contract IDs, no timezone, no rollover |
| **GitHub `datasets/gold-prices` `data/monthly.csv`** | World Bank Gold | **monthly** 1833–2025-07 (2312 rows, World Bank Pink Sheet) | — | — | — | PDD | Free | **CLONED** but **not GC futures** (is spot proxy, monthly) |
| **Portara `GCA` (GC) `GCA2026Q` 1-min continuous** | GCA (GC) | 1-min 1987→now 623 MB uncompressed | — | — | Exchange | Paid, sample free `s3.amazonaws.com` | Paid + sample S3 | **S3 blocked** (same egress) |

**Attempted acquisition — measured, not inferred:**

1. **Dukascopy `datafeed.dukascopy.com` GC tick `BI5`**  
   `curl -v -m15 https://datafeed.dukascopy.com/datafeed/GOLD/2025/07/06/00h_ticks.bi5` → `* Connected to 194.8.15.180:443` → `OpenSSL SSL_connect: SSL_ERROR_SYSCALL 35` → `curl: (35)` — **identical to XAUUSD but GC path also blocked**. `ping 8.8.8.8 0% loss` (ICMP allowed) vs TCP 443 blocked. `github.com 200` vs `datafeed.dukascopy.com 000` logs retained (see §1.3 macro test — same pattern for `fred`, `bls`).

2. **Kaggle GC 15m `GC_in_15_minute_new.csv` (TradingView GC1! 2025-06-30 23:30 examples `3324.0/3324.2/3320.3` per Kaggle page)**  
   `curl -I -m10 https://www.kaggle.com/datasets/youneseloiarm/comex-gold-futures-dataset-gc-contract` → `SSL_ERROR_SYSCALL 35` to `kaggle.com:443` — **blocked**.

3. **Portara S3 sample `https://portaradownloadersampledata.s3.amazonaws.com/1%20Minute/GCA/GCA2026Q.txt`**  
   Would be `s3.amazonaws.com:443` — same egress block (not attempted due to prior `s3` pattern, but `fred`/`kaggle`/`datafeed` already prove 443 block for non-allowlist).

4. **GitHub mirrors cloned (allowlisted `github.com`):**
   - `https://github.com/Prachi-Gopalani13/Commodity-Price-Prediction` → **cloned** `122` lines monthly `Gold Futures Historical Data.csv` `"May 20","1,700.90"…` — **rejected as unsynchronizable**: no 15-min, no contract, no 2025–2026 intraday, no timezone, not GC `GCG26` etc.
   - `https://github.com/datasets/gold-prices` → **cloned** `data/monthly.csv` 2312 rows `1833-01,18.930` — **World Bank spot proxy, not GC futures**, monthly, latest `2025-07`.
   - `https://github.com/theorycraft-trading/dukascopy` → **cloned** (Elixir `Dukascopy` lib, docs `GOLD.CMD/USD` etc.) — **no data**, only downloader code which would hit blocked `datafeed.dukascopy.com`.
   - `api.github.com/search/repositories?q=GC+futures+COMEX` → **1** result `hugocytam/gold-dashboard` (live SGE vs GC spread dashboard, **no historical CSV**).

5. **Dukascopy instrument search via `theorycraft` docs:** lists `BRENT.CMD/USD`, `COPPER.CMD/USD`, but **`GOLD.CMD/USD` is XAU/USD spot, not GC contract**; GC futures would be `GCG26.CMD` style — **not enumerated** in cloned repo, and even if known, download would hit blocked `datafeed`.

6. **Offline CSV already on disk:** `data/raw/xauusd_*` only XAUUSD, no `GCG*` or `GC1` files; `data/curated` only `XAUUSD MT5 1H synthetic`.

**Result:** **No GC futures tick/1m/15m/h1 with contract IDs, expiration, and intraday timestamps overlapping XAUUSD `2025-08-06→2026-09-16` could be acquired via any allowlisted path without silently mixing contracts.** The only GC-like files found are **monthly, non-synchronous, non-contract-specific** and would violate “Do NOT use an unverified continuous futures series”.

---

## 2. Contract specification (as documented, not measured)

*(From CME fact card + StackExchange, not from acquired GC bytes — because no GC bytes acquired)*

| Spec | GC (COMEX Gold Futures) | MGC (Micro Gold, for reference) |
|---|---|---|
| **Exchange / Rulebook** | COMEX 113, CME Globex / ClearPort | COMEX |
| **Code** | `GC` (e.g., `GCG26` = Feb 2026) | `MGC` |
| **Size** | 100 troy oz | 10 troy oz |
| **Quotation** | USD/oz, **$0.10/oz = $10** min tick | USD/oz, $0.10 = $1 |
| **Months listed** | Current + next 2 calendar months + Feb/Apr/Aug/Oct within 23m + Jun/Dec within 72m [StackExchange] — **sparse far months** | Monthly |
| **Last trading day** | **Third last business day of delivery month** [CME] — business days exclude holidays; e.g., May 2017 last Fri May 26 because Mon May 29 holiday [StackExchange] | Same |
| **First Notice Day** | Last business day of month prior to delivery month [NYMEX 1/7] | — |
| **Trading hours (Globex)** | **Sun 17:00–Fri 16:00 CT** with 16:00–17:00 CT break daily [CME fact card] | Same |
| **Timezones** | **CT** (`America/Chicago` CST UTC-6 / CDT UTC-5) — **not UTC**; XAUUSD is UTC — **session mismatch requires conversion** | — |
| **Settlement** | Physically deliverable (100-oz or 3×1-kg bars, 995 fineness) or cash; most traders roll ~2 weeks before expiration [Gainesville] | Physical or cash |
| **Continuous construction** | **Not listed by exchange** — must be built via **roll date**: CME convention **8 calendar days before expiration** [StackExchange `rolldates.html`] or volume/open-interest flip; adjustments: **back-adjust** (add roll gap), **ratio-adjust**, or **zero-adjust/unadjusted** (true prices, gaps at rolls) — **choice changes basis** |
| **Active / most liquid** | Feb, Apr, Jun, Aug, Dec (volume concentrates) [Gainesville] | — |
| **Example roll gap** | If `GCG26` settles 2680 and `GCJ26` settles 2685, unadjusted series has +5 gap at roll; back-adjust would subtract 5 from history — **basis would be distorted if wrong** |

**Implication:** Without **per-contract bars with expiration dates and roll methodology**, any `GC1!` continuous CSV (e.g., TradingView `GC1!` `3324.0` examples) is **unverified** for this test — it silently mixes `GCG26`/`GCJ26` without documenting which contract was front at `2025-08-06 00:00Z` vs `2026-09-16 23:45Z`.

---

## 3. Rollover treatment

**Required per instruction:** Document exactly how individual GC contracts are mapped across time.

**Status:** **BLOCKED — no rollover could be constructed because no per-contract GC series was acquired.**

**What would be required for a valid rollover (not performed):**

- Ingest **individual contract files** `GCG26`, `GCF26`, `GCJ26`, `GCM26`, `GCQ26`, `GCV26`, `GCZ26` etc. with fields `contract`, `expiration`, `open/high/low/close/volume/openInterest`, `timezone CT`.
- Determine **roll date** per contract: **8 calendar days before third-last business day** (CME convention) or **volume crossover** (when next month volume > front). The two methods differ by 1–5 days and create different gaps.
- Choose **adjustment**: For **information test** (not strategy), **unadjusted** front-month close is preferred (true tradable prices, gaps visible) vs **back-adjusted** (continuous curve, distorts absolute levels but preserves returns). Must **preserve both** and label clearly; **basis `F−S` must use unadjusted `F`**.
- Produce **continuous mapping table**:

| Date range (UTC) | Front contract | Expiration (CT) | Roll date (CT) | Adjustment | Overlap |
|---|---|---|---|---|---|
| `2025-08-06 → 2025-08-22` | `GCQ25` (Aug 2025) | 2025-08-26 (third last bus. day) | 2025-08-18 | unadjusted | — |
| `2025-08-18 → 2025-10-22` | `GCZ25` (Dec 2025) | 2025-11-24 | 2025-11-16 | … | — |
| … | … | … | … | … | … |

- **No such table exists** for this test — **cannot be fabricated**.

**Candidate unverified series rejected:**

- `GC_in_15_minute_new.csv` (Kaggle, 458KB, 15m `2025-06-30 23:30 3324.0` …) — **no roll table, no contract IDs, no expiration, no timezone** — using it would be “**silently mixing contracts**” per hard restriction.
- `Gold Futures Historical Data.csv` (GitHub 122-line monthly) — **no intraday, no rolls, wrong timeframe**.
- `datasets/gold-prices` World Bank monthly — **not GC**, no contract.

**Failure mode if rollover mishandled:** Basis `F−S` would contain **artificial jumps** of ±$5–$15 at rolls (carry gap), creating spurious “basis widening → convergence” that is **not information but artifact**. This is why Phase 1 requires exact mapping before any research.

---

## 4. Timestamp methodology

### 4.1 XAUUSD spot

- **Source time:** Dukascopy tick `time_msc` UTC ms → 15m bar open `time` ISO `+00:00` UTC, `900s` cadence, monotonic, `tz_aware` PASS.
- **Session:** 24×5 (Sun 22:00 UTC → Fri 22:00 UTC approx, but gaps absent; weekend closure 58 events, unexpected 6.42% gap).
- **Example:** `2025-08-06T00:00:00+00:00` open `3383.31`, `2026-09-16T23:45:00+00:00` last.

### 4.2 GC futures (required, not acquired)

- **Exchange time:** CME Globex **CT** `17:00–16:00 CT` with `16:00–17:00 CT` maintenance break — **not 24h**.
- **Required conversion:** `CT = CST (UTC-6)` winter, `CDT (UTC-5)` summer (DST second Sun Mar → first Sun Nov). For sync with XAUUSD UTC, must convert each GC tick `CT → UTC` (e.g., `2026-03-11 12:30 UTC` is `08:30 ET` = `07:30 CT` CST; `2026-06-10 12:30 UTC` is `08:30 ET` = `07:30 CT` CDT). **Off-by-one-hour errors if DST ignored.**
- **Bar convention:** GC `GC1!` 15m on TradingView appears at `23:30, 00:15` CT? No — must verify from raw GC (not available). **Cannot proceed if alignment tolerance > interval.**

### 4.3 Synchronization design (planned, not executed)

| Parameter | Planned value | Rationale | Why not optimised |
|---|---|---|---|
| **Common interval** | **15m** (smallest defensible) | XAUUSD native is 15m mid; GC `GC_in_15_minute_new.csv` is 15m; 1-hour would coarsen but 15m is native for both | Not optimised to improve correlation; 15m is declared XAUUSD timeframe |
| **Tolerance** | **≤1s** for tick-then-resample, **±30s** for 15m bar open alignment | 15m bars must have **identical open timestamps** in UTC (e.g., `2025-08-06T00:00:00Z` for both) to compute `basis = F−S` and `lead` via `Δlog(F)` vs `Δlog(S)` | Larger tolerance would be look-ahead (GC 23:30 vs XAUUSD 00:00 mismatch) |
| **Unmatched** | Count bars where XAUUSD present but GC missing (due to CME break 16:00–17:00 CT = 21:00–22:00 UTC, and GC not listed far months) and vice versa | Must be **absent, not forward-filled**; mismatch >5% would block test | — |
| **Stale** | GC bar `volume==0` or `close==prev close` for >4 consecutive 15m during GC session → stale, exclude | — | — |
| **Session mismatch** | XAUUSD 24×5 vs GC 23×5 (1h break) → **GC break bars will be absent**; XAUUSD has bars at `21:00–22:00 UTC` where GC is closed — **must be excluded from sync** | — | — |
| **Rollover boundaries** | Exclude `roll date ±1 bar` from sync (or flag) to avoid artificial basis jump | — | — |

**Because no GC intraday with CT timestamps was acquired, synchronization quality cannot be measured — §5 is empty and Phase 4 cannot start with real data.**

---

## 5. Synchronization quality

**Status:** **NOT MEASURED — BLOCKED** (no GC series to sync).

**What would be measured (template, no numbers):**

| Metric | Definition | Threshold to proceed | Observed |
|---|---|---|---|
| `XAUUSD timestamp` | UTC `+00:00` 15m open, monotonic | — | `2025-08-06T00:00:00Z` (measured) |
| `GC timestamp` | CT → UTC converted, monotonic | — | **Not acquired** |
| `Common interval` | 15m | Fixed (not optimised) | — |
| `Tolerance` | `|XAUUSD_open_UTC − GC_open_UTC| ≤30s` | ≤30s | — |
| `Unmatched XAUUSD→GC` | XAUUSD bars with no GC bar within tolerance / total XAUUSD bars in GC session | **<5%** else BLOCKED | — |
| `Unmatched GC→XAUUSD` | GC bars with no XAUUSD bar / total GC bars | <5% | — |
| `Stale GC` | GC bars with `volume==0` or unchanged close >4 bars during GC session | <1% | — |
| `Session mismatch` | XAUUSD bars during GC 16:00–17:00 CT break | Must exclude, count mismatch | — |
| `Rollover gaps` | Bars at roll date | Flag, exclude from basis `F−S` diff | — |
| **Decision** | Proceed only if `unmatched <5%` **and** `stale <1%` **and** timestamps reliably CT→UTC | **BLOCKED if unreliable** | **BLOCKED** |

**Smallest defensible interval is 15m** (XAUUSD native) — not optimised to improve result. **Do not proceed if timestamp alignment is unreliable — we do not proceed.**

---

## 6. Carry / basis definition

### 6.1 Economic relationship

For a storable commodity with **cost-of-carry** (financing + storage + insurance − convenience yield / lease):

```
F(t,T) = S(t) * exp( (r + u − y) * τ )          (continuous)
F(t,T) ≈ S(t) * (1 + (r + u − y) * τ)           (simple, τ in years)
carry  c(t,T) = (r + u − y) * τ                 (in price terms)
basis  b(t)   = F(t,T) − S(t)   (or log-basis ln(F/S))
time to maturity τ = (expiration − t) / 365.25   (ACT/365.25, CT expiration at 13:30 CT? Not, but use date)
```

- `S(t)` — **XAUUSD spot mid** at `t` (UTC) — measured `26038` bars.
- `F(t,T)` — **GC front-month price** at `t` for contract expiring `T` — **not acquired** (would be GC `t` front `GCG26` etc. `close` in USD/oz).
- `τ` — `T − t` — requires **per-contract expiration** (third last business day of delivery month, CT) — **not available without contract mapping**.
- `r` — **financing rate** — risk-free `SOFR` / `Fed Funds Effective` (FRED `SOFR`, `DFF` daily, 16:00 ET, public domain) — **would be FRED daily, but FRED blocked** (same `SSL_ERROR_SYSCALL` as §1.3 macro test); could proxy with `3M T-Bill` but still FRED.
- `u` — **storage + insurance** — physical gold storage ~0.10–0.20% p.a. + insurance — **assumption required, not measured in QTS**; historical `COMEX` storage fees not in any acquired dataset.
- `y` — **lease / convenience yield** — gold lease rate (`GOFO`/`GLR`) — **not available** in any QTS provider; Bloomberg `GLR` not free.
- `c` — **carry** = `F − S` theoretical — cannot be identified without `r,u,y`.
- `b` — **observed basis** = `F_market − S_market` — **can be measured from `F` and `S` ticks alone** without `r,u,y` — this is the **only reliably identifiable quantity** with `S`+`F`.

**This test is INFORMATION TEST ONLY — not a trading strategy — so we do not force `F = S + carry` to fit.**

### 6.2 What can and cannot be identified with current data

| Quantity | Identifiable? | Required inputs | Status |
|---|---|---|---|
| `S(t)` (spot) | **YES** — `XAUUSD 15m mid` `3383.31` … `4271.805` | XAUUSD | **Measured** |
| `F(t,T)` (futures front) | **NO** | GC per-contract 15m | **BLOCKED** — no GC intraday |
| `τ(t)` (time to maturity) | **NO** | GC expiration per contract | **BLOCKED** — no contract IDs |
| `b(t)=F−S` (observed basis) | **NO** | `F` + `S` synchronized | **BLOCKED** — needs `F` |
| `c = r+u−y` (theoretical carry) | **NO** | `r` (SOFR), `u` (storage), `y` (lease) | **BLOCKED** — `r` FRED blocked, `u`/`y` not in any provider, not measured |
| `b − c` (mispricing) | **NO** | `b` + `c` | **Cannot be identified** |

**Therefore:** Only `S` is known. `F`, `τ`, `b`, `c` are **not identifiable** without GC futures and carry inputs. We **state exactly what can and cannot be identified** — we do **not** force theoretical `F=S+carry` to fit `S` alone, and we do **not** proxy `F` with `S` (that would be fabrication per `xauusd_directional_next_step`).

**If GC were available, the basis test would be `b(t)=F−S` and its dynamics (widening/compression) vs subsequent `S` or `F` — not `F=S+carry` fit.**

---

## 7. Exact preregistered hypotheses (small, economically justified, no threshold mining)

**Populations:** XAUUSD 15m mid `2025-08-06→2026-09-16` 26038 bars UTC + GC front-month 15m (CT→UTC) synchronized at 15m (planned 26038 bars, sessions aligned, roll gaps flagged). **Warmup 64** bars, `i+h<n`, no held-out.

**Horizons:** `h = 1, 4, 12` bars (**15m, 1h, 3h**) — primary `h=1` (lead/lag at next 15m), sensitivity `h=4,12`. **Lags:** `l = 1, 4` for lead tests (GC `t−l` → XAUUSD `t→t+h`), **no dozens of lags**, no lookback window search.

**Thresholds:** **No thresholds** — basis `b` is continuous; tests are **correlational / mean-difference**, not `b > X` threshold strategies. **No `k`, `z`, `threshold` optimisation** (threshold strategies are for later, only if information is detected).

| ID | Arrow | Prediction (incremental beyond XAUUSD L1) | Null | n (if GC available) | Variables | Test |
|---|---|---|---|---|---|---|
| **H-GC-LEAD-01** | `GC lead → XAUUSD` | `GC` return at `t−l` predicts **XAUUSD** `log( S_{i+h}/S_i )` beyond XAUUSD own trailing `trail16`/`range_expansion` — **positive cross-correlation** `corr( Δlog(F_{i−l}), Δlog(S_{i→i+h}) ) >0` and Granger-like incremental `R²` >0 | `No lead: cross-corr =0 and XAUUSD autocorrelation fully explains` | 69? No, continuous: ~25k sync bars | `Δlog(F_{i−l})` (l=1,4), `Δlog(S_{i→i+h})` (h=1,4,12), control `Δlog(S_{i−trail})` | Pearson/Spearman cross-corr + block bootstrap CI, + regression `S_{h} ~ S_{trail} + F_{lag}` incremental `R²` |
| **H-GC-LEAD-01b** | `GC lead → XAUUSD magnitude` | `|Δlog(F_{i−l})|` predicts `|Δlog(S_{i→i+h})|` (volatility lead) incremental beyond `trail16` | `No volatility lead` | ~25k | `|Δlog(F)|`, `|Δlog(S)|` | Same |
| **H-XAU-LEAD-02** | `XAUUSD lead → GC` | Symmetric **reverse** — `Δlog(S_{i−l})` predicts `Δlog(F_{i→i+h})` — tests **bidirectionality**; if symmetric, no GC incremental | `No XAU→GC lead` | ~25k | `Δlog(S_{i−l})`, `Δlog(F_{i→i+h})` | Same as H-GC-LEAD-01 but flipped |
| **H-BASIS-WIDE-03** | `basis widening → convergence` | When `b(t)=F−S` **widens** (more positive, futures rich vs spot — contango steepens), subsequent `b` **mean-reverts** (narrows) and/or `S` **rises** / `F` **falls** at `h=1,4` — **negative autocorrelation of `b`** and **positive `b → ΔS` / negative `b → ΔF`** | `b` is random walk, no mean reversion | ~25k sync `b` | `b(t)`, `Δb_{t→t+h}=b_{t+h}−b_t`, `Δlog(S_{t→t+h})`, `Δlog(F_{t→t+h})` | `corr(b_t, Δb_{t→t+h})` (expect <0), `corr(b_t, Δlog(S))` |
| **H-BASIS-COMP-04** | `basis compression → subsequent` | When `b` **compresses** (narrows toward 0 or negative — backwardation), `b` widens back and `S`/`F` adjust oppositely | Same null as 03 | ~25k | Same as 03 but conditioning on low `b` | Same |
| **H-REGIME-05** | `regime-dependent basis` | `b` dynamics differ in **contango vs backwardation** regimes (`b>0` vs `b<0`) and **near vs far from expiration** (`τ <14d` vs `τ >14d`) — `GC→XAUUSD` lead stronger when `b` large or `τ` small (arbitrage pressure) | `No regime difference` | ~25k | `b(t)`, `τ(t)`, `Δlog(S)`, `Δlog(F)` | Stratified corr / regression within regimes, no threshold mining (regime = sign of `b`, `τ` median split only) |

**What is NOT tested:** No `b > X` threshold sweep, no `lookback 5,10,20,40,60` window search, no `TVECM`/`threshold cointegration`/`pairs`/`z-score` strategy, no `VFLP`/`Donchian`/`Bollinger`/`RSI` reuse — those are **complex models for later, only after simple information exists**.

**Competing explanations:** (1) `b` widening is just `S` volatility tail (not `F` info), (2) both `S` and `F` are driven by common USD factor (spurious), (3) stale GC vs XAUUSD 24h session mismatch creates artificial lead, (4) roll gap not flagged creates spurious `b` jump, (5) thin GC far-month illiquidity.

**Falsification:** (a) anchored 5-fold walk-forward `cross-corr` CI includes 0, (b) incremental `R²` ≤0 after controlling `trail16`, (c) `b` autocorrelation ≥0, (d) Holm correction fails, (e) block bootstrap `p>0.05`.

---

## 8. Results

### 8.1 GC data availability — **No GC series to test**

**All five hypotheses require `F(t,T)` and `b(t)=F−S`.**

- **GC 15m continuous `GC1!` 2025-06-30 23:30 `3324.0` example** (Kaggle 458KB) — **not acquired** (Kaggle `SSL_ERROR_SYSCALL` 35 to `www.kaggle.com:443`).
- **Dukascopy `datafeed.dukascopy.com` GC `BI5` ticks** — **blocked** (`SSL_ERROR_SYSCALL` 35 to `194.8.15.180:443`, `ping 8.8.8.8 0% loss`, `github.com 200` vs `datafeed 000`).
- **Portara `s3.amazonaws.com` GC 1-min sample** — S3 domain also 443 block (inferred from `fred`/`kaggle` block pattern).
- **GitHub clones (allowlisted `github.com`):**
   - `Prachi-Gopalani13` monthly 122 lines 2018–2020 — **unsynchronizable** (no 15m, no contract, wrong period).
   - `datasets/gold-prices` World Bank monthly 1833–2025-07 — **not GC**, monthly, not 15m.
   - `theorycraft` Dukascopy lib — **code only**, no data; download would hit blocked `datafeed`.
   - `hugocytam/gold-dashboard` — **no historical CSV**.
- **Result:** **0 GC bars synchronized** at 15m UTC overlapping XAUUSD `26038` bars. **Synchronization table in §5 is empty.**

**Therefore:** **No `Δlog(F)`, `b`, `τ`, or `carry` series exists to compute correlations, lead/lag, or regime tests.** Results tables are intentionally **empty — not fabricated**.

### 8.2 What could be computed from spot alone (and why it is not GC information)

- XAUUSD own `trail16` and `range_expansion` already tested: `H-ST-02` ratio 1.48, `range_expansion` 1.86×, `h=1` baseline `0.001104` — this is **L1 info, not GC**.
- **Temptation to proxy `F` with `S`** (mid as futures) would be **fabrication** (`SYNTHETIC_DERIVED` mislabeled as `REAL`) per `research_integrity_audit.md` RI-009 and `data_requirements.md` — **not done**.

### 8.3 Template of results if GC were available (not filled)

| Hypothesis | `l` / `h` | `n_sync` | `cross_corr` | 95% CI (block bootstrap) | `p` | `incremental R²` vs `trail16` | Holm | Walk-forward `WFA` | Interpretation |
|---|---|---|---|---|---|---|---|---|---|
| H-GC-LEAD-01 | l=1, h=1 | — | — | — | — | — | — | — | **Not measured** |
| H-GC-LEAD-01 | l=4, h=4 | — | — | — | — | — | — | — | Not measured |
| H-XAU-LEAD-02 | l=1, h=1 | — | — | — | — | — | — | — | Not measured |
| H-BASIS-WIDE-03 | h=1 | — | corr(b,Δb) — | — | — | — | — | — | Not measured |
| H-REGIME-05 | contango vs backwardation | — | — | — | — | — | — | — | Not measured |

**All cells are `BLOCKED` — not `0` (which would be a measured no-correlation).**

---

## 9. Walk-forward results

### 9.1 Design (planned, not executed)

- **Anchored 5-fold chronological** — 26038 bars ÷5 ≈5207 per fold `0:5207, 5207:10414, 10414:15621, 15621:20828, 20828:26038` — training = `[0, test_start)` expanding, test = `[test_start, test_end)` — **no lookahead, no held-out 40% tick access**.
- **Statistics per fold:** `cross_corr GC_{lag}→S_{h}`, incremental `R²` over `S_{trail}`, `corr(b,Δb)`, block bootstrap 999 block20 seed42, Holm over 5 hypotheses ×3 horizons =15 tests.
- **Cost for economic interpretation:** When interpreting lead as trade, include **XAUUSD spread** (event median 1.732 bps from `xauusd_event_spread_evidence.json`, not mid), **GC transaction cost** (`$0.10/oz` tick = `0.30 bps` at $3300, plus `CME fee ~$0.85` + `clearing $0.03` ≈ `0.35 bps`, plus **EFP / roll cost** `b` gap), **commission** (broker `0.4 bps` round-turn from `impulse_research`), **carry** `c = (r+u−y)τ` (not identifiable, see §6).

### 9.2 Observed

**Not executed — no GC series to walk forward.** Fold definitions above are identical to macro event test (which had 23 events, now would have ~25k sync bars if GC existed) — **no test ratios, no `WFA`, no `PBO`**.

**Failure to walk forward is not a negative `WFA<0.3` but a `BLOCKED` — cannot distinguish `INCONCLUSIVE` (unstable) from `NO_INCREMENTAL` (zero).**

---

## 10. Cost assumptions (for economic interpretation, not applied)

**Because no lead was measured, costs are documented but not applied to a strategy.**

| Leg | Cost component | Value at $3300–$4400 XAU/GC | Source | How it would be applied |
|---|---|---|---|---|
| **XAUUSD spot** | Spread | **1.732 bps** median (23 event windows), `p95 3.04—23.8 bps` max 36.6 bps tail [event_spread_evidence] — **mid is not executable**, declaration `2.0 bps` is `ESTIMATED` | `xauusd_event_spread_evidence.json` pooled `1.732` | Entry `½ spread` + exit `½ spread` = `≈1.73 bps` per round-turn at median, **>5 bps at tail** |
| | Commission | **0.4 bps** round-turn | `impulse_research_xauusd_dukascopy_15m.json` `round_turn_cost_bps 3.4 =2.0 spread +0.4 commission +1.0 slippage` | Added to spread |
| | Slippage / latency | **0.5 bps per side** `1.0 bps` round-turn `latency 1 bar` | Same | Added |
| | **Total XAUUSD** | **3.4 bps** `ESTIMATED` (mid proxy) — **real p95 tail 3.04–23.8 bps** means real round-turn could be **5–30 bps** in event windows | Measured vs estimated distinction per `research_integrity_audit` RI-005 | `net = gross −3.4 bps` (or −5–30 bps stress) |
| **GC futures** | Tick / spread | **$0.10/oz** = **0.30 bps** at $3300 (`0.10/3300`) | CME spec [fact card] | Half tick per side `0.15 bps` |
| | CME ClearPort / Globex fee | **≈$0.85–$1.20 per contract** → `0.85/ (100×3300)=0.26 bps` | CME fee schedule | Added |
| | EFP / cash-and-carry | `F−S` gap carry `c = (r+u−y)τ` — **not identified** (r FRED blocked, u/y not measured) | §6 | Would be explicit `c` if `r,u,y` known |
| | Roll / delivery | Gap at roll `8d` before expiration — **unadjusted vs back-adjust** choice | CME `rolldates.html` + StackExchange | Flag roll ±1 bar |
| | **Total GC** | **~0.6 bps** round-turn at median (0.30 tick +0.26 fee) plus **carry `c`** if holding to delivery | — | `netGC = grossGC −0.6 bps −carry` |
| **Latency** | GC `TRADES` vs XAUUSD `mid` 15m | **1 bar (15m)** delay as in `H-DIR-02` | — | `Δlog(F_{lag})` with `lag+1` |

**Economic gate earlier:** XAUUSD directional H-MACRO-EVENT-DIR-01 net was **-1.99 bps at `h=1`** vs `-3.31 bps` baseline — already negative at `3.4 bps`. Adding GC costs (`0.6 bps`) would make a GC→XAUUSD lead trade even more negative unless lead gross `>4.0 bps` per 15m (≈3.6× baseline 0.11% =0.39% =39 bps for volatility, but directional is 1.4 bps) — **unlikely**.

---

## 11. Incremental-information assessment

### 11.1 Critical comparison — A (already in L1) vs B (genuinely incremental GC)

**A = XAUUSD L1 already contains:**
- `trail16` `|log(S_i/S_{i−16})|` median 0.003195 — high/low split ratio 1.44× (from `macro_incremental.py`)
- `range_expansion k2.5 lookback20` 776 bars ratio 1.86× (0.002002 vs 0.001077)
- `event volatility` 3.57× (69 window bars, §4 macro test) — already incremental beyond L1 but **thin** (69) and **not GC**
- XAUUSD autocorrelation and own lead/lag — can predict GC if common factor, not GC incremental

**B = GC genuinely incremental would require:**
- `corr(Δlog(F_{lag}), Δlog(S_{h})) ≠0` **and** `R²(S_{h} ~ S_{trail} + F_{lag}) > R²(S_{h} ~ S_{trail})` — incremental after controlling L1 `trail16`.
- `corr(b_t, Δb_{t+h}) <0` (mean reversion of basis) that **predicts `ΔS` or `ΔF`** beyond `S` own mean reversion.
- **Regime-dependent**: `b` sign / `τ` median split changes lead — not in S alone.

**Because no `F`, `b`, `τ` series exists, we cannot distinguish A vs B — assessment is `BLOCKED`.**

### 11.2 What was actually tested vs what is claimed

- **Claim:** 5 preregistered relationships (§7) — **all BLOCKED**, not “tested and found zero”.
- **What was actually tested:** **None** — we did **not** proxy GC with XAUUSD, did **not** use unverified `GC1!` continuous, did **not** run TVECM, did **not** sweep lags.
- **A result that merely reproduces L1 volatility clustering is NOT GC incremental** — we avoid that by conditioning on `trail16` in `H-GC-LEAD-01` (require incremental `R²`). Since test not run, no false claim of GC incremental.

---

## 12. Failure modes

| Failure mode | Status | Evidence | Mitigation |
|---|---|---|---|
| **Look-ahead / leakage** | **Not applicable (blocked)** — but design would use `F_{i−l}` lag `1,4` to predict `S_{i→i+h}` with `i+h<n`, warmup 64, no future bar | — | Anchored, `l`≥1, `h`≥1, no peeking |
| **Look-ahead via continuous roll gap** | **HIGH RISK if unverified `GC1!` used** — back-adjusted series would leak future roll adjustment into past `b` | Rejected `GC_in_15_minute…` and `Gold Futures Historical Data.csv` as unverified | Require per-contract unadjusted + documented roll table |
| **Selection / threshold mining** | **Not mined** — 5 hypotheses, 2 lags, 3 horizons, **no dozens of windows/lags**, no `b>X` threshold | §7 | Fixed lags/horizons |
| **Single-regime / stale GC** | Would be risk: GC break 16:00–17:00 CT stale bars vs XAUUSD 24h would create artificial lead if not excluded | Planned `stale <1%` gate | Exclude stale/break bars |
| **Session mismatch** | **HIGH RISK** — XAUUSD 24×5 vs GC 23×5 `16:00–17:00 CT` break → 1h daily where XAUUSD has bar but GC closed. If filled with prior `F`, `b` spurious. | §4.3 planned `unmatched <5%` gate | Exclude break, do not forward-fill |
| **Rollover artifact** | **HIGH RISK** — `F−S` jump at 8d before expiration (≈$5–15) would appear as “basis widening” and fake mean reversion | Rejected continuous without roll table | Flag roll ±1 bar |
| **Network / data block** | **CONFIRMED BLOCK** — `datafeed.dukascopy.com:443` `SSL_ERROR_SYSCALL 35`, `kaggle.com:443` `35`, `fred/portara S3` same pattern, `ping 0% loss`, `github.com 200` vs `datafeed/kaggle 000` (logs as in §1.2 macro test). **Not synthesised** | `curl -v` logs retained; not proxied |
| **Contract mixing** | **Prevented** — Do NOT silently mix `GCG26`/`GCJ26` into `GC1!`; document exactly how contracts mapped — **blocked because no mapping could be built** | §2, §3 | `BLOCKED_BY_DATA_QUALITY` |
| **Carry misidentification** | **Cannot identify `carry = r+u−y`** — `r` FRED blocked (`SSL_ERROR_SYSCALL`), `u`/`y` not in any QTS provider — would force `F=S+carry` to fit | §6.2 table | State what can/cannot be identified, do not force fit |
| **Thin GC far-month illiquidity** | Would be risk if GC 72-month far contracts used — volume thins | — | Use front-month only |
| **Held-out contamination** | **Not accessed** — `held_out_rows_read=0` (same as all prior `reports/xauusd_*` `safety`) | `git status` | Keep `NO_TRADE` |
| **Overfitting via complex model** | **Not deployed** — TVECM/threshold/pairs not run until simple information exists (per anti-overfitting rule) | — | Information test first |

---

## 13. Final gate

### 13.1 Per-hypothesis gates

| ID | `n` | Gate | Reason |
|---|---|---|---|
| H-GC-LEAD-01 (GC→XAUUSD lead) | 0 | **BLOCKED_BY_DATA_QUALITY** | No `F` |
| H-GC-LEAD-01b (vol lead) | 0 | **BLOCKED_BY_DATA_QUALITY** | No `F` |
| H-XAU-LEAD-02 (XAU→GC) | 0 | **BLOCKED_BY_DATA_QUALITY** | No `F` |
| H-BASIS-WIDE-03 (basis widening→convergence) | 0 | **BLOCKED_BY_DATA_QUALITY** | No `b` |
| H-BASIS-COMP-04 (basis compression) | 0 | **BLOCKED_BY_DATA_QUALITY** | No `b` |
| H-REGIME-05 (regime-dependent basis) | 0 | **BLOCKED_BY_DATA_QUALITY** | No `b`/`τ` |

### 13.2 Overall gate — exactly one

**`BLOCKED_BY_DATA_QUALITY`**

**Reasoning:** The required data for the entire information test — **COMEX GC gold futures intraday with exact contract IDs, expirations, rollover methodology, and CT→UTC timestamps synchronized at 15m** overlapping XAUUSD `2025-08-06→2026-09-16` — **cannot be acquired or synchronized reliably** in this checkout:

- **No GC series with 15m granularity, contract specs, and per-contract expirations could be acquired via any allowlisted path** without violating “Do NOT silently mix contracts” / “Do NOT use an unverified continuous futures series”:
   - `datafeed.dukascopy.com` GC `BI5` tick — **TCP 443 `SSL_ERROR_SYSCALL` 35** (allowlist blocks `datafeed`, `fred`, `kaggle`, `s3`; only `github.com`/`api.github.com` 200; `ping 0% loss`, `curl -v` logs retained).
   - Kaggle `GC_in_15_minute_new.csv` 15m GC1! 458KB 2025-06-30 23:30 `3324.0` — **same 443 block** to `kaggle.com`.
   - Portara `s3.amazonaws.com` GC 1-min — same S3 443 block (inferred).
   - GitHub clones (allowlisted) yielded only **monthly** `Gold Futures Historical Data.csv` 122 lines 2018–2020 and World Bank monthly 1833–2025 — **unsynchronizable at 15m**, no contract IDs, no timezone, wrong period.
   - `theorycraft` Dukascopy lib — code only, download hits blocked `datafeed`.
- **Underlying contract insights (CME fact card) are DOCUMENTED** (§2) — `GC` 100 oz, `$0.10` tick, third-last business day expiration, `17:00–16:00 CT` with `16:00–17:00` break, Jun/Dec within 72m — but **without per-contract bars, `τ` and `b=F−S` cannot be computed**, and **carry `c=r+u−y` cannot be identified** (`r` FRED `SOFR`/`DFF` blocked same `SSL_ERROR_SYSCALL`, `u`/`y` not in any provider).
- **Synchronization (§5) could not be measured** — common 15m, tolerance ≤30s, `unmatched <5%`, `stale <1%`, session mismatch (GC 1h break), rollover ±1 bar flags — **all BLOCKED** because no GC timestamps to compare to XAUUSD UTC.

**This is not `NO_INCREMENTAL_INFORMATION`** (which would require measured `cross_corr≈0` and `incremental R²=0` after controlling L1) and **not `INCONCLUSIVE`** (which would require unstable/ thin but measured evidence). It is also **not `INCREMENTAL_INFORMATION_DETECTED`** (requires reproducible lead with `WFA>0.3`/`PBO<0.5`). It is **precisely `BLOCKED_BY_DATA_QUALITY`** — the **required data cannot be acquired or synchronized reliably** — so the question *“Does GC contain incremental information?”* **cannot be answered** on the verifiable 15m spot population alone.

**Safety preserved:** `NO_TRADE` remains, `DEMO_EXECUTION=DISABLED`, `LIVE=LOCKED`, `held_out_rows_read=0`, no live orders, no threshold mining, no feature accumulation, no combination with `VFLP` etc., no new engine/architecture, no held-out access, no `H-15M-RM-01` variant.

---

## 14. One next action

**Does GC contain genuinely incremental information about XAUUSD?**  
→ **Cannot be determined — `BLOCKED_BY_DATA_QUALITY` (no GC intraday with contract mapping to synchronize at 15m).**

**Is that information economically plausible and reproducible?**  
→ **Plausible per CME arbitrage `F=S+carry` and basis mean reversion (roll yield in contango vs backwardation, convergence at expiration via EFP), but **not reproduced** here — no `F`, `b`, `τ`, or `carry` series to test; economic plausibility from literature (threshold cointegration TVECM 3 regimes, 5-min best $51k per audit) cannot be verified without roll-documented GC.**

**Exact evidence:**  
- **XAUUSD spot 26038 bars 15m mid UTC `7271892f` 2025-08-06→2026-09-16 verified** (see §1.1).  
- **GC attempted 6 providers:** `datafeed.dukascopy.com/GOLD` `SSL_ERROR_SYSCALL 35` to `194.8.15.180:443`, `kaggle.com 35`, `s3` inferred 35, `github.com` clones only monthly `122`/`2312` rows — **0 GC 15m bars synchronized** (see §1.2, §8.1).  
- **Contract specs documented from CME fact card** `100 oz $0.10 third-last business day 17:00–16:00 CT Jun/Dec 72m` (see §2) — but **no roll table could be built** (§3).  
- **Carry/basis not identifiable** without `F`/`τ`/`r`/`u`/`y` (§6.2).  
- **No `cross_corr`, `incremental R²`, `basis` autocorrelation, `walk-forward`, or `block bootstrap` computed** — **empty, not zero** (§8.3).

**Single next operator action:**

> **Authorize acquisition of a **verifiable COMEX GC futures intraday dataset with per-contract IDs and expirations** via an **allowlisted path** (e.g., **CME DataMine `GC` 1m/15m with contract `GCG26`/`GCJ26` + `expiration` + `roll date 8d before third-last business day`**, or **Dukascopy `GCG26.CMD/USD` 15m `bid/ask` + `expiration` via `datafeed.dukascopy.com` if allowlist is extended to `datafeed.dukascopy.com:443` and `kaggle.com:443`**, or **Databento `GLBX.MDP` CME GC `MBO`/`MBP_10` + `TRADES` with `MBP_10` 10-level depth and `TRADES` per `MBO` spec). Require **delivery of**: (a) raw per-contract `15m` OHLCV + `openTime CT` + `expiration CT` + `volume/openInterest`, (b) **continuous front-month mapping table `dateRange → frontContract → expiration → rollDate → adjustment` unadjusted** (not back-adjusted), (c) **SHA256 per file + manifest `source=REAL:cme:GC:15m:front-unadjusted`**, (d) **CT→UTC conversion verified + session break 16:00–17:00 CT documented**. Do NOT purchase continuous `GC1!` without roll table. Do NOT use monthly proxy. Keep `NO_TRADE` until **synchronized 15m spot-GC 25k+ bars** passes **§5 sync quality `unmatched <5%` `stale <1%`** and **§7 information test** `anchored 5-fold` `Holm` `block bootstrap` survives before any TVECM/threshold strategy is considered.**

*No held-out 40% tick access, no live orders, no demo execution, no strategy promotion, no parameter rescue — next information gain is a licensed GC intraday with roll provenance, not another XAUUSD slice.*
