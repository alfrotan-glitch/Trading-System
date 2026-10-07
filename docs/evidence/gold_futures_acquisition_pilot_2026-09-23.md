# Gold Futures Acquisition Pilot — 2026-09-23

**Branch:** `arena/01a0cdf1-trading-system` → `d1576a9` + this pilot  
**Type:** **GC Futures Acquisition Pilot only** — not a trading experiment, no basis research, no TVECM/pairs/threshold/optimisation, no held-out 40% access, no purchase, `NO_TRADE` `DEMO_EXECUTION=DISABLED` `LIVE=LOCKED`.  
**Question:** Can QTS obtain and correctly understand **real, per-contract COMEX GC intraday data** well enough to make the subsequent *Gold Futures Basis — Information Test* scientifically valid?

---

## 1. Provider / source

### 1.1 Target (required for a valid pilot)

| Field | Required | What was attempted |
|---|---|---|
| **Exchange** | COMEX (CME Group) | COMEX GC — see §2 |
| **Product** | Gold Futures `GC` (100 oz) — not `MGC` micro, not `GC1!` continuous | GC `GCG26` etc. — see §2 |
| **Granularity** | **1-minute or 15-minute** intraday (pilot: several weeks–few months, 1–2 contracts) | **15m** (to sync with existing XAUUSD 15m `26038` bars) |
| **Fields per observation** | `contract ID` + `timestamp` + `OHLC` + `volume` + `openInterest` + `exchange/session` + `expiration` | All required — see §4–6 |
| **Continuous** | **No** — per-contract unadjusted, with explicit `dateRange→contract→expiration→rollDate→adjustment` (§5) — `GC1!`/back-adjusted rejected | Must keep pilot unadjusted |

### 1.2 Candidate providers enumerated (catalog vs measurement)

| Provider | Dataset / product | Exact instrument | Download path (if known) | Historical coverage | Source timestamp | Source timezone | License/access terms | Cost | Attempted | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| **Dukascopy Bank SA** | `datafeed.dukascopy.com` `BI5` tick → `GOLD.CMD/USD` or `GC` futures CFD | `GOLD.CMD/USD` (GC proxy) — *needs mapping verification* | `https://datafeed.dukascopy.com/datafeed/GOLD/{YYYY}/{M}/{DD}/{HH}h_ticks.bi5` (`XAUUSD` uses `XAUUSD` path, `POINT_VALUE 1000` 20-byte `>iiiff`) | 2003+ (FX/metals tick) | Tick `time_msc` | **UTC/Geneva** (Dukascopy) | Free personal, no redistribution (no LICENSE file) | Free | **Attempted** `curl -v -m15 https://datafeed.dukascopy.com/datafeed/GOLD/2025/07/06/00h_ticks.bi5` → **BLOCKED** (see §7) | `SSL_ERROR_SYSCALL 35` to `194.8.15.180:443`, `ping 8.8.8.8 0% loss`, `github.com 200` vs `datafeed 000` |
| **Tradovate / TradingView via Kaggle** | `COMEX Gold Futures Dataset (GC Contract)` `GC_in_15_minute_new.csv` 458 KB | `COMEX:GC1!` continuous *but file is 15m* `2025-06-30 23:30 3324.0/3324.2/3320.3` examples | `https://www.kaggle.com/datasets/youneseloiarm/comex-gold-futures-dataset-gc-contract` | 2025-06-30→2025-10-15 (per page) | TradingView `GC1!` 15m bar | Not documented (likely UTC or CT) | Kaggle CC, TradingView Terms | Free | **Attempted** `curl -I -m10 https://www.kaggle.com/datasets/...` → **BLOCKED** `SSL_ERROR_SYSCALL 35` to `kaggle.com:443` | Same egress block |
| **Portara / CQG** | `GCA` (GC) `1-min` intraday `GCA2026Q.txt` sample + full 623 MB 1987→now | `GCA` = GC combined | `https://portaradownloadersampledata.s3.amazonaws.com/1%20Minute/GCA/GCA2026Q.txt` (sample) | 1987-09-03→now (Portara) | CQG `1-min` | Exchange (CT) | Paid full, sample free via `s3.amazonaws.com` | Paid + sample free | **Not directly curled** (inferred block — `s3.amazonaws.com:443` same 35 as `fred`/`kaggle`/`datafeed`) |
| **GitHub `Prachi-Gopalani13/Commodity-Price-Prediction`** | `Gold Futures Historical Data.csv` 122 lines monthly `May 20 1,700.90` | Gold Futures (unspecified contract) | `https://github.com/Prachi-Gopalani13/Commodity-Price-Prediction` (`git clone` allowlisted) | 2018–2020 monthly | Monthly `Date` | Not documented | No LICENSE (implicit) | Free | **Cloned** `122` lines (see §7) | **Unsynchronizable** — monthly, no contract IDs, no intraday, no timezone, wrong period |
| **GitHub `datasets/gold-prices`** | `data/monthly.csv` 2312 rows `1833-01,18.930` | World Bank Pink Sheet Gold (spot proxy, **not GC futures**) | `https://github.com/datasets/gold-prices` | 1833–2025-07 monthly | Monthly | — | PDD | Free | **Cloned** `2312` rows | **Not GC** — monthly spot proxy, not futures, no contract |
| **GitHub `olddatasets/gold-spot-downloader`** | `data/latest.csv` (would be `GC=F` via `yfinance`) | `GC=F` (Yahoo) | `https://github.com/olddatasets/gold-spot-downloader` | 1258→present (but `data/` missing) | `yfinance` daily | — | — | Free | **Cloned** — `data/latest.csv` **does not exist** (`No such file`) | No GC intraday |
| **GitHub `theorycraft-trading/dukascopy`** | Elixir `Dukascopy` lib — docs `BRENT.CMD/USD` etc. | Code only, no data | `https://github.com/theorycraft-trading/dukascopy` | — | — | — | MIT | Free | **Cloned** | Code only; download would hit blocked `datafeed` |
| **CME DataMine / Nasdaq Data Link `CHRIS/CME_GC1`** | CME GC continuous `GC1` daily | `CHRIS/CME_GC1` | `https://data.nasdaq.com` | 1975→now daily | CME settlement | CT | Paid (key) | $ | Not attempted (requires key + `api.nasdaq.com:443` blocked same `35`) |
| **Databento `GLBX.MDP` CME GC `MBO`/`MBP_10`/`TRADES`** | `MBO` L3 per-order, `MBP_10` L2 10-level, `TRADES` | `GC` `MBO` `GCG26` etc. | `https://databento.com` | 2010+ tick | CME `MBO` | UTC (CME) | Paid $500–2000/mo | Free | PLANNED, not attempted (paid) |

**Allowlist evidence:** `github.com:443` `200`, `api.github.com:443` `SSL success`, `codeload.github.com:443` `SSL success` — **allowlisted**; `datafeed.dukascopy.com:443`, `kaggle.com:443`, `fred.stlouisfed.org:443`, `stooq.com:443`, `query1.finance.yahoo.com:443`, `api.nasdaq.com:443`, `cdn.jsdelivr.net:443` all `SSL_ERROR_SYSCALL 35` + `http` `Empty reply 52`, `ping 8.8.8.8 0% loss` (ICMP allowed, TCP 443 blocked for non-allowlist) — **same block as `1.3` macro test**.

**Conclusion §1:** **No GC intraday per-contract with contract IDs acquired** via any allowlisted path without violating `GC1!`/unverified-continuous rule.

---

## 2. Contract(s) — what was targeted for the pilot

**Pilot minimum per instruction:** 1–2 specific GC contracts, preferably one near/active + one subsequent, several weeks–few months, `1m` or `15m`.

**Targeted (if GC were acquirable):**

| Target | Contract example | Why | Period (if GC available) |
|---|---|---|---|
| **Near/active** | `GCZ25` (Dec 2025) — most liquid Aug→Nov 2025 | Front-month during XAUUSD `2025-08-06→2026-09-16` overlap; volume concentrates Feb/Apr/Jun/Aug/Dec [CME fact card] | `2025-08-06 → 2025-11-24` (expiration third-last business day Nov 2025 `2025-11-24` → roll `2025-11-16` 8d before) |
| **Subsequent** | `GCG26` (Feb 2026) — next active | To demonstrate **rollover** and session continuity | `2025-11-16 → 2026-02-24` (Feb 2026 expiration `2026-02-24` → roll `2026-02-16`) |

**What was actually obtained:**

- **Per-contract GC:** **None** — 0 files, 0 contracts, 0 expirations verified (see §5).
- **Closest obtained:** `Gold Futures Historical Data.csv` monthly 122 lines `May 20 $1,700` — **no contract ID**, **monthly**, **no expiration**, **no intraday**, **no `GCZ25`/`GCG26`** — **fails contract gate**.

**Contract specifications (documented from CME, not measured):**

- **Exchange / Rulebook:** COMEX 113, CME Globex/ClearPort [CME fact card]
- **Code:** `GC` (`GCG26` = Feb 2026, `GCJ26` = Apr 2026, `GCM26` = Jun 2026, `GCQ26` = Aug 2026, `GCV26` = Oct 2026, `GCZ26` = Dec 2026)
- **Size:** 100 troy oz, **quotation USD/oz**, **min $0.10/oz = $10**
- **Months listed:** Current + next 2 calendar months + Feb/Apr/Aug/Oct within 23m + Jun/Dec within 72m [StackExchange] — **sparse far months**
- **Last trading day:** **Third last business day of delivery month** (business days exclude holidays; May 2017 Fri May 26 because Mon May 29 holiday) [StackExchange] — **expiration CT date required per contract**
- **First Notice Day:** Last business day of month prior to delivery month [NYMEX 1/7]
- **Trading hours:** **Sun 17:00–Fri 16:00 CT** with **16:00–17:00 CT maintenance break daily** [CME fact card]
- **Roll convention:** **8 calendar days before expiration** (CME `rolldates.html` per StackExchange) or volume/open-interest flip — **must be documented per §5**; most positions roll ~2 weeks before expiration [Gainesville].

---

## 3. License / access

| Source | License / access terms | Access date | Terms verified? | Can redistribute? |
|---|---|---|---|---|
| **XAUUSD Dukascopy via vudo805** | Upstream **NO LICENSE** — `internal research only, no redistribution` [acquisition.json + `docs/data_provenance_xauusd_dukascopy.md`] | 2026-09-23 regeneration (`git checkout 4d6f155`) | **Yes** — repo ships no LICENSE file | **No** |
| **Dukascopy `datafeed.dukascopy.com`** | `Free for personal research, redistribution restrictions` [provider catalog] | 2026-09-23 attempt | Yes (catalog) | No |
| **Kaggle GC `GC_in_15_minute_new.csv`** | Kaggle CC + TradingView Terms (TradingView data `GC1!` is not open) | 2026-09-23 attempt | Yes (page) | No (TradingView) |
| **Portara `GCA` S3 sample** | Paid full, sample free via `s3.amazonaws.com` Terms | — | Yes | Sample only |
| **GitHub `Prachi…` monthly** | No LICENSE file (implicit) | 2026-09-23 clone | Yes | Unknown — not used |
| **GitHub `datasets/gold-prices`** | **PDD** (World Bank) | 2026-09-23 clone | Yes | Yes (but not GC) |
| **CME GC `GC` intraday** | CME DataMine paid, Databento paid $500–2000/mo | Not attempted | Yes | No (paid) |

**Pilot did not spend money** — no paid acquisition, no Databento/CME purchase, no FirstRate bundle.

---

## 4. Timestamp semantics — `CT → UTC` demonstration

### 4.1 Required demonstration (explicit, reproducible conversion)

**CME Gold futures trade in CT (`America/Chicago`):**

- **CT definition:** `CST = UTC-6` (standard, winter), `CDT = UTC-5` (daylight, summer)
- **DST rule:** Second Sunday in March 02:00 local → first Sunday in November 02:00 local — **same as `America/New_York` ET but CT is 1h behind ET** (`ET = CT+1h`).
- **CME session:** **Sun 17:00 CT → Fri 16:00 CT** with **daily break Mon–Thu 16:00–17:00 CT** (1h, no trading) [CME fact card].
- **GC bar open:** e.g., `2025-08-06 00:00 CT` → `05:00 UTC` (CDT), `2026-01-28 19:00 CT` → `2026-01-29 01:00 UTC` (CST) — **off-by-1h if DST ignored**.
- **XAUUSD spot:** **UTC** `2025-08-06T00:00:00+00:00` 15m bar open (Dukascopy, `timezone: UTC`).

**Reproducible conversion (Python, `zoneinfo`):**

```python
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+

ct = ZoneInfo("America/Chicago")  # CME CT
utc = ZoneInfo("UTC")

# Example 1: Winter (CST)
t_ct_winter = datetime(2026, 1, 28, 14, 0, tzinfo=ct)  # FOMC 14:00 CT
t_utc_winter = t_ct_winter.astimezone(utc)
# -> 2026-01-28 20:00:00+00:00  (CST UTC-6: 14:00+6h=20:00 UTC)

# Example 2: Summer (CDT)
t_ct_summer = datetime(2026, 6, 17, 14, 0, tzinfo=ct)  # FOMC 14:00 CT
t_utc_summer = t_ct_summer.astimezone(utc)
# -> 2026-06-17 19:00:00+00:00  (CDT UTC-5: 14:00+5h=19:00 UTC)

# Example 3: Early-close / holiday (if present) — must be flagged per CME holiday calendar
# e.g., 2025-12-24 early close? Not in pilot period, but would be documented per `cmegroup.com/holiday-calendar`
```

**Verification:** Same conversion matches authoritative FOMC `14:00 ET = 13:00 CT` → `19:00/20:00 UTC` (winter `20:00`, summer `19:00`) — consistent with macro test `FOMC_2026-01-28 19:00Z` (=14:00 EST) vs `FOMC_2026-03-18 18:00Z` (=14:00 EDT).

**Do not infer timezone from numeric timestamp alone** — GC numeric `2025-08-06 00:00:00` without `CT` label is ambiguous; must be documented as `America/Chicago`.

### 4.2 Session break handling

| CME session interval (CT) | UTC (winter `CST` / summer `CDT`) | XAUUSD UTC bar exists? | GC bar expected? | Pilot action |
|---|---|---|---|---|
| `17:00–16:00` (next day) continuous | `23:00–22:00 UTC` (winter `23:00–22:00`, summer `22:00–21:00`) | **Yes** 24×5 | **Yes** 23×5 (except `16:00–17:00`) | Keep |
| **Break `16:00–17:00 CT`** | **Winter `22:00–23:00 UTC` / Summer `21:00–22:00 UTC`** | **Yes** (1 bar `21:00–21:15` etc.) | **No** (exchange closed) | **Exclude — do not forward-fill**; count as `session mismatch` (§10) |

**Holidays / early closes:** CME holiday calendar `cmegroup.com/holiday-calendar` would list e.g., `2025-11-27 Thanksgiving` early close — **if present in pilot period, would be documented and bars flagged `holiday`**.

### 4.3 Source timestamp convention (as documented, not measured for GC)

| Source | Timestamp convention | Timezone | Verified? |
|---|---|---|---|
| XAUUSD 15m mid | Bar open `time` ISO `+00:00` | **UTC** | **Yes** (`tz_aware` PASS, monotonic) |
| GC CME `GC` 15m (if acquired) | Bar open `openTime` in **CT** (`America/Chicago`) per CME | **CT** | **Would be verified from raw GC file header** (e.g., `openTime` + `timezone=America/Chicago` field) — **no GC file to verify** |
| Kaggle `GC_in_15_minute_new.csv` | Not documented (example `2025-06-30 23:30` no tz) | Unknown | **Not verified** → rejected as unverified |
| GitHub monthly `Gold Futures Historical Data.csv` | `"May 20"` monthly | Unknown | Not verified → rejected |

**Pilot did not infer timezone from numeric timestamp — CT→UTC requires explicit `CT` label per file, which no GC file provided.**

---

## 5. Contract / expiration mapping

**Required per instruction:** Small explicit table `dateRange → contract → expiration → rollDate → adjustment`.

### 5.1 Expected mapping for a valid pilot (if GC were available — template, 2 contracts, unadjusted)

| Date range (UTC, `XAUUSD` bar opens) | Front contract | Expiration (CT, third-last bus. day) | Roll date (CT, 8d before per CME `rolldates.html`) | Adjustment | Overlap / session |
|---|---|---|---|---|---|
| `2025-08-06T00:00Z → 2025-11-16T16:00CT` (`2025-11-16T22:00Z` winter) | `GCZ25` (Dec 2025) | **2025-11-24** Mon (third-last bus. day Nov 2025; Nov 27 Thu Thanksgiving, Nov 28 Fri, so `24` is `−3` excluding weekend/holiday) — *example, must be verified per CME calendar* | **2025-11-16** | **Unadjusted** (true tradable `F`) | GC break `16:00–17:00 CT` excluded |
| `2025-11-16T17:00CT` (`2025-11-16T23:00Z`) `→ 2026-02-16T16:00CT` | `GCG26` (Feb 2026) | **2026-02-24** Tue | **2026-02-16** | Unadjusted | — |
| `2026-02-16T17:00CT → 2026-04-16T16:00CT` | `GCJ26` (Apr 2026) | 2026-04-27? | 2026-04-19 | Unadjusted | — |

**Do NOT create a continuous series `GC1!` unless this roll rule is explicitly documented — pilot keeps data **unadjusted** (gaps at rolls visible, not smoothed).**

### 5.2 Actual mapping for this pilot

| Date range | Contract | Expiration | Roll date | Adjustment | Observed? |
|---|---|---|---|---|---|
| `2025-08-06→2026-09-16` | **None** | **Not verified** | **Not verified** | **Not created** | **BLOCKED** — no GC per-contract files to map |

**Failure:** Cannot create `contract ID → expiration` for every contract in pilot because **0 contract files** acquired. Monthly `May 20` CSV has **no `GCG26`/`GCZ25` IDs**, so mapping impossible.

---

## 6. Session semantics

| Market | Session (local) | Local → UTC (winter `-6` / summer `-5`) | Overlap with XAUUSD UTC 24×5 |
|---|---|---|---|
| **XAUUSD spot** (Dukascopy) | 24×5 `Sun 22:00 UTC → Fri 22:00 UTC` (approx, gaps absent) | UTC | 24×5 |
| **GC futures CME Globex** | `Sun 17:00–Fri 16:00 CT` with `16:00–17:00 CT` break daily [CME fact card] | Winter `23:00–22:00 UTC` / Summer `22:00–21:00 UTC` | **23×5** — 1h daily where XAUUSD has `1 bar` but GC closed |
| **Pilot requirement** | Document break + holidays, exclude `16:00–17:00 CT` bars from sync, do not forward-fill | — | See §4.2 |

**No GC session to document for pilot period** — would require raw GC `openTime CT` + `session` metadata per bar.

---

## 7. Raw file inventory

### 7.1 Files acquired for pilot (as committed)

| # | File path | Contract | Source | Download date (UTC) | Provider timestamp convention | Provider timezone |
|---|---|---|---|---|---|---|
| **XAUUSD (existing)** | `data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv` | `XAU/USD` spot (CFD) | `vudo805/forex-price-simulator@4d6f155` `data/XAUUSD/*.parquet` | 2026-09-23 regeneration `13:31 UTC` (original `2026-09-18T16:28Z`) | `time` ISO `+00:00` | **UTC** |
| GC | **None** | — | — | — | — | — |
| GC | **None** (GitHub monthly clones not GC intraday) | — | — | — | — | — |

**Per observation/file required (§1):** For XAUUSD, each `15m` bar has `time,open,high,low,close,volume` (`volume` = tick count, not traded volume; `bid/ask` not preserved; `openInterest` not available; `exchange/session` = `MT5` namespace only, not CME). **For GC, contract ID / `openInterest` / `exchange/session` / `expiration` not available — fails minimum pilot.**

### 7.2 Alternative files cloned but rejected as not meeting pilot minimum

| File | Contract ID | Timestamp | OHLC | Volume | OpenInterest | Exchange/session | Expiration | Why rejected |
|---|---|---|---|---|---|---|---|---|
| `test-gold/Gold Futures Historical Data.csv` 122 lines `"May 20","1,700.90"` | **Missing** (monthly bucket) | Monthly `"May 20"` | `Price,Open,High,Low` (no timestamp) | `Vol. "-"` / `"3.73M"` monthly | **Missing** | **Missing** | **Missing** | Monthly `2018–2020`, no intraday, no contract, wrong period |
| `test-gold-prices/data/monthly.csv` 2312 rows `1833-01,18.930` | **Missing** (World Bank spot proxy, not `GC`) | Monthly | `Price` | — | — | — | — | Not GC futures, monthly, not 15m |

**No `contract ID` + `expiration` → fails provenance gate** (“If any of these are unknown, mark the pilot `BLOCKED`”).

---

## 8. SHA256

### 8.1 SHA-256 per acquired file (measured, `sha256sum`)

| File | SHA-256 | Byte size | Row count | Minimum timestamp | Maximum timestamp |
|---|---|---|---|---|---|
| `data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv` | `7271892fa9bacf2a4ad20655d6a019020a4aaf057510e769bb42c5ba59d0a074` | **1,942,?** (measured 1.9 MB, 26039 lines incl. header) | **26038** data rows | `2025-08-06T00:00:00+00:00` | `2026-09-16T23:45:00+00:00` |
| `data/raw/xauusd_dukascopy_1h_mid_agg_20250806_20260916.csv` | `97b457d6ac42743613a6ee48cf6a02c5fe4475e648fc4c1575003ca5e6c624b0` | 482 KB | **6513** | `2025-08-06T00:00:00+00:00` | `2026-09-16T23:00:00+00:00` |
| `GC` 15m/1m per-contract | **Not acquired** | — | 0 | — | — |
| `test-gold/Gold Futures Historical Data.csv` (rejected) | `N/A` (monthly, not pilot) | 8.46 KB | 122 | `Dec 18` | `May 20` | — |
| `test-gold-prices/data/monthly.csv` (rejected) | `N/A` | 2312 rows | — | `1833-01` | `2025-07` | — |

**Row count verified:** `wc -l data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv` = `26039` (1 header + 26038).

**Manifest for XAUUSD (reproducible):** `data/evidence/xauusd_dukascopy_acquisition.json` `schema qts.data_acquisition.v1` `repository vudo805/forex-price-simulator` `commit 4d6f15543e6285fad91fd57fe42f716bc7273075` `per-file SHA` `e650d23…` etc. — **14 parquets + 2 exports**.

### 8.2 GC raw file inventory (empty, with blocking evidence)

**No GC raw files to checksum.** Blocking evidence retained:

- `curl -v -m15 https://datafeed.dukascopy.com/datafeed/GOLD/2025/07/06/00h_ticks.bi5` → `* Connected to 194.8.15.180:443` → `SSL_ERROR_SYSCALL 35` (same as `fred.stlouisfed.org:443` `23.198.148.55:443` and `kaggle.com:443` in macro test — `ping 8.8.8.8 0% loss`, `github.com:443 200` vs `datafeed/kaggle 000` logs).
- `curl -I -m10 https://www.kaggle.com/datasets/youneseloiarm/comex-gold-futures-dataset-gc-contract` → `SSL_ERROR_SYSCALL 35` to `kaggle.com:443`.
- `curl -v -m10 https://stooq.com/q/d/l/?s=gc.f&i=d` / `query1.finance.yahoo.com:443` / `api.nasdaq.com:443` / `cdn.jsdelivr.net:443` / `eodhd.com:443` all `35` — same egress block (only `github.com:443`/`api.github.com:443`/`codeload.github.com:443` `SSL success` allowlisted).
- **No offline SHA to report for GC.**

---

## 9. Canonicalization result

### 9.1 XAUUSD spot — canonicalization PASS (already exists)

| Step | Result |
|---|---|
| **Provider → Raw Storage** | `git clone https://github.com/vudo805/forex-price-simulator` → `git fetch --unshallow` → `git checkout 4d6f155` → `python scripts/acquire_xauusd_dukascopy.py --source-dir /tmp/test-vudo/data/XAUUSD` (pandas 3.0.6) — per-file SHA verified `e650d23…` etc. |
| **Raw preserved** | `data/raw/xauusd_dukascopy_15m_mid_20250806_20260916.csv` `7271892f…` + `1H` `97b457d…` — **never overwritten** |
| **Validation** | `monotonic_time` PASS, `tz_aware` PASS, `ohlc_invariants` PASS, `no_duplicates` PASS — `no_missing_bars` **FAIL 6.42%** (`unexpected 1785/27,823` weekend-only) — **gaps absent, not filled** |
| **Normalization** | `time`→UTC `2025-08-06T00:00:00+00:00`, `mid=(bid+ask)/2` as upstream, `volume` tick count |
| **Canonical Dataset** | `20260918-010+8f120133-1ba57af7` `sha256:1ba57af7d9d034d9` `26038` rows `2025-08-06T00:00Z→2026-09-17T00:00Z` |
| **Manifest** | `data/evidence/xauusd_dukascopy_acquisition.json` + `data/evidence/data_inventory.json` `version 20260918-010+8f120133-1ba57af7` |
| **Reproducibility** | `git` + `sha256` per file + `scripts/acquire_xauusd_dukascopy.py` + `data/raw` SHA — **reproducible** |

### 9.2 GC futures — canonicalization **BLOCKED**

| Step | Result | Reason |
|---|---|---|
| **Provider → Raw Storage** | **Not started** — no GC `BI5`/`CSV`/`parquet` bytes to preserve | `datafeed`/`kaggle`/`s3` egress block |
| **Validation** | **Not run** | No raw file |
| **Normalization** | **Not run** | No `CT` timestamps to convert `CT→UTC` |
| **Canonical Dataset** | **Not created** | No `Manifest` for GC |
| **Manifest / SHA** | **Empty inventory** — §8.2 no files | See §8.2 curl logs |
| **Data licensing** | Would be free personal (Dukascopy) / TradingView Terms (Kaggle) / PDD (World Bank) — but **no dataset to license** | — |
| **Unadjusted** | **Required** — pilot keeps unadjusted (not back-adjusted) — **cannot demonstrate without data** | — |

**Overall canonicalization:** **XAUUSD PASS, GC BLOCKED → pilot cannot proceed to synchronization feasibility beyond XAUUSD alone.**

---

## 10. Synchronization feasibility (only after GC pilot is canonicalized — here: feasibility *assessment* with XAUUSD vs empty GC)

**Do NOT perform an edge test — measure only feasibility metrics (§4–5).**

**Inputs:**

- **XAUUSD 15m** `26038` bars `2025-08-06T00:00Z→2026-09-16T23:45Z` UTC, `900s` cadence, `58` weekend closures + `1785` unexpected gaps `6.42%` (absent).
- **GC 15m** `0` bars (blocked) — **common interval `15m` cannot be formed**.

**Feasibility metrics (with 0 GC bars):**

| Metric | Definition | Threshold to be feasible | Observed (XAUUSD vs empty GC) | Pass? |
|---|---|---|---|---|
| **Common timestamps** | Bars where `|XAUUSD_open_UTC − GC_open_UTC| ≤30s` within GC session | — | **0** | — |
| **Unmatched XAUUSD→GC** | `XAUUSD bars with no GC bar within tolerance` / `XAUUSD bars in GC session` | **<5%** else BLOCKED | **100%** (`26038/26038`) — **no GC** | **FAIL** (if GC existed, would be `unmatched`) |
| **Unmatched GC→XAUUSD** | `GC bars with no XAUUSD bar` / `GC bars` | <5% | `0/0` undefined | — |
| **Stale GC** | `GC bars volume==0` or unchanged `close` >4 bars during GC session | <1% | `0` | — |
| **Session mismatch** | XAUUSD bars during GC `16:00–17:00 CT` break (Winter `22:00–23:00 UTC` / Summer `21:00–22:00 UTC`) | Count, exclude | **~260** bars (1 per day ×260 days) would be mismatch if GC existed | — |
| **Timestamp tolerance** | `CT→UTC` conversion `±30s` | `≤30s` | Not measured (no GC `CT` to convert) | — |
| **Contract/roll overlap** | Bars at `roll date ±1 bar` (8d before expiration) | Flag, exclude | **0** roll dates (no contracts) | — |
| **Synchronized bars** | Bars where both legs present, unadjusted, non-stale, non-roll, within tolerance | **≥1000** for 5-fold? | **0** | **FAIL** |
| **Goal** | Prove synchronization *technically feasible* | `unmatched <5%` **and** `stale <1%` **and** `tolerance ≤30s` | **Cannot be proven — no GC to compare** | **BLOCKED** |

**Interpretation:** If GC `15m` `GCG26`/`GCZ25` with `CT` expirations were available, synchronization at `15m` UTC vs `CT→UTC` is **technically feasible** (smallest defensible `15m` bar is native to both, tolerance `30s` achievable with `zoneinfo` `America/Chicago`, session break is only `1h` daily `~4%` mismatch). **Feasibility cannot be demonstrated without GC bytes** — **blocked, not infeasible**.

**What would be proven if GC existed:** That `XAUUSD 15m UTC` `2025-08-06T00:00Z` aligns to `GCZ25 15m CT→UTC` `2025-08-05 19:00 CT =2025-08-06T00:00Z` (CDT), with `1h` break gap at `21:00–22:00 UTC` summer filtered, and `roll 2025-11-16T17:00 CT` gap flagged.

---

## 11. Failure modes

| Failure mode | Status | Evidence | Would block pilot? |
|---|---|---|---|
| **Network egress block for GC intraday** | **CONFIRMED BLOCK** | `curl -v -m15 https://datafeed.dukascopy.com/datafeed/GOLD/2025/07/06/00h_ticks.bi5` → `SSL_ERROR_SYSCALL 35` to `194.8.15.180:443`; `kaggle.com:443` `35`; `stooq/yahoo/nasdaq/cdn 35`; `ping 0% loss`; `github.com:443 200` vs `datafeed/kaggle 000` logs retained (§1.2, §8.2) — same as macro test `fred` `23.198.148.55:443` `35` | **YES** |
| **No per-contract GitHub mirror** | **Confirmed** — `Prachi` monthly `122` `May 20 $1,700` and `datasets/gold-prices` World Bank monthly `2312` `1833–2025` cloned via allowlisted `github.com` but **no `GCG26`/`GCZ25` 15m intraday with `expiration`/`openInterest`** | `git clone --depth1` success, `wc -l` + `head` (§7) | **YES** |
| **Contract mixing / unverified continuous `GC1!`** | **Prevented** — rejected `GC_in_15_minute_new.csv` 15m `3324.0` (Kaggle 458KB) as unverified (no roll table), and `Gold Futures Historical Data.csv` monthly as unsynchronizable per hard restriction | Web_search Kaggle page `GC_in_15_minute_new.csv 458.08 kB` + `GC1!` `3324` | **Would block if used** |
| **Timezone inference from numeric timestamp alone** | **Prevented** — Kaggle `GC_in_15_minute_new.csv` `2025-06-30 23:30` no `CT`/`UTC` label → **not inferred** | `GC_in_15_minute_new.csv` header unknown | **Would block** |
| **Session mismatch not handled** | **Would be high risk** — XAUUSD `24×5` vs GC `23×5` `16:00–17:00 CT` break `1h` daily (`~260` bars) — **not handled because no GC session metadata** | §4.2, §6 | **YES if GC existed** |
| **Rollover artifact (back-adjust leak)** | **Prevented** — keep pilot **unadjusted** (see §5 template) — no continuous series created | §3, §5 | **Would block if back-adjusted** |
| **Missing `openInterest`/`volume`** | **Blocked** — pilot minimum requires `openInterest` where available — **no GC file to check** | §7 | **YES** |
| **Held-out contamination** | **Not accessed** — `held_out_rows_read=0` as in all `reports/xauusd_*` `safety` | `git status` | No |
| **Cost / purchase** | **Not spent** — no Databento/CME/FirstRate purchase during pilot per instruction | — | No |
| **Overfitting (TVECM/pairs)** | **Not run** — no basis research, no threshold sweep, no `VFLP`/Donchian reuse | — | No |

---

## 12. Final `PILOT_PASS` or `PILOT_BLOCKED`

### Per-gate checks (all must pass for `PILOT_PASS`)

| Gate | Required | Observed | Pass? |
|---|---|---|---|
| **Contract identity verified** | `contract ID` (e.g., `GCZ25`, `GCG26`) per file | **Missing** — 0 GC files, monthly `May 20` has no ID | **FAIL** |
| **Expiration verified** | `expiration CT` third-last business day per contract | **Missing** — no `GCZ25` expiration `2025-11-24` etc. | **FAIL** |
| **`CT→UTC` verified** | Explicit `America/Chicago` → `UTC` with DST, `zoneinfo`, break `16:00–17:00 CT` documented | **Template documented (§4.1) with `2026-01-28 14:00 CT→20:00Z` etc., but no GC `CT` timestamps to convert** | **Partial** (method documented, not executed) |
| **Raw data reproducible** | `SHA-256` + `byte size` + `row count` + `min/max timestamp` per file | **XAUUSD PASS** `7271892f` `26038` `2025-08-06T00:00Z→2026-09-16T23:45Z` — **GC FAIL** `0` files | **FAIL** |
| **Manifest / checksums exist** | Complete inventory `version, checksum, rows, start/end, provider, timezone, provenance` | **XAUUSD PASS** `xauusd_dukascopy_acquisition.json` `1ba57af7` — **GC FAIL** empty inventory | **FAIL** |
| **Data is unadjusted** | Per-contract unadjusted (not `GC1!` back-adjusted) | **No GC series to be unadjusted**; monthly clones rejected as unverified continuous | **FAIL** |
| **Synchronization can be performed reliably** | `common timestamps`, `unmatched <5%`, `stale <1%`, `tolerance ≤30s`, `roll overlap` flagged, `≥` few 1000 sync bars | **0 synchronized bars**, `unmatched 100%` (no GC) | **FAIL** |

### Overall

**`PILOT_BLOCKED`**

**Blocking reason (exact):**

> **No real, per-contract COMEX GC intraday (`1m`/`15m`) with `contract ID → expiration` could be acquired via any allowlisted path without violating “Do NOT use `GC1!` / unverified continuous / monthly” — `datafeed.dukascopy.com:443` (`GOLD` `BI5` tick), `kaggle.com:443` (`GC_in_15_minute_new.csv` 15m `GC1!` 458KB `3324.0`), `stooq.com`/`query1.finance.yahoo.com`/`api.nasdaq.com`/`cdn.jsdelivr.net` all `SSL_ERROR_SYSCALL 35` to `...:443` (egress block for non-allowlist; `ping 8.8.8.8 0% loss`, `github.com:443 200`/`api.github.com 200` vs `datafeed/kaggle/fred 000` logs retained); allowlisted `github.com` clones yielded only **monthly** `Gold Futures Historical Data.csv` `122` lines `May 20 $1,700` and World Bank `2312` rows monthly (not GC, no `GCG26`/`GCZ25`, no intraday, no `expiration`, no `openInterest`, no timezone) — **unsynchronizable at 15m** and **fails contract/expiration gate**. Therefore **`contract ID → expiration` for every contract in the pilot cannot be demonstrated**, `CT→UTC` cannot be executed on GC bytes, `SHA-256` inventory for GC is empty, and **synchronization feasibility cannot be measured** (0 sync bars, `unmatched 100%`). This is **`BLOCKED_BY_DATA_QUALITY` due to network allowlist for GC intraday providers**, not data absence or synthesis — **no money spent, no `GC1!`, no back-adjusted continuous used**.

**Success would have been `PILOT_PASS` only if:** `GCZ25` `GCG26` (or similar) `15m` unadjusted per-contract CSV with `contract, expiration CT (third-last bus. day), openTime CT, OHLCV, openInterest, session` + `SHA256` + `manifest` + `CT→UTC` example (`2026-01-28 14:00 CT→20:00Z` winter etc.) + `unmatched <5%` `stale <1%` sync vs XAUUSD `26038` bars could be demonstrated.

---

## 13. Exactly one next operator action

> **Extend the sandbox network allowlist to the GC intraday provider(s) required for the per-contract pilot before any purchase, or authorize a paid GC intraday dataset that is already on an allowlisted path.** Specifically, **choose one**:
> - **(A) Allowlist `datafeed.dukascopy.com:443` (Dukascopy `GOLD.CMD/USD` `GCG26`/`GCZ25` `15m`/`1m` `BI5`/`CSV` + `expiration` metadata)** — *free, no purchase, same `vudo805` method as XAUUSD spot* (`git clone` already allowlisted, only `datafeed` egress blocked) — then re-run `python scripts/acquire_xauusd_dukascopy.py --source-dir` equivalent for `GOLD` with `CT→UTC` + per-contract `expiration` third-last business day + `SHA256` manifest (pilot: 2 contracts, several weeks–few months, unadjusted, `§5` roll table), prove `unmatched <5%` sync vs XAUUSD `15m` before any basis research.
> - **(B) If allowlist cannot be extended, authorize a small paid pilot that is fetchable via allowlisted `github.com` or already-approved egress** (e.g., **Databento `GLBX.MDP` CME GC `MBO`/`TRADES` 1-day `15m` sample + `CME DataMine` GC `1m` sample with `contract→expiration` file** — request **sample, not full history**, with explicit `contract ID→expiration` table, keep unadjusted, no `GC1!`). **Do NOT purchase full 623 MB `GCA` `623 MB` or Kaggle `458 KB` until pilot `PILOT_PASS` with `SHA` + `CT→UTC` + `sync <5%`.**
>
> **Keep `NO_TRADE` `DEMO=DISABLED` `LIVE=LOCKED`, no basis/TVECM/pairs/threshold research, no `GC1!`/monthly proxy, no held-out 40% access until `PILOT_PASS` (`contract` + `expiration` + `CT→UTC` + `SHA` + `sync`) is achieved. Do not interpret successful sync as edge.**

*No held-out access (`held_out_rows_read=0`), no live orders, no demo execution, no strategy promotion, no parameter rescue — pilot proves data path, not trading signal.*
