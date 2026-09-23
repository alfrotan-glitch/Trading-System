# XAUUSD Directional Falsification — H-DIR-02 (Verifiable Discovery Prefix)

**Registered:** 2026-09-23T12:40:00Z — **before** any measurement on the verifiable view
**Parent:** H-DIR-01 in `docs/xauusd_directional_next_step_2026-09-23.md` — mechanism, horizons, cost filter, bootstrap, and economic floors are **frozen and reused verbatim**
**Status:** `PREREGISTERED, NOT TESTED` — H-DIR-01 remains `BLOCKED / NOT RUN` on the canonical 70,834,426-row definition; this is a **distinct, declared experiment** on the maximal verifiable prefix
**Policy:** H-DIR-01 is not silently redefined, truncated, or repaired. A smaller, independently attestable Discovery view is a new population, not a fix. Results of H-DIR-02 will be reported as H-DIR-02, never as H-DIR-01.

---

## 1. Why a new experiment is required

Canonical archive `dataset-xauusd-730d-20260919` (`XAUUSD_730d_20260919T114013Z.zip`, SHA `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723`, manifest digest `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`, rows 139,930,971, `time_msc` 1726746013452→1789775939790, cutoff `1764563969254`) has **no exact part boundary** at its 60% time split: `reports/xauusd_discovery_boundary_audit.json` (Actions `35856015114`, `h_dir_01_ran=false`, `held_out_quote_members_opened=0`) proves `part-000441.parquet` `[70,783,710, 70,916,415)` straddles the split with **50,716 Discovery + 81,989 held-out** rows in one ZIP-compressed member. `reports/xauusd_discovery_only_source_search_2026-09-23.md` proves no authenticated Discovery-only view of the full 70,834,426-row prefix exists; `preflight_view()` correctly refuses, so H-DIR-01 is permanently `NOT_RUN_ACCESS_BLOCKED` in this sandbox without a separate Windows reacquisition (protocol in `docs/preregistration_reacquisition_730d_discovery_2026-09-23.md`).

**The blocker is the archive layout, not the hypothesis mechanism.** The discovery-prefix rows before the straddle are **70,783,710** (`previous_complete_part` end, `part-000440` is empty). Those rows are **99.928%** of the H-DIR-01 Discovery population (50,716 rows = 0.072% omitted) and are **wholly contained in immutable, non-straddling parts** whose per-part SHA-256s are independently pinned in the manifest and whose every row-group `time_msc` max is provably `< 1764563969254` without opening any held-out bytes. A complete, independently pinned Discovery view **can** be built from those parts alone, and its `preflight_view()` can be proven on a separate runner that holds **only** that view.

H-DIR-02 therefore tests **the same mechanistic conjecture as H-DIR-01** on the **maximal verifiable prefix** — the largest Discovery view that can be authenticated without touching the mixed member. The 0.072% omission is declared **before** measurement, is not conditioned on results, and is a different population from H-DIR-01. If H-DIR-02 survives, it will be labeled `SURVIVED_DISCOVERY_ONLY` for H-DIR-02, not as a retrofit of H-DIR-01; if it rejects, H-DIR-01 remains blocked and the directional persistence mechanism is rejected on this verifiable 70.78M-row sample.

## 2. Locked source and population (H-DIR-02)

| Field | H-DIR-01 (blocked) | **H-DIR-02 (this preregistration)** |
|---|---|---|
| Source ZIP / manifest / dataset digest | Same canonical triple (above) | **Same canonical triple (immutable)** |
| Discovery definition | `time_msc < 1764563969254`, first 70,834,426 original rows | **`global_row_index < 70,783,710`**, original row order, `time_msc < 1764563969254` still enforced per row-group; equals all immutable parts with `global_row_end ≤ 70,783,710` and `rows>0` (empty `part-000440` excluded). This is the `previous_complete_part` boundary from the boundary audit. |
| Discovery rows | 70,834,426 | **70,783,710** (50,716 fewer, 99.928% overlap) |
| Source rows | 139,930,971 | 139,930,971 |
| Time min | 1726746013452 | 1726746013452 |
| Cutoff | 1764563969254 (exclusive) | **1764563969254 (exclusive)** — still the held-out exclusion bound; every verifiable row-group max must be < cutoff |
| Held-out definition | global row ≥ 70,834,426 (69,096,545 rows) | global row ≥ 70,783,710 is not held-out for this experiment; the 50,716 + 69,096,545 rows at/after the verifiable end are **excluded and never opened** by this experiment |
| View to be built | None exists | `data/raw/mt5_ticks_discovery_verifiable/` — `manifest.json` (`qts.xauusd_discovery_view.v1`, `COMPLETE_DISCOVERY_ONLY`) + `parts/part-*.parquet` (only whole, non-straddling parts), plus independently pinned `docs/xauusd_directional_view_authority_H-DIR-02.json` (`qts.xauusd_discovery_view_authority.v1`) |

The 50,716 omitted rows are **not imputed, not inferred, and not used to complete a forward window** — anchors whose `[i−16, i+1+1024]` window would require a row beyond `70,783,710` are **dropped and counted** as `boundary_outcomes` (same rule as H-DIR-01, now relative to the verifiable end). This is a complete, declared population change, not a silent repair.

## 3. Frozen mechanism, horizons, and economic filter (identical to H-DIR-01)

No mechanism, threshold, horizon, cost, or statistic is changed. All values below are **copied verbatim** from `docs/xauusd_directional_next_step_2026-09-23.md` § "One bounded hypothesis — H-DIR-01":

* **Mechanism:** Sustained signed 16-quote net displacement `r_i = m_i − m_{i−16}`, `m=(bid+ask)/2`, sign `s_i=sign(r_i)` proxies directional pressure. If pressure persists in the pre-existing high-volatility state, its past sign predicts later signed move. High is `|r_i| ≥ $0.20` (40 half-cent units); low is `|r_i| ≤ $0.10` (20 units); middle and `r_i=0` ignored and counted. Cuts in integer half-cent units.
* **Horizons:** `h=256` primary, `h=1024` stability check, stride `h+18` non-overlapping (`i % (h+18)==0`, `i≥16`, `i+1+h` inside verifiable Discovery). 1024 sample may overlap 256 and is not independent evidence.
* **Economic filter (counterfactual, not a fill):** `g_{i,h}=s_i·(m_{i+1+h}−m_{i+1})`, `c_{i,h}=(q_{i+1}+q_{i+1+h})/2 + $0.02`, `y=g−c` with `q=ask−bid`. Balances both signs: `G=(mean(g|s=+1)+mean(g|s=−1))/2`, `N=(mean(y|s=+1)+mean(y|s=−1))/2`. Joint estimands `T1=N_high` (cost-stressed directional effect) and `T2=G_high−G_low` (gross interaction). **Floors:** `T1 ≥ $0.05` and `T2 ≥ $0.05` (five one-cent grid steps) — p-values cannot replace floors. Rates are diagnostics only.
* **Uncertainty/controls:** Three equal `time_msc` terciles within verifiable Discovery, ≥1,000 events per `(tercile, high/low, prior up/down)` for 256 (≥1,000 pooled per `(high/low, prior up/down)` for 1024), block-bootstrap in 1,024-anchor blocks split at tercile bounds, **9,999 draws, seed 20260923**, within-tercile resampling, centered p `(1+count(T*−T≥T))/10000`, one-sided 99% lower bound `T−p99(T*−T)` — both bounds must exceed 0. Secondary sign-shuffle within `(tercile, block, state)` cells (1,999 draws). Holm-Bonferroni across the four p-values at `α=0.01` is the multiplicity gate (same family size as H-DIR-01). No iid quote p-values.
* **Exclusions counted:** zero-sign, middle-state, boundary outcomes (now `≥70,783,710`), and tercile counts. Long raw gaps not called weekends; `volume`/`last`/`flags` not features; clock labels still blocked (`timestamp_interpretation_confirmed=false`).

## 4. Non-negotiable artifact gates (H-DIR-02 view)

1. The view manifest `view_manifest_sha256` is pinned in `docs/xauusd_directional_view_authority_H-DIR-02.json` **before** any H-DIR-02 run. No view is trusted on its self-label.
2. A separate runner that holds **only** the verifiable view (no canonical ZIP, no `part-000441` or any later part) runs `preflight_view()` with `DiscoveryIdentity(rows=70783710, cutoff=1764563969254, ...)` — validates authority triple, manifest SHA, every part SHA, every row-group `time_msc` min/max `< cutoff`, monotonic order, contiguous `first_global_row`, and final `rows==70783710`, before any `bid/ask` read. Mixed-boundary part is refused on manifest alone before footer read; cross-cutoff `ViewBoundaryViolation` aborts before `bid/ask` read.
3. Only after **all** row-groups pass may `scan_attested_view()` → `evaluate()` be invoked. `held_out_span_opened=false`, `held_out_rows_read=0`, `runner_proven_unable_to_access_held_out_in_a_real_run` must be attested by the runner's filesystem evidence.
4. Overwriting `H-DIR-01` status with H-DIR-02 results is forbidden. The two experiments have distinct report paths: H-DIR-01 stays `reports/xauusd_directional_access.json` (`NOT_RUN_ACCESS_BLOCKED`); H-DIR-02 reports to `reports/xauusd_directional_H-DIR-02_state.json` / `.md`.

## 5. Validation and execution separation

A `SURVIVED_DISCOVERY_ONLY` verdict for H-DIR-02 is **not** a strategy, not `ROBUST`, not Demo-ready. It would require a separately preregistered out-of-sample check opening the still-closed 69M-row held-out span (and later walk-forward, execution, paper/shadow, demo stages) before any execution-readiness claim. Until then `DEMO_EXECUTION=DISABLED`, `LIVE=LOCKED`, `orders_submitted=0`.

## 6. Engineering that enables this without touching held-out

Accompanying change (committed with this preregistration, not after seeing results): `scripts/build_verifiable_discovery_view.py` builds the verifiable view **only** from parts whose manifest `global_row_end ≤ 70783710` and `rows>0`, verifying each part's SHA and row-group bounds before inclusion; it **never** `ZipFile.open()`s `part-000441` or any later part. Workflow `.github/workflows/canonical-xauusd-verifiable-discovery-view.yml` runs the builder on a GitHub-hosted runner, uploads only the bounded view manifest + authority JSON, and publishes them via Contents API to `arena/01a0cdf1-trading-system`. No archive or quote bytes are rewritten; no row is repaired.

## 7. Failure preservation

Every REJECTED/INCONCLUSIVE outcome on H-DIR-02 will be preserved in `docs/xauusd_edge_discovery_map.md` and the cycle closure, and will not be rerun with loosened floors, altered horizons, or favorable-subset selection. The 15-minute Dukascopy completeness blocker and the original H-DIR-01 BLOCK remain independent, preserved failures.

