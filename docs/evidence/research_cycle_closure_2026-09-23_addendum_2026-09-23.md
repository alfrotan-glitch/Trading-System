# Research Cycle Closure Addendum — Continuous Loop 2026-09-23 (Post-Verifiable-View Campaign)

**Branch:** `arena/01a0cdf1-trading-system` → commits `37b1ff7` (closure) … `cfd0b1c` (this addendum)
**Disposition:** **NO VALIDATED EDGE — CONFIRMED** — all distinct directional and cross-feature mechanisms rejected/inconclusive on maximal verifiable prefix; walk-forward fails; hard external limit (MT5 reacquisition) remains the only certification path for H-DIR-01
**Capital posture:** `NO_TRADE` · `DEMO_EXECUTION=DISABLED` · `LIVE=LOCKED` · `confirm_live=false` · `orders_submitted=0`
**Held-out integrity:** 69,096,545 rows (40% of raw `time_msc` span) **still never opened** by any confirmatory test (all runners report `held_out_rows_read=0`, `held_out_span_opened=false`); H-DIR-01 remains `NOT_RUN_ACCESS_BLOCKED` per `37b1ff7` and is not retrofitted

This addendum is the reproducible record of the continuous autonomous loop that executed after `37b1ff7` without waiting for operator input, under the 2026-09-23 directive *NEVER stop at REJECTED/INCONCLUSIVE/BLOCKED*. Every number below is traceable to a committed `reports/*.json`, a GitHub Actions run, or a pinned manifest. Negative results are preserved.

---

## 1. Infrastructure certified before any new hypothesis

The closure's §5.1 requirement (“separately manifested, separately digested Discovery view”) was satisfied *without moving held-out* by the **maximal verifiable prefix**:

* **View:** `global_row < 70,783,710`, `time_msc < 1764563969254`, **70,783,710 rows** = 99.928% of Discovery (70,834,426), omitting only the 50,716 Discovery rows that share `part-000441` with 81,989 held-out rows (`reports/canonical_zip_inventory.json`). This is the largest prefix whose every row-group `time_msc max < cutoff` is provably inside Discovery via manifest-only check.
* **Authority:** `docs/xauusd_directional_view_authority_H-DIR-02.json` (`zip_sha256=975b686...`, `dataset_sha256=26aee827...`, `view_manifest_sha256=0b163b30...`), pinned before any runner mount.
* **Manifest:** `reports/xauusd_directional_H-DIR-02_view_manifest.json` (440 → 377 parts after rebuild, `COMPLETE_DISCOVERY_ONLY`).
* **Builder:** `scripts/build_verifiable_discovery_view.py` (member lookup `members[parts/name]`, per-part SHA, footer `time_msc` check, verbose log; failure `35860671048` → fix `8ecdb03` → success `35860835154`).
* **Enforcement:** `src/qts/research/xauusd_directional_view.py` `preflight_view()` validates every row-group `time_msc` min/max against `cutoff` **before** any `bid/ask` read; `scripts/run_xauusd_*_verifiable.py` reporters all emit `held_out_rows_read=0`.
* **Actions:** `35860835154` (H-DIR-02), `35861163668` (H-DIR-03), `35861777557` (temporal descriptive), `35862027176` (H-TEMP-01), `35862228204` (H-ST-02WF), `35862702846` (H-XF-01), `35862918711` (H-XF-02) — all `success`, 360m timeout, `gh release download dataset-xauusd-730d-20260919`.

This view is *not* a rewrite of `XAUUSD_730d_20260919T114013Z.zip`; the canonical ZIP is never modified. H-DIR-01's preregistered population (70,834,426) stays `BLOCKED` and unchanged.

## 2. Hypotheses preregistered **before** measurement on that view

All below were committed as `docs/xauusd_*_next_step_*.md` with `Registered: ...Z` timestamps **before** their Actions run, with locked thresholds, horizons, cost (`(q_i+q_{i+h})/2+0.02`), one-quote delay, Holm, block-bootstrap `9,999 seed 20260923`, `BLOCK_ANCHORS=1024`, `MIN_N=1000`, `MIN_BLOCKS=50`, tercile/count gates. No held-out opened.

| ID | Preregistration | Question |
|---|---|---|
| **H-DIR-02** | `xauusd_directional_next_step_H-DIR-02_2026-09-23.md` | Same 16→256 volatility-conditioned directional as H-DIR-01, on verifiable 70.78M prefix |
| **H-DIR-03a/b** | `xauusd_directional_next_step_H-DIR-03_2026-09-23.md` | Spread-state directional at 16/64 (tighten vs widen, bid_up_same vs bid_down_same) |
| **H-TEMP-01** | `xauusd_temporal_next_step_H-TEMP-01_2026-09-23.md` | Raw-hour magnitude `A={15,16,17}` vs `Q={0,1,23}` at 16/64, a priori session (no UTC claim) |
| **H-ST-02WF** | `xauusd_magnitude_walkforward_H-ST-02WF_2026-09-23.md` | Walk-forward 5-fold of H-ST-02 (256) with per-fold quantiles |
| **H-XF-01** | `xauusd_cross_next_step_H-XF-01_2026-09-23.md` | Volatility×Spread `High+Wide (≥0.27)` vs `High+Tight (≤0.20)` at 256/1024 (locked thresholds) |
| **H-XF-02** | `xauusd_cross_next_step_H-XF-02_2026-09-23.md` | Volatility×Activity `High+Active (≤100ms)` vs `High+Quiet (>500ms)` at 256/1024 |

Descriptive `reports/xauusd_temporal_discovery_state.json` (raw `time_msc%86400000//3600000` ticks 77k at rh0 vs 5.75M at rh16, spread 0.393 at 0 vs 0.242 at 18, `abs16` 0.476 at 0 vs 0.169 at 22) was **not** a hypothesis test and was not used to set preregistered thresholds (thresholds were a priori session / locked occupancy).

## 3. Measured results (all `held_out_rows_read=0`, `orders=0`)

| ID | State file / Actions | n / blocks | Effect (primary horizon) | Floors (binding) | Other gates | Verdict |
|---|---|---|---|---|---|---|
| **H-DIR-02** | `reports/xauusd_directional_H-DIR-02_state.json` `35772e1` `35860835154` | High `n` ~10k | **T1 −$0.300** (<$0.05), **T2 −$0.0016** (<$0.05), 1024 T1 −0.317, terciles −0.275/−0.302/−0.309 | T1/T2 fail | Holm false, bootstrap LB ≤0, gap false | **REJECTED** |
| **H-DIR-03a** | `reports/xauusd_spread_directional_state.json` `27b5ef2` `35861163668` 16q `65,881` vs `61,815` | both >50 blocks | **lift −0.016** (<0.02), **pooled −$0.305** (≤0) | fail | tercile/stability/gap false | **REJECTED** |
| **H-DIR-03b** | same, 16q `180,294` vs `174,639` | | **lift −0.0076** (<0.02), **pooled −$0.295** | fail | same | **REJECTED** |
| **H-TEMP-01** | `reports/xauusd_temporal_state.json` `7eb3405` `35862027176` 16q Active `952,933` mean $0.232 vs Quiet `127,521` mean $0.302 | 1361/1285/1423 blocks | **ratio 0.77** (<1.25), **gap −$0.07** (<$0.10), **lift 0.036** (<0.05) **inverted** (quiet>active); 64q 0.75 | fail | — | **REJECTED** |
| **H-ST-02WF** | `reports/xauusd_walkforward_state.json` `f816a48` `35862228204` 5-fold | folds 52–67k, blocks 51/59/52/45/66 | Fold ratios **1.19/1.23/1.25/1.16/1.36**, lifts **0.046/0.049/0.032/0.029/0.046** — all **lifts <0.05**, 3 ratios <1.25, fold3 blocks 45<50 | all folds fail floor | all sign-positive, CV 0.055 stable but floors dominate | **REJECTED** (not robust) |
| **H-XF-01** | `reports/xauusd_cross_state.json` `ed4f6f4` `35862702846` 256q High+Wide `42,086` $1.32 vs High+Tight `8,647` $0.645 | 90/86/95 blocks | **pooled ratio 2.04** (pass), **gap $0.67** (pass), **lift 0.042** (<0.05); 1024 2.02 lift 0.006; tercile lifts **−0.076/+0.048/−0.063** | lift fail, tercile sign fail | tercile2 `n_B=481` <1000 | **INCONCLUSIVE** (insufficient `n` + sign) |
| **H-XF-02** | `reports/xauusd_cross_activity_state.json` `bb7bcc0` `35862918711` 256q High+Active `26,075` $1.13 vs High+Quiet `14,870` $0.983 | 90/86/95 blocks | **ratio 1.15** (<1.25), **gap $0.15** (pass), **lift 0.025** (<0.05); 1024 1.09 lift 0.013; terciles 1.09/1.11/1.20 lifts 0.045/0.024/0.023 | ratio/lift fail | sign-positive but below floors | **REJECTED** |

**Interpretation:** Every distinct directional family (volatility-conditioned, spread-state) is strongly negative after spread+2c and one-quote delay (−0.3 net, −1.6¢ lifts). Raw-hour magnitude is inverted. Walk-forward shows H-ST-02's full-sample ratio 1.48 (lift 7.5pp TESTED) is not temporally robust to cost+2c (all 5 folds <0.05 lift). Cross-feature interactions either lack samples in the required regime (High+Tight is 481 in tercile 2 because high volatility almost never coincides with tight spread there) or have mean ratios that survive but exceed-probability lifts that do not, and tercile lifts flip sign. No family clears its binding floors and sign gates.

## 4. What this addendum proves beyond `37b1ff7`

`37b1ff7` closed the 730d tick campaign as `NO VALIDATED EDGE` with H-DIR-01 `BLOCKED` and magnitude clustering `TESTED` but not robust, and ranked “re-acquire partition-aligned Discovery view on Windows” as the only highest-value path. The continuous loop **certified that view** (70.78M) and **exhausted the next 6 distinct falsifiable mechanisms** on it without touching held-out:

* 2 directional (H-DIR-02, H-DIR-03a/b) → rejected with large negative lifts, confirming H-QD-02 / H-ST-03 rejections are not horizon-specific.
* 1 temporal magnitude (H-TEMP-01) → inverted, falsifying a priori session magnitude.
* 1 walk-forward (H-ST-02WF) → proves the sole surviving magnitude structure is not robust to time with cost+2c, even though sign is stable.
* 2 cross-feature interactions (H-XF-01/02) → one structurally sparse (INCONCLUSIVE by `MIN_N`/`MIN_BLOCKS`), one economically below floor despite sign-positive.

Diminishing returns are now measured, not asserted: pooled ratios 2.04 / 1.15 with lifts 0.042 / 0.025 show that even the strongest mean differences do not translate into cost-surviving exceed lifts that survive tercile/block/Holm/delay.

## 5. Disposition — hard external limit confirmed

* **No validated edge exists on any available verifiable tick evidence.** All available tick-level Discovery data (the 70.78M maximal verifiable prefix, 99.928% of Discovery) has been tested with preregistered, cost-stressed, delay-robust, block-bootstrapped families covering volatility-conditioned direction, spread-state direction, raw-hour magnitude, walk-forward magnitude, and two locked cross-feature interactions. None is `TESTED`/`ROBUST` in the directional sense; the only magnitudes that are `TESTED` are not robust and not a trade. Held-out remains closed.
* **H-DIR-01 stays `NOT_RUN_ACCESS_BLOCKED` and unchanged** per `xauusd_directional_next_step_2026-09-23.md` and `xauusd_directional_boundary_audit_2026-09-23.md`. This addendum does not retrofit it to 70,783,710 rows; `37b1ff7`'s hard constraint at `1764563969254` and `70,834,426` rows is preserved. Any future certification of H-DIR-01 still requires the Windows-terminal reacquisition described in `37b1ff7 §5.1` and `preregistration_reacquisition_730d_discovery_2026-09-23.md` (chunk-boundary-aligned, per-part SHA, `view_manifest_sha256` pinned in `xauusd_discovery_view_authority.json`, plus clock-basis probe). That reacquisition is **still blocked in this Linux sandbox** (`data/evidence/mt5_history_acquisition.json` `MT5_PACKAGE_UNAVAILABLE`), and no new Dukascopy bar acquisition was attempted because its completeness is `FAIL` (6.42% missing, R5 `FAIL`) and would not supply measured spread.
* **No strategy promoted, no Demo execution enabled.** Every `reports/xauusd_*_state.json` in this addendum reports `strategy_promoted=false`, `held_out_span_opened=false`, `safety.DEMO_EXECUTION=DISABLED`, `orders_submitted=0`. The `DEMO_EXECUTION=DISABLED` / `LIVE=LOCKED` gates were never bypassed, floors were never weakened (`MIN_RATIO 1.25`, `MIN_GAP $0.10`, `MIN_LIFT 0.05`, `MIN_N 1000`, `MIN_BLOCKS 50`, `α 0.01`, `N_BOOT 9999 seed 20260923`).

**Next autonomous action is blocked by the same hard external constraint identified in `37b1ff7 §5.1`.** No further distinct discovery hypothesis on the same 60% Discovery sample is the highest-value step; the expected information gain of another slice is below the cost of the DSR penalty and the provenance risk. The mission therefore remains `NO VALIDATED EDGE` for the tick archive, with full reproducibility: every `REJECTED`/`INCONCLUSIVE`/`NOT_RUN` in `docs/xauusd_edge_discovery_map.md` is preserved and traceable.

---

*Evidence and code that enforce the above:* `src/qts/research/xauusd_directional_view.py`, `src/qts/research/xauusd_directional.py`, `src/qts/research/xauusd_spread_directional.py`, `src/qts/research/xauusd_temporal*.py`, `src/qts/research/xauusd_walkforward.py`, `src/qts/research/xauusd_cross*.py`, `scripts/build_verifiable_discovery_view.py`, `scripts/run_xauusd_*_verifiable.py`, `.github/workflows/canonical-xauusd-*`, and the `reports/xauusd_*_state.json` / `docs/xauusd_*_next_step_*.md` artifacts cited.

