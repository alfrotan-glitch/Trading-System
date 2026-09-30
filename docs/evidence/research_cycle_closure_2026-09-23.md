# Research Cycle Closure — 2026-09-23

**Branch:** `arena/01a0cdf1-trading-system` → commit `869db8d` + this closure
**Disposition:** **NO VALIDATED EDGE** — INCONCLUSIVE on discovery sample; H-DIR-01 BLOCKED (not falsified)
**Capital posture:** `NO_TRADE` · `DEMO_EXECUTION=DISABLED BY POLICY` · `LIVE=LOCKED` · `confirm_live=false` · orders_submitted=0
**Held-out integrity:** 69,096,545 rows (40% of raw `time_msc` span) **never opened** by any confirmatory test; H-DIR-01 runner preflight refuses without independently pinned Discovery view

This is the principal-investigator closure for the XAUUSD 730-day canonical tick campaign (2026-09-23) plus the frozen 15-minute Dukascopy real-bar campaign. It is reproducible and auditable: every number below is traceable to a committed report, a GitHub Actions run, or a pinned acquisition manifest. Negative, blocked and inconclusive results are preserved.

---

## 1. What was established

### 1.1 Canonical tick archive — identity and data facts

| Artifact | Value |
|---|---|
| Release / asset | `dataset-xauusd-730d-20260919` / `XAUUSD_730d_20260919T114013Z.zip` |
| Verified ZIP SHA-256 (opaque bytes, runner-measured) | `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723` — `reports/canonical_zip_inventory.json` run `dc7d36c`, `reports/dataset_access_xauusd_730d.json` |
| Acquisition manifest SHA-256 | `d9a61ad583002c6e24f2ad04aee6399e6ec00a9a47928712a7c3f4418e15972f` |
| Dataset digest (`qts.mt5_raw_tick_dataset.v1`) | `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789` — ledger rows = manifest row_count = parquet row count = **139,930,971** |
| Time span (raw `time_msc`) | 1726746013452 → 1789775939790 (provisional UTC 2024-09-19T11:40:13Z → 2026-09-18T23:58:59Z — **UNCONFIRMED clock**) |
| Discovery / held-out split | Discovery `time_msc < 1764563969254` = **70,834,426 rows**; held-out `= 69,096,545 rows` (last 40% of span, never aggregated by any hypothesis) |
| Distribution across ZIP central directory | 734 `part-*.parquet` + `manifest.json` only; no sidecar index, no Discovery partition |
| Boundary audit (manifest-only) | `reports/xauusd_discovery_boundary_audit.json` — Actions `35856015114` (code `90a1633` → `de95a87`, file SHA `f2864545873f98adac4f6b0bd37a806810bca580f006641e3e854efaf3df1153`) — only `manifest.json` opened; `held_out_quote_members_opened=0`, `quote_rows_decoded=0` |
| Boundary finding | **No exact immutable part boundary.** `part-000441.parquet` global `[70,783,710, 70,916,415)` straddles the split: **50,716 Discovery rows + 81,989 held-out rows** in one ZIP-compressed member (`compressed 1,112,372` vs `uncompressed 1,185,224` bytes in `reports/canonical_zip_inventory.json`). Previous `part-000440.parquet` is empty and ends at `70,783,710`. Chunk request window `2025-11-30T11:40:13.383522Z → 2025-12-01T11:40:13.383522Z` is **not** a verified row-time bound. No per-part timestamp or row-group/page index exists in the ledger. |
| Source-search (metadata-only) | `reports/xauusd_discovery_only_source_search_2026-09-23.md` (commit `869db8d`) — 61 post-2026-09-19 ancestors + 12 branch-tip trees via GitHub tree API, Releases (1 asset), Actions artifacts (2× ~1 KB audit) / caches (0), local evidence — **no independently authenticated Discovery-only prefix, view, or view authority** was found. `docs/xauusd_directional_view_authority.json` and `data/raw/xauusd_discovery_view/` remain absent. |
| Data-quality facts (tick archive, Discovery) | `non_monotonic=0`, `negative_spread=0`, `invalid_price=0`; ~6.07 M same-ms excess rows (adjacent-only) but monotonic; 74 consecutive identical quote rows; `volume=0` on every row, `last=0` on every row — no trade prints; flags `{4: 7,963,568, 130: 8,157,814, 134: 123,809,589}` with undefined bit, so flags unused; spread mean 25–27 cents in Discovery terciles, 37–41 cent secondary mode descriptive only; gaps ≥1s 7.7 M, ≥60s 784, ≥3600s 515, ≥24h 108 (UNCLASSIFIED_SPACING, not repaired); `timestamp_interpretation_confirmed=false`; `repairs_applied=[]` |
| Access enforcement | `src/qts/research/xauusd_directional_view.py` — `preflight_view()` validates pinned `view_manifest_sha256` ≠ self-label, all part SHA-256s, and **every row-group `time_msc` min/max** against `cutoff` **before** any `bid/ask` read; mixed-boundary part refused on manifest alone before footer read; cross-cutoff `ViewBoundaryViolation` aborts. `scripts/run_xauusd_directional.py` via `.venv/bin/python` → `{"status":"NOT RUN","held_out_span_opened":false,"strategy_promoted":false}`; `reports/xauusd_directional_access.json` remains `NOT_RUN_ACCESS_BLOCKED`, `safety.orders_submitted=0` |

### 1.2 Process structure that **survived** its locked, cost-stressed gate (still **not** a directional trade)

All below were measured **on the Discovery 70.8 M rows only**, with Holm-Bonferroni (where applicable), tercile agreement and one-quote delay where preregistered. A tiny p-value alone never promoted a hypothesis.

| ID | Status | Locked prediction (effect floor pre-registered) | Measured (primary horizon 256 quotes unless noted) | Interpretation |
|---|---|---|---|---|
| **H-ST-02** | **TESTED** (state/microstructure preregistration) | High `|m_i−m_{i−16}| ≥ $0.20` has larger 256-q absolute move than low `≤ $0.10` (ratio ≥1.25, exceed-spread lift ≥0.05) | high mean abs $1.073 (n 103,498) vs low $0.727 (n 109,532), **ratio 1.476**, lift **7.0 pp**; delay 1.474; 1024-q ratio 1.42; all 3 terciles ≥1.25. Mean **signed** move high +0.8 cent, P(up)=0.506 — **no side**. | Volatility clustering in the quote stream (absolute move, not direction). Reproduction of the same contrast in `xauusd_volatility_state.json` is not a second test. |
| **H-VL-01** | **TESTED** (`docs/xauusd_volatility_preregistration.md` → `xauusd_volatility_state.json`, Actions `35850795793`) | Same H-ST-02 contrast clears **spread + $0.02** and reaches spread+$0.01 sooner | high exceed-spread+2c 79.50% vs low 71.96% — **lift 7.54 pp** (delay 7.56 pp); median wait to spread+1c **17 vs 29 quotes** (ratio 0.586, delay same); dollar gap $0.346 > $0.22; 1024 agrees. High spread 27.6c vs low 25.2c, so scaled moves **3.89 vs 2.88 spreads** — not just wider spread. | Magnitude cost filter survived harsher cost. Descriptive, not executable (no volatility instrument, no side). |
| **H-VL-02** | **TESTED** | Extreme `≥ $0.40` > ordinary high `[$0.20, $0.40)` (ratio ≥1.15, $ gap ≥$0.10) | extreme $1.287 (38,979) vs $0.943 (64,519) — **ratio 1.364**, gap $0.344, delay 1.362; 1024 agrees | Tail continues beyond ordinary high; no saturation. |
| **H-VL-03** | **TESTED** | Quiet-to-expansion > stay-quiet (ratio ≥1.25, $ gap ≥$0.22) | $0.887 (29,318) vs $0.664 (80,073) — **ratio 1.335**, gap **$0.2226**, only **$0.0026 above floor**; delay 1.333 | Passes formally; dollar surplus is two-tenths of a cent — treat as **thin** and not a basis for sizing. |
| **H-VL-04** | **TESTED** | Persistent high > contraction onset (ratio ≥1.15, $ gap ≥$0.10) | $1.389 (19,038) vs $0.960 (62,175) — **ratio 1.447**, gap $0.429, delay 1.446 | Persistence vs onset difference, not exhaustion. |
| **H-SP-01** | **TESTED** | Spread persists more than independence (Δ ≥0.05) | Positive, in `xauusd_microstructure_state.json` | Process fact about quote quoting, not a return predictor; not labeled PROMISING by design. |

**Descriptors, not tests:** unconditional Discovery distribution at 256q: mean abs $0.873 (~3.3 spreads), mean signed +0.59 cent (2.3% of spread), median 1.5c, 10th/90th −$1.345/+$1.355, P(up)=0.505; 4096q signed mean +9.6c, P(up)=0.517 — that common drift plus unstable panel cells (e.g., wide-and-quiet 4096q +30.7c but 256q −1.1c) explains most top-ranked signed generators (**33 generators in state scan, 18 in volatility scan — all `NOT TESTED`**).

### 1.3 15-minute Dukascopy real-bar campaign (separate population, frozen)

*Dataset* `20260918-010+8f120133-1ba57af7` (Dukascopy-derived mid OHLC, 14 pinned source parquets, `sha256:1ba57af7d9d034d9`, 26,038 bars, 2025-08-06→2026-09-16) — provenance `REAL`, venue namespace `MT5` (storage only), registered via `scripts/acquire_xauusd_dukascopy.py`. **Completeness disposition** (`docs/data_completeness_disposition.md` / `data/evidence/xauusd_completeness_disposition.json`): **QUALITY FAILED** — 1,493 legacy unexpected intervals (5.42%) and 1,785 conservative (6.42% of 27,823 active expected intervals) vs 2% gate; recovery candidate `20260918-recovery-140-e563c57e` (+140 bars from earlier upstream history) still FAIL at 1,645 / 5.91%; requires **new authoritative acquisition**. Frozen impulse research (`data/evidence/impulse_research_xauusd_dukascopy_15m.json`, 2026-09-18T15:23Z) remains the only measured outcome: 10 pre-registered families × 2 parameterizations, horizons [12,4], cost 3.4 bps round-turn (ESTIMATED), 3,759 events, 40 trials/180 total DSR — **all 10 families `p_holm=1.0`, gross continuation diff −0.007…+0.021, net bps −2.91…+5.75 with CIs crossing zero, profit factor ~0.89…1.26, DSR ≤0.07**. Conclusion preserved as **`REGIME_DEPENDENT` / `BLOCK`** (go_block=BLOCK). R5 execution-cost history remains FAIL / non-blocking; the 23-window event spread study (median 1.73 bps) is **not continuous** and not an R5 gate input. No impulse hypothesis was promoted, retried, or rewritten.

### 1.4 Safety and auditability

Forward observation, MT5 tick history acquisition, paper/shadow, and experiment ledger (304 trials, DSR 0.00) infrastructure are present and tested but **no real broker acquisition or observation session is present in repository evidence** (`data/evidence/mt5_history_acquisition.json` status `MT5_PACKAGE_UNAVAILABLE` in Linux sandbox; operator-reported limited `copy_ticks_range` capability — 1/7/30-day success, 365-day `Call failed` — is private evidence, not a dataset). Every confirmatory script refuses to repair rows, to silently fill gaps, or to infer session labels (`time_msc` gaps are intensity only). All published research commits preserve `DEMO_EXECUTION=DISABLED`, `confirm_live=false`, `orders_submitted=0`.

---

## 2. What was falsified

### 2.1 Tick-level microstructure and state hypotheses (Discovery 70.8M rows)

| ID | Preregistered claim | Gate | Measured result | Verdict |
|---|---|---|---|---|
| **H-MS-01** | Move > spread reverses >½ after one spread | Rev freq >0.5, mean residual >0 after 1 spread | Non-overlap rev freq **0.49941** (p=0.51), mean residual **−0.803 bps** (bootstrap −0.806→−0.799), delay −0.801 bps, 1-sec gaps −0.804 bps | **REJECTED** |
| **H-MS-02** | Wide spread (× median) → larger scaled next move | Δ wide−narrow >0 | Wide 0.149 vs narrow 0.194 — **Δ −0.0447** (narrow larger) | **REJECTED** (reversed direction) |
| **H-QD-01** | Two-sided same-direction > one-sided in next-quote continuation | Rate diff ≥0.02, delay holds, residual >0 | Below floor | **REJECTED** |
| **H-QD-02** | Next mid-sign dependent beyond independence | | |ab| diff ≥0.02, delay holds | Below floor; one-spread residual negative | **REJECTED** |
| **H-INT-01** | ≤100 ms gap raises P(next ≤100 ms) (lift ≥0.05) | **Lift negative** | **REJECTED** |
| **H-MV-01** | One-sided bid-up → next 1-cent up >½ (≥0.02, mirror, delay, residual, ≥0.50 resolved) | Fails floor/residual | **REJECTED** |
| **H-VOL-01** | ≤100 ms gap → larger 16-q abs move than ≥1000 ms (ratio ≥1.25) | Ratio <1.25 | **REJECTED** |
| **H-SPR-01** | Widen → larger 16-q abs move than tighten (ratio ≥1.10, delay ≥1.10) | Delay ratio <1.10 | **REJECTED** |
| **H-ST-01** | Wide+active > wide+quiet 256-q abs move (ratio ≥1.25, lift ≥0.05) | Ratio **1.197**, lift **3.8 pp** | **REJECTED** (correct sign, floor missed; Holm p≈1e−57 does not override floor) |
| **H-ST-03** | Run length ≥5 fades next 256-q move (fade ≥52%, residual >0 after 1 spread+1c, both sides, delay, terciles) | Fade **49.4%** (15,718), residual **−0.91 bps**, up-runs 48.3%/down 50.5% residuals negative; 1024-q 50.7% (3,865) | **REJECTED** — failed fade is not evidence to follow the run |
| **H-ST-04** | Leaving persistent spread > staying (ratio ≥1.15) | Ratio **1.069**, lift 0.1 pp | **REJECTED** |
| **H-TOD-01** | Hour/session/day-of-week effect | Blocked | **NOT TESTED / BLOCKED** — `timestamp_interpretation_confirmed=false` |
| **H-ST-02 short-horizon intensity**, **15m → tick inference**, **hidden-state clustering** | Re-tests, cross-timeframe extrapolations, unsupervised regime discovery on held-out | Not preregistered / would spend held-out on state selection | **NOT TESTED** — preregistration explicitly forbids reopening or unconstrained model search |

Comparator: independent short-horizon directional hypotheses **H-QD-01/02** and long-run fade **H-ST-03** were already rejected on this same Discovery sample; the 16-q / 256-q volatility contrast does not supply a side.

### 2.2 15-minute Dukascopy real-bar impulse hypotheses

All 10 pre-registered impulse families (IMP-*-B/V) falsified as **incremental predictors after estimated costs**: p_holm =1.0, net expectancy ≈0 (best +5.75 bps with ±~10 bps CI), win rate ~0.434–0.507, DSR ≤0.07. Result frozen as `REGIME_DEPENDENT / BLOCK`. **Not rerun** after completeness correction — rerunning on the still-FAIL dataset would not cure the missing-data gap.

### 2.3 Claims that would be retrofits and stay falsified/not adopted

* That a profitable backtest on this Discovery sample would constitute validation (distinguishes statistical from economic, discovery from validation; `VALIDATED EDGE` requires independent reproducibility + statistical defensibility + economic meaningfulness after realistic cost/delay/degradation + out-of-sample survival + all QTS integrity gates).
* That `TESTED`/`magnitude structure` means `PROMISING`/`ROBUST` or Demo-ready (policy: process magnitude ≠ tradable edge; no volatility instrument for pure absolute-move bets; conditioning on a directional signal requires that signal to be separately supported — it is not).
* That `H-DIR-01` could be salvaged by slicing/truncating `part-000441`, loosening `1764563969254`, skipping its 50,716 Discovery rows, or substituting Dukascopy bars/synthetic 1H/forward-observatory ticks (all different populations — would silently change the preregistered population).

---

## 3. What remains uncertain

1. **H-DIR-01 directional conjecture** — Does the sign of the preceding 16-quote net displacement (`r_i`, `$0.20` high / `$0.10` low) have positive, material, cost-stressed alignment at 256 quotes **inside the high volatility state and more than in the low state** (`T1=N_high ≥ $0.05`, `T2=G_high−G_low ≥ $0.05`, 99% block-bootstrap lower bounds >0, tercile-count gated, one-quote delayed)? **NOT TESTED / BLOCKED** — the complete 70,834,426-row prefix cannot be materialized from the canonical ZIP without opening a mixed, ZIP-compressed member containing held-out rows. 50,716 required Discovery rows are the uncertainty span. Omitting them would change the preregistered inference population.

2. **Magnitude-structure generality** — Would H-ST-02/H-VL-01…04 effect sizes (1.34–1.48 ratios, 3.6–7.5 pp lifts) reproduce on a newly acquired, boundary-aligned dataset or degrade under real commission/latency/fill discretization? The hold-out was never used to estimate them, so they are not overfit to it, but they are not validated either.

3. **State/transition panel sign drift** — 33 state-scan + 18 volatility hypothesis generators are `NOT TESTED` and flip sign across 256/1024/4096q. Horizon 4096 unconditional drift (+9.6c, P(up)=0.517) and wide-and-quiet at 4096 (+30.7c, n 1,007) vs same cell at 256 (−1.1c) illustrate **non-stationarity**, not a strategy.

4. **Temporal/session structure** — Hour, session, weekday, weekend labels and any `H-TOD-01` claim stay **blocked** until MetaQuotes UTC vs server-local offset is measured and `timestamp_interpretation_confirmed` is set via auditable probe. Raw `time_msc` gaps remain usable as intensity only.

5. **15-minute Dukascopy edge conditional on complete data and measured costs** — Would a complete, weekend-correct mid-bar history (≤2% missing) with continuous real spread/bid-ask/tick execution data (R5 PASS) change the `REGIME_DEPENDENT / BLOCK` outcome? Unknown; the only available measurement used estimated costs.

6. **Trade-print microstructure** — Size, aggressor side, `last`/`volume` behavior is **blocked** (fields are zero) on the tick archive, not absent due to missing download.

7. **Execution reality** — Commission, slippage, latency and fill-discretization beyond the conservative `spread+2c` / `spread+1c` delay stresses are unmeasured; any executable claim can only be weaker than the reported counterfactual.

---

## 4. What evidence supports the current conclusion

**Conclusion:** **`NO VALIDATED EDGE`** as defined in the mission lock (independently reproducible + statistically defensible + economically meaningful after realistic costs + robust to delay/degradation + out-of-sample survival + all integrity/safety gates). The tick discovery sample provides **process structure (volatility clustering)** and **multiple rejections**, not a directional edge; the only real-bar campaign is **frozen and completeness-blocked**. This is not proof that no edge could ever exist, only that none has been established on the available, verifiable evidence.

**Evidence chain (all committed, no fabrication):**

* **Identity:** `reports/canonical_zip_inventory.json` (run `4901224` → `dc7d36c` / `64fd3bb`), `reports/dataset_access_xauusd_730d.json`, `reports/xauusd_discovery_state.json` (Actions `35834431066`), `reports/xauusd_microstructure_state.json` (`35837520722`), `reports/xauusd_state_scan.json` (`35844031516`), `reports/xauusd_volatility_state.json` (`35850795793` / `a22f9dc`→`308b432`), plus their `cycle_2026-09-23_*` summaries — each verifies `zip_sha256`, `manifest_dataset_sha256`, row count `139,930,971`, `cutoff 1764563969254` before any extraction; `nonmonotonic=0`, `negative_spreads=0`, `repairs_applied=[]`.
* **Microstructure rejections & H-SP-01:** full descriptive level-1 process facts plus confirmatory H-MS-01/02 in `xauusd_microstructure_state.json` / `cycle_2026-09-23_xauusd_microstructure.md`.
* **State & volatility magnitude structure and rejections:** `xauusd_state_scan.json` (126 panel cells, 33 generators), `xauusd_volatility_state.json` (18 generators), and preregistrations `xauusd_state_preregistration.md`, `xauusd_volatility_preregistration.md`, `xauusd_microstructure_preregistration.md`.
* **Access-blocked, not cherry-picked:** `xauusd_discovery_boundary_audit.json` and `xauusd_discovery_only_source_search_2026-09-23.md` (search of 61 ancestors, 12 branch tips, Releases, 9 Actions runs / 2 artifacts / 0 caches) show the 50,716-row gap is structural; `xauusd_directional_next_step_2026-09-23.md` is the frozen H-DIR-01 protocol (256/1024q, `T1/T2 ≥ $0.05`, 99% block-bootstrap with 9,999 draws, 1,024-anchor blocks, seed `20260923`, tercile-count gated); `xauusd_directional_view.py` + `run_xauusd_directional.py` fail closed (demonstrated `NOT RUN`, `held_out_span_opened=false`).
* **Real-bar impulse:** `xauusd_dukascopy_acquisition.json` (14 SHA-pinned source parquets, HEAD `4d6f155`), `data_provenance_xauusd_dukascopy.md`, `data/evidence/xauusd_completeness_disposition.json`, `data/evidence/xauusd_recovery_candidate_manifest.json`, `research/impulse_continuation_report_xauusd_dukascopy_15m.md` (and frozen `impulse_research_xauusd_dukascopy_15m.json`) with explicit cost/latency sensitivity and ledger accounting (N=304/180, DSR=0.00).
* **Safety:** every `reports/xauusd_*_state.json` and `reports/cycle_*` reports `strategy_promoted=false`, `held_out_span_opened=false`, `safety.DEMO_EXECUTION=DISABLED`, `orders_submitted=0`; `verify_execution_boundary.py` / `test_execution_boundary.py` structural order-free guarantees (only `copy_ticks_range` family reachable; `order_send` unreachable).
* **Self-correction:** volatility preregistration intentionally did not reopen H-ST-02 or chase H-VL-03's thin $0.0026 surplus; microstructure and state campaigns correctly label magnitude survivors as `TESTED` process structure rather than `PROMISING`; quantity failures were not repaired by changing the 2% gate or the 60% time split.

**Least-favorable assumptions retained:** raw `time_msc` used without UTC normalization; gaps left as `UNCLASSIFIED_SPACING` (not called weekends); no global dedup; no row repair; spread+2c + 1c stress + one-quote delay on directional tests; no model fit; no held-out peeking.

---

## 5. Next highest-value autonomous action

**Decision: do not run a new discovery hypothesis on any currently available real dataset in this sandbox. Leave H-DIR-01 preregistered but NOT RUN; treat the tick-magnitude clustering as a descriptive fact to be validated later, not as a prompt for another slice of the same Discovery sample.**

The portfolio of 304 tested variants and four complementary tick-level families has moved this Discovery sample toward **diminishing returns**: the only surviving structure is magnitude clustering with no side, while every directional, transition and spread predictor has been rejected or shown to flip sign across horizons. A further unconstrained feature hunt on the same 60% would spend the remaining held-out sample on model selection without a mechanistic reason, precisely what the mission forbids converting into a strategy.

Expected-information-gain analysis ranks the options:

| Option | Why it is lower value or invalid |
|---|---|
| Truncate H-DIR-01 to `part-000440` boundary (70,783,710 rows) or change `1764563969254` | Silently changes the preregistered population to fit the partition — violates provenance integrity and the *never retrofit a gate* rule; `869db8d` explicitly forbids it. |
| Copy first 441 whole parts and ignore the mixed-part remainder | Drops 50,716 required Discovery rows (0.072% of Discovery); new population ≠ H-DIR-01 population; would be a different, undisclosed experiment. |
| Open `part-000441.parquet` to slice 50,716 rows after a row-group check | Requires decompressing a ZIP member that bundles 81,989 held-out rows — violates the held-out leak prohibition and the task's rule 1. No per-row authenticator exists to prove correctness without that read. |
| Re-query the broker only for Discovery time now and compare counts | Counts ≠ byte-equality, order, or unchanged bid/ask proof; no hash of the original prefix exists to compare against; broker retention may have changed; validation would require opening the mixed part. |
| Substitute Dukascopy 15m bars, the 500-row synthetic 1H fixture, or forward-observatory ticks for the gap | Different instrument transforms/feeds/populations — cannot fill or authenticate the 50,716 missing WM Markets MT5 ticks; would fabricate evidence. |
| New exhaustive discovery-phase search on this same 60% | Adds trials without new data — DSR penalty rises, out-of-sample remains 40% untouched, no mechanism. |
| **Re-acquire a certified Discovery-only tick dataset with a partition-aligned time boundary on the original Windows operator terminal, plus a measured clock-basis confirmation** | **Highest value.** Produces the *only* missing artifact that can make H-DIR-01 (and any future tick validation) falsifiable without leaking held-out: a separately manifested, separately digested, read-only Discovery view whose *every* row-group max `< cutoff` is provably inside Discovery and whose manifest SHA is independently pinned. Also unblocks temporal hypotheses. |

### 5.1 Autonomous plan — what will be done, what will not be done here

**Will be published now (this closure, no data movement):**

1. This closure and `reports/research_cycle_closure_2026-09-23.json` (machine-readable counterpart) are the reproducible record. No `manifest.json`, Parquet, or ZIP is moved or created in this sandbox.
2. A *protocol amendment* stub `docs/preregistration_reacquisition_730d_discovery_2026-09-23.md` will be committed: it specifies the re-acquisition as a **separate physical dataset**, not a rewrite of `XAUUSD_730d_20260919T114013Z.zip` — Discovery time span re-acquired with the **60% cutoff as an explicit chunk boundary** (no chunk may cross it), bounded chunks oldest-first with recursive halving on `Call failed` (as in `mt5_history_acquisition.md`), every field preserved, lossless Parquet write-verify, per-part SHA-256, `dataset_sha256` over sorted part names + hashes, `status=COMPLETE_DISCOVERY_ONLY` view manifest with `source_zip_sha256`, `source_dataset_sha256`, `cutoff_time_msc=1764563969254`, `discovery_rows=70834426` (and `time_msc_min`), plus an independent file `docs/xauusd_discovery_view_authority.json` containing `view_manifest_sha256` pinned **before** the H-DIR-01 runner is allowed to mount the view. A second phase measures clock basis: controlled `copy_ticks_range` probes vs UTC reference, documented offset, and `timestamp_interpretation_confirmed` flag — only then may hour/session studies be unlocked.

**Will not be done in this Linux sandbox (hard external constraint):**

* No `copy_ticks_range` acquisition — `MetaTrader5` requires Windows + a running WM Markets DEMO terminal (`data/evidence/mt5_history_acquisition.json` → `MT5_PACKAGE_UNAVAILABLE` here).
* No clock-basis measurement — requires that same live terminal and a UTC reference capture.
* No new Dukascopy bar acquisition — requires upstream re-clone and gate re-evaluation; completeness cannot be repaired by documentation.
* No held-out opening, no H-DIR-01 execution, no strategy promotion, no Demo/Live orders — enforced by existing preflight gates.

**Will require owner/operator action (true policy decision, not a permission shortcut):** execute the amendment's acquisition on the designated Windows operator machine (Sections 1.1 and 12 of `mt5_history_acquisition.md` / `mt5_demo_setup.md`), publish the Discovery view manifest and its authority file via the same two-runner bounded-JSON pattern used for the boundary audit, and present the SHA-pinned view to a separate runner that holds **only** that view. Only when `preflight_view()` passes on *every* row group may `scripts/run_xauusd_directional.py` be invoked there. Until then every H-DIR-01 report stays `NOT_RUN_ACCESS_BLOCKED`.

**Why this maximizes information gain:** H-DIR-01 is the last *mechanistically motivated* directional falsification left on the tick population (volatility-conditioned impulse persistence) that is not already rejected, has a binding economic floor ($0.05 ≈ 5 grid steps + spread+2c + delay), and directly answers whether the established magnitude clustering has a tradeable side. Its value is zero while the Discovery prefix is uncertifiable; certifying that prefix once also re-enables every future tick validation without re-paying the provenance cost. In contrast, another search on the incomplete mid-bar history re-tests a population already `REGIME_DEPENDENT / BLOCK` with no measured execution data, and another microstructure slice re-tests a rejected family.

### 5.2 Failure mode and stop rule

If the Windows terminal's `copy_ticks_range` retention no longer returns the full Discovery span (the previously measured 365-day `Call failed` regime) or the reacquired Discovery digest cannot be reconciled with the original 50,716-row prefix via a non-held-out-leaking method, that fact will be recorded as a **hard external constraint** and the mission will remain `NO VALIDATED EDGE` for the tick archive — not as a silent substitution.

### 5.3 Success condition remains

`VALIDATED EDGE` = independently reproducible + statistically defensible + economically meaningful (both T1 and T2 floors *and* 99% lower bounds >0) + robust to realistic costs/delay/degradation + survives untouched out-of-sample (the still-closed 69,096,545 rows) + passes all QTS integrity/safety gates. Otherwise `NO VALIDATED EDGE` — the correct outcome for this cycle.

---

*Evidence and code that enforce the above:* `src/qts/research/xauusd_directional_view.py`, `src/qts/research/xauusd_directional.py`, `scripts/audit_xauusd_discovery_boundary.py`, `.github/workflows/canonical-xauusd-discovery-boundary-audit.yml`, `tests/test_xauusd_directional.py`, `tests/test_xauusd_discovery_boundary_audit.py`, and the cited `reports/*.json` / `reports/cycle_*.md` artifacts.

*Negative results preserved:* all REJECTED hypotheses and the two `BLOCKED` boundaries (tick held-out, mid-bar completeness) remain in `docs/xauusd_edge_discovery_map.md`, `data/evidence/xauusd_completeness_disposition.json`, and this closure.

