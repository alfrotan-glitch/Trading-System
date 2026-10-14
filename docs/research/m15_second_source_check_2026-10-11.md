# M15 second-source check — 2026-10-11

Status: **`getdata-finance` rejected (proven synthetic reopen-bar stitching corruption); `BaseMax` and `Dukascopy mirror` cross-validated via two MIT-licensed MT5 sources (`soloshun` H1 and `xaubot-ai` M15).** No new tuning or re-selection was performed. Both verdicts remain `NO_VALIDATED_EDGE` (costs `ASSUMED`).

Reproduce: `python scripts/check_m15_source_overlap.py --candidate <csv_or_parquet> [--stamp-basis utc|server_gmt23_us_dst|server_gmt23_eu_dst] --out <json>`
(the reference is the Dukascopy mirror replicate, fetched and SHA-256-verified by
`scripts/fetch_longhistory_sources.py`).

## Why a second source was needed

The long-history verdicts rest on one primary series (BaseMax 15m, 2004–2025). The
other initially pinned sources (`ejtraderLabs`, `Yuan`) are the same quote stream, not
independent confirmation (see `longhistory_data_provenance_2026-10-10.md`). Because the
BaseMax research cut (`2004-06-11..2025-02-28`) ends before the Dukascopy mirror
(`2025-08-06..2026-09-16`), bridging series were needed to verify both streams' price
basis and clock conventions.

## Candidates evaluated

| Candidate | Coverage | Licence / terms | Provenance | Decision |
|---|---|---|---|---|
| `novandraanugrah` Kaggle XAU 15m (CC0) | 2004 → 2025-08 | CC0 | Same upstream as BaseMax (see provenance note) | **Not independent.** Excluded. |
| `getdata-finance/xauusd-15m-ohlcv-metals-historical-data` `XAUUSD_15m.csv` @ `c4ca49e` (2026-09-30) | 2026-03-26 02:30 → 2026-09-25 20:30 UTC, 11,989 bars | MIT (Copyright GetData 2026) | Upstream vendor undisclosed; **proven corrupted prior to `2026-08-23 22:00 UTC`** (141 synthetic `22:00 UTC` reopen bars with 12-decimal floating-point tick volumes and forced zero weekend gaps) | **Rejected** (see §1 below). |
| `getdata.finance` full archive (≈404k 15m rows, from 2009-02-24) | Long history | Not verified: vendor page returned a Cloudflare tunnel error | Same vendor as corrupted sample above (`XAUUSD_3d.csv` / `XAUUSD_12h.csv` exhibit identical floating-point volume corruption back to 2024) | **Rejected.** |
| `soloshun/Quantitative-XAUUSD-Strategy` `data/raw/xauusd_h1_2015_present.parquet` @ `59526d66` | 2015-01-02 09:00 → 2025-09-26 08:00 (`GMT+2/+3` US-DST), 63,239 H1 bars | **MIT** | `MetaQuotes-Demo` MT5 export (`src/data_acquisition.py`, `.env.example` `SERVER=MetaQuotes-Demo`) with native `spread` and `tick_volume` | **Identifies BaseMax upstream (`100.0%` exact match on 61,211 H1 bars) and bridges BaseMax into Dukascopy (`2025-08..09`, 848 H1 bars)** (see §2 below). |
| `GifariKemal/xaubot-ai` `data/training_data.parquet` @ `10301c86` | 2025-06-24 07:00 → 2026-02-11 03:45 (`GMT+2/+3` EU-DST `Europe/Athens`), 15,000 M15 bars | **MIT** | Independent MT5 broker M15 export (`src/mt5_connector.py`) with native `spread` and `volume` | **Confirmed independent M15 confirmation overlapping both BaseMax (`754` bars) and Dukascopy (`12,084` bars)** (see §3 below). |

---

## 1. Forensic proof of `getdata-finance` corruption vs. Dukascopy replicate

SHA-256 of the sample CSV: `b23257db4b38cbffe431b98449f1aef523cecc232f659e79781aeeff8f2bb4c9`.
Dukascopy replicate loaded: 26,038 bars, 2025-08-06 00:00 → 2026-09-16 23:45 UTC.

1. **Timestamps.** Shift scan from −6 h to +6 h in 15-minute steps gives best alignment
   at **0 h in every month** (March–September).
2. **Whole-period level mismatch.** Over the 11,090-bar overlap, median (`getdata − Dukascopy`)
   close is **+$13.55**, mean +$22.34, std $31.71:

| Month (2026) | Overlap bars | Median Δ close ($) | Std ($) | `non_integer_volume_bars` | `open == prev_close` share |
|---|---:|---:|---:|---:|---:|
| March (from 26th) | 357 | +93.71 | 4.27 | 5 | 1.0000 |
| April | 1,929 | +67.78 | 32.49 | 29 | 0.9990 |
| May | 1,890 | +56.08 | 21.59 | 30 | 0.9995 |
| June | 1,986 | +13.37 | 18.52 | 35 | 0.9995 |
| July | 2,076 | +0.48 | 12.06 | 26 | 0.9995 |
| August | 1,816 | +14.49 | 7.96 | 16 | 0.9979 |
| September | 1,036 | −0.15 | 0.15 | **0** | 0.9988 |

3. **Root cause established (`bar_integrity_diagnostics`).** The March–August level gap is
   **not** a futures/spot basis difference and **not** an error in the Dukascopy mirror.
   Prior to `2026-08-23 22:00:00 UTC`, `getdata-finance` corrupted its session-reopen bars:
   - **141 bars with impossible 12-decimal floating-point tick volumes:** Although the
     `getdata-finance` README defines `volume` as integer *"Tick volume (number of price
     updates in bar)"*, 141 bars between `2026-03-26` and `2026-08-20` (almost all stamped
     at `22:00:00 UTC`, the daily reopen after the `21:00–22:00 UTC` NY break and the Sunday
     `22:00 UTC` weekend reopen) contain floating-point volumes such as `17570.455908954485`
     (`2026-03-26 22:00`), `19649.951518342143` (`2026-03-29 22:00`), and `15943.562952243126`
     (`2026-04-12 22:00`).
   - **Synthetic gap suppression across 48-hour weekends (`open[t] == close[t-1]`):** Across
     all 11,988 bar transitions in `getdata-finance`, **99.91% (`11,977/11,988`)** satisfy
     `open[t] == close[t-1]` exactly — including **24 out of 26 weekend reopen bars** after
     48-hour market closures. Those synthetic `22:00 UTC` bars injected artificial jumps
     (e.g., `+$8.24` on `2026-03-29 22:00`, `+$10.38` on `2026-03-31 22:00`, `+$39.32` on
     `2026-04-12 22:00`, `-$20.76` on `2026-04-05 22:00`; step-error std **$11.13** across
     the 184 corrupt/reset bars) that accumulated as a random-walk price offset (`+$104.60`
     above Dukascopy by `2026-03-31 22:00 UTC`).
   - **Periodic splice resets back to Dukascopy spot level:** On **`2026-04-01 22:00:00 UTC`**,
     `getdata-finance` broke its `open == prev_close` chain with a single-bar **`-$102.775`
     reset** (`prev_close = 4862.965 → open = 4760.19 → close = 4760.00`, `vol = 1922.025669`),
     snapping from `+$104.60` error directly onto Dukascopy's exact spot price (`4760.40 →
     4759.03`, residual `+$0.97`). A final **`-$17.49` splice reset** occurred on
     **`2026-08-23 22:00:00 UTC`** (`4625.56 → 4608.07`), after which floating-point volumes
     ceased (`0` in September) and `getdata-finance` agreed with Dukascopy to within
     **`-$0.155` median (`std = $0.303`)** across all 1,575 bars from `2026-08-23 22:00` to
     `2026-09-16 23:45 UTC`.
   - **Intraday return agreement on clean bars:** Even before `2026-08-23`, across all
     **10,906 clean intraday bars** (`volume % 1 == 0` and normal transitions), 15m bar
     changes (`Δclose`) between `getdata-finance` and Dukascopy have a correlation of
     **`0.9995`**, a median absolute difference of **`$0.105`**, and a std of **`$0.220`**.

---

## 2. Bridging `BaseMax` (`2004–2025`) to `Dukascopy` (`2025–2026`) via `soloshun` (`MetaQuotes-Demo` MT5 H1)

Repository: `soloshun/Quantitative-XAUUSD-Strategy` @ `59526d66493a034376c0cdab2ad8c07e4c64215c` (MIT License).
File: `data/raw/xauusd_h1_2015_present.parquet` (`1,874,195` bytes, SHA-256 `5d138b85984f9a59e77df211a21424edd24434a38f0e0fd287bff5c9f265f62d`).
Coverage: `63,239` H1 bars from `2015-01-02 09:00:00` to `2025-09-26 08:00:00` (`GMT+2/GMT+3` US-DST server clock), exported via `src/data_acquisition.py` (`mt5.copy_rates_range`, `.env.example` `SERVER=MetaQuotes-Demo`) with native MT5 columns `['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']`.

1. **Identifies `BaseMax` upstream and proves `bid` price basis:** Comparing `soloshun` H1
   against `BaseMax` M15 resampled to H1 across **61,211 overlapping H1 bars (`2015–2025`)**
   at `0h` server-clock shift yields **`100.0%` exact `$0.0000` close agreement (`exact_0 = 1.000`)
   in every year `2015–2024` (`0.998` in `2025`)**. This establishes that the `BaseMax` /
   `ejtraderLabs` / `Yuan` quote stream is the `MetaQuotes-Demo` MT5 `bid` bar history.
2. **Bridges `BaseMax` directly into the `Dukascopy mirror` window:** Because `soloshun`
   continues cleanly through `2025-09-26 08:00`, it overlaps `Dukascopy mirror` (resampled
   to H1) across **848 H1 bars (`2025-08-06` to `2025-09-26`)**. After converting `soloshun`
   via `server_gmt23_to_utc`:
   - `median(soloshun_close − duka_close) = -$0.0793` (`median_abs = $0.0850`, `p95_abs = $0.2733`, `std = $0.1795`).
   - `soloshun`'s native MT5 `spread` column in 2025 has median `5 points` (`$0.05/oz`) and
     mean `7.50 points` (`$0.075/oz`; `2015–2019` median was `15–35 points` = `$0.15–$0.35/oz`),
     confirming that `soloshun`/`BaseMax` is MT5 `bid` and `Dukascopy mirror` is spot `mid`.

---

## 3. Independent M15 cross-validation via `GifariKemal/xaubot-ai` (MIT License)

Repository: `GifariKemal/xaubot-ai` @ `10301c8665443d2b83569840df65de49b6890cbe` (MIT License).
File: `data/training_data.parquet` (`3,700,130` bytes, SHA-256 `cc654dc13c67304391a081db7ebe2f7eaa8e0fbfddf3c19bf106e48cdb447304`).
Coverage: `15,000` M15 bars from `2025-06-24 07:00:00` to `2026-02-11 03:45:00`, with native MT5 `open, high, low, close, spread, real_volume, volume` (`non_integer_volume_bars = 0`).

1. **Independent of `BaseMax` (`2025-06..07`):** Over the 754 M15 bars overlapping `BaseMax`
   raw in June–July 2025 (at `0h` server-clock shift), `median(xaubot − basemax) = -$0.1400`
   (`median_abs = $0.1400`), confirming `xaubot-ai` is a distinct MT5 broker quote stream
   (median MT5 bar `spread = 14 points`, p75 `20 points`, p95 `21 points`).
2. **EU-DST (`Europe/Athens`) vs. US-DST (`America/New_York`) server clock:** During
   `2025-10-26..2025-11-01` (when European DST had ended at `UTC+2` but US DST remained at
   `UTC+3`), `xaubot-ai` aligns with UTC Dukascopy at **`-2h`** (`median_abs_diff = $0.2767`,
   `p95 = $0.5326`) rather than `-3h` (`median_abs_diff = $9.5518`). `server_gmt23_eu_dst_to_utc`
   (`stamp_basis="server_gmt23_eu_dst"` in `qts.research.longhistory.sources`) normalizes
   this exact schedule.
3. **6.2-month M15 agreement against `Dukascopy mirror` (`12,084` bars, `2025-08-06..2026-02-11`):**
   - **Close correlation:** `1.000000`; **15m return correlation:** `0.999033`.
   - **Overall (`xaubot_bid − duka_mid`):** median **`-$0.2250`**, median abs **`$0.2285`**,
     p95 abs **`$0.4885`**, std **`$0.2721`**.

| Month | Overlap M15 bars | Median (`xaubot − duka`) ($) | Median \|Δ\| ($) | p95 \|Δ\| ($) | Std ($) |
|---|---:|---:|---:|---:|---:|
| 2025-08 | 1,632 | −0.2100 | 0.2100 | 0.3482 | 0.1220 |
| 2025-09 | 2,002 | −0.2050 | 0.2050 | 0.3699 | 0.1668 |
| 2025-10 | 2,088 | −0.2615 | 0.2650 | 0.5082 | 0.2432 |
| 2025-11 | 1,817 | −0.2050 | 0.2050 | 0.4150 | 0.2160 |
| 2025-12 | 1,979 | −0.2465 | 0.2500 | 0.4853 | 0.2330 |
| 2026-01 | 1,914 | −0.2285 | 0.2335 | 0.5700 | 0.4171 |
| 2026-02 | 652 | −0.2608 | 0.2750 | 0.8868 | 0.4871 |

4. **Engine replication on the 133 common complete trading days (`2025-08-06..2026-02-10`):**
   Running the 4 frozen M15 selected candidates under `COST_BASE` on the exact same 133
   complete trading days of `Dukascopy mirror` (`12,080` bars) vs. `xaubot-ai` (`12,176` bars)
   confirms that the Dukascopy replicate P&L and Sharpe figures are genuine spot-gold
   behavior, not feed artifacts:

| Strategy / Benchmark | Dukascopy Net ($) | Dukascopy Turns | Dukascopy Sharpe | `xaubot-ai` Net ($) | `xaubot-ai` Turns | `xaubot-ai` Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| `buy_and_hold_long` | +4,847.30 | 1 | +2.9204 | +4,847.28 | 1 | +2.9146 |
| `ma_32_128_atr3` | +3,123.79 | 114 | +2.6384 | +3,094.46 | 116 | +2.6151 |
| `donchian_384_192_atr3` | +2,746.89 | 19 | +2.6262 | +2,851.01 | 19 | +2.6665 |
| `session_brk_b0` | −1,162.53 | 111 | −2.3653 | −1,073.89 | 111 | −2.1590 |
| `rexp_k10_h16` | −3,726.89 | 808 | −4.3683 | −3,519.59 | 810 | −4.0068 |

## Decision and consequences

- **`getdata-finance` sample: rejected.** Proven to contain 141 synthetic `22:00 UTC`
  reopen bars with floating-point volumes and forced zero weekend gaps prior to
  `2026-08-23 22:00 UTC`.
- **`Dukascopy mirror` and `BaseMax` price basis: cross-validated.** `soloshun` (`MetaQuotes-Demo`
  MT5 H1, MIT) bridges `BaseMax` (`100.0%` match over `2015–2025`) into `Dukascopy mirror`
  (`-$0.079` median offset over `848` H1 bars in `2025-08..09`), and `xaubot-ai` (independent
  MT5 M15, MIT) confirms `Dukascopy mirror` across `12,084` M15 bars (`2025-08..2026-02`,
  `median_diff = -$0.2250`, `std = $0.2721`) and reproduces strategy engine results across
  all 4 frozen candidates.
- **No change to any verdict.** Both verdicts remain `NO_VALIDATED_EDGE`, costs `ASSUMED`.

## Triangulation update (same day): which series disagrees with which

Reproduce: `python scripts/check_m15_source_triangulation.py --out <json>`. Inputs are the
getdata-finance repositories pinned at `ae63d12` (15m), `131c799` (1w) and `05a22e6` (3d).
The 1-week and 3-day samples extend back to 2024-09, which is the one stretch where
getdata overlaps the primary series.

**A. Open prices at identical UTC stamps** (weekly and 3-day samples; the open of a bar
equals the prior close, so the stamps are comparable):

| Comparison | Overlap | Median Δ open ($) | Median abs Δ ($) | Within $0.50 | Median Δ by quarter ($) |
|---|---:|---:|---:|---:|---|
| getdata 1w − BaseMax | 37 (2024-09 → 2025-07) | −0.19 | 1.90 | 24% | 24Q3 −6.3, 24Q4 −2.3, 25Q1 +0.0, 25Q2 +1.3, 25Q3 +9.3 (sparse) |
| getdata 3d − BaseMax | 55 (2024-09 → 2025-07) | −0.13 | 1.17 | 38% | 24Q3 −6.5, 24Q4 −1.1, 25Q1 −0.1, 25Q2 +2.2, 25Q3 +5.1 (sparse) |
| getdata 1w − Dukascopy | 52 (2025-08 → 2026-09) | +14.55 | 15.28 | 2% | every quarter +5.8 to +19.6 |
| getdata 3d − Dukascopy | 92 (2025-08 → 2026-09) | +11.42 | 13.02 | 13% | every quarter +3.0 to +40.4 |

Reading: getdata and BaseMax agree closely in 2025 Q1 (median within $0.10) and differ by
several dollars in 2024 Q3 and Q4. Dukascopy differs from getdata by $3 to $40 in every
quarter they overlap. BaseMax does not overlap Dukascopy, so these data cannot say which
of the two is off. The established fact is narrower: getdata agrees with the primary series
where both exist. That is evidence, not proof, that getdata's basis is the common one.
Neither getdata nor BaseMax is verified as the reference.

**B. Frozen holdout selections on identical bars.** The window is 2026-03-26 02:30 to
2026-09-16 20:45 UTC, the exact common timestamp range. The costs are the protocol's ASSUMED
base. The holdout is not touched, and nothing is re-selected.

| Candidate | Dukascopy net $ (Sharpe, round turns) | getdata 15m net $ (Sharpe, round turns) |
|---|---:|---:|
| donchian_384_192_atr3 | +271 (0.44, 23) | +688 (0.96, 22) |
| ma_32_128_atr3 | −1,311 (−1.34, 113) | −608 (−0.51, 123) |
| session_brk_b0 | +932 (1.67, 110) | +924 (1.70, 111) |
| rexp_k10_h16 | −4,125 (−5.15, 745) | −3,794 (−4.60, 750) |
| buy-and-hold, same bars | −570 (−0.37) | −755 (−0.53) |

Three things follow:
- **The sign of `ma_cross` against buy-and-hold flips.** On Dukascopy `ma_cross` is $741
  worse than buy-and-hold. On getdata it is $147 better. Only the price stream differs.
- **Buy-and-hold alone differs by $185** across the two streams, on identical timestamps.
  The price basis at the two endpoints is different.
- **`session_breakout` agrees on both streams** (about +$930) over this window. Its holdout
  result (−$4,467, 2020–2025) is still negative. A six-month window with 110 round turns is
  not enough to separate a real effect from noise.

Bar coverage also differs. Over the same timestamps, getdata has 262 bars that Dukascopy
lacks (120 in August 2026, 66 in September), and Dukascopy has 20 that getdata lacks.
Each stream has gaps.

**Data-coverage note.** BaseMax's raw file is effectively empty after its research cutoff:
about 2,000 bars a month through February 2025, then 1,388 in March, 368 in April, 2,001 in
May, 928 in June, 744 in July, none in August, and 2 in September 2025. Only 2 bars overlap
Dukascopy (2025-09-30, −$1.03). BaseMax cannot cross-check Dukascopy at all. The research
window ends 2025-02-28, so the verdicts do not depend on this tail.

**Limits.** Both windows are about six months. Round-turn counts are between 22 and 750.
Costs are ASSUMED. Nothing here is gating, and nothing here is evidence of an edge.

## What would close the gap

1. A licensed, documented long-history M15 series with disclosed vendor, licence, and
   timestamp convention, overlapping the Dukascopy window, so the basis question can be
   measured.
2. Measured broker costs and bars from the Windows MT5 DEMO terminal
   (`qts data mt5-depth`, `qts demo cost-check --record`). These come from the same
   broker feed the DEMO account trades against, so they answer a different question than
   a third-party series. Blocked in this sandbox (Linux, no MetaTrader5 package).

## Not claimed

No new edge. No second source validated. Nothing in this note was used to tune or select
any strategy, and the 2025–2026 holdout was not touched.
