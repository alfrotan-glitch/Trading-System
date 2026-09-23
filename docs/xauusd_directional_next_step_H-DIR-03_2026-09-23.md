# XAUUSD Directional — H-DIR-03 (Spread-State Directional at Short Horizon)

**Registered:** 2026-09-23T13:10:00Z — **before** any measurement on the verifiable view
**Parent:** H-DIR-02 REJECTED (T1 −$0.30, T2 −$0.0016 on 70,783,710-row verifiable prefix); H-DIR-01 BLOCKED. This is a **distinct mechanistic family** — spread-state, not volatility-conditioned displacement.
**Status:** `PREREGISTERED, NOT TESTED`
**View:** Same maximal verifiable Discovery prefix as H-DIR-02 — `global_row < 70,783,710`, `time_msc < 1764563969254`, 70,783,710 rows, authority `docs/xauusd_directional_view_authority_H-DIR-02.json`, manifest `reports/xauusd_directional_H-DIR-02_view_manifest.json`. No held-out opened.
**Policy:** No cherry-picked horizon, no winning side, no post-hoc threshold. A `REJECTED` stays rejected; a `SURVIVED` is still `DISCOVERY_ONLY` until separate out-of-sample.

---

## 1. Why this family is next

H-DIR-02 falsified the volatility-conditioned 16-quote displacement sign at 256/1024 quotes with large negative cost-stressed effects (−$0.30, −$0.0016) and consistent tercile failure. Together with H-ST-03 (run-length fade 49.4%) and H-MS-01 (next-quote reversal 49.94%), this suggests the 16-quote displacement sign carries **no directional information at 256 quotes**, even when conditioned on magnitude.

What remains untested with high prior is **microstructure state as a directional signal at short horizon**. Spread dynamics are the most direct observable of liquidity pressure: a `tighten` (bid ↑, ask ↓) narrows the spread by moving both sides inward — plausible buying pressure lifting the bid while ask eases — whereas a `widen` (bid ↓, ask ↑) is the opposite. One-sided updates (`bid_up_ask_same`, `bid_down_ask_same`) are weaker. The descriptive level-1 facts show `tighten` 1,185,363 and `widen` 1,117,020 occurrences in Discovery (≈1.6% each), with `bid_up_ask_same` 3,240,075 and `bid_down_ask_same` 3,146,866. These are **pre-existing, non-searched partitions** defined in `xauusd_microstructure_preregistration.md` (tight ≤20c, wide ≥27c, tighten/widen as above), not a post-hoc taxonomy.

If spread-state predicts direction, it should do so **quickly** (before the next quote update erases the signal) and **survive the same cost filter** as H-DIR-01/02 (mid-to-mid gross minus entry/exit spread/2 + $0.02, one-quote delayed). A short horizon (16 and 64 quotes) is mechanistically appropriate: microstructure signals decay in a few quotes, not 256.

This family is therefore preregistered **before** any directional measurement on this view at these horizons.

## 2. Locked source and sampling (same verifiable view as H-DIR-02)

* **Source triple:** `dataset-xauusd-730d-20260919` / `XAUUSD_730d_20260919T114013Z.zip` / SHA `975b68637be359...` / manifest `d9a61ad5830...` / dataset digest `26aee827802...` — same as H-DIR-02.
* **Discovery:** `global_row_index < 70,783,710` in original ledger order, every row-group `time_msc` max `< 1764563969254`. Verifiable view `data/raw/mt5_ticks_discovery_verifiable/` (via `build_verifiable_discovery_view.py`, never opens `part-000441` or later). `70783710` rows, `time_msc_min` 1726746013452, `source_rows` 139930971. Authority pinned before run.
* **Held-out:** Not opened for hypothesis, feature, threshold, or horizon choice. Same separate-runner `preflight_view()` gates as H-DIR-02.
* **Row carry:** Same `CARRY = h+2` logic as `DirectionalScan` but with `LOOKBACK=1` (state is the current quote's transition, not a 16-quote displacement). Anchors are `i % (h+2) == 0` with `i ≥ 1` and `i+1+h` inside verifiable Discovery. Within-horizon non-overlapping.

## 3. Locked definitions (no search)

* **Mid** `m_i=(bid_i+ask_i)/2`, **spread** `q_i=ask_i−bid_i` (cents, integer).
* **States** (from the nine-state partition, pre-existing):
  * `tighten` = `bid_up && ask_down` (spread narrows)
  * `widen` = `bid_down && ask_up` (spread widens)
  * `bid_up_same` = `bid_up && ask_same`
  * `bid_down_same` = `bid_down && ask_same`
  * Other states (`both_up`, `both_down`, `both_same`, `ask_up_same`, `ask_down_same`, `unchanged`) are **not** in this family — they are neither tighten nor widen and are ignored and counted separately.

Spread levels (tight ≤20c, wide ≥27c) are descriptive only and **not** combined with tighten/widen in this family — that would be a cross-feature interaction not preregistered here.

## 4. Hypotheses (Holm family of two, both must be considered; no cherry-picked winner)

All tests are **one-sided** in the predicted direction, at **h=16 primary** and **h=64 stability** (64 must agree in sign to avoid a horizon-specific artifact; 64 is not a second discovery). Both horizons use the same state definition and the same cost filter.

| ID | Prediction | Population | Floor (binding) | Directional cost filter |
|---|---|---|---|---|
| **H-DIR-03a** | `tighten` predicts **up**: `P(up \| tighten) > P(up \| widen)` at `h=16` (and `h=64`) | Verifiable Discovery anchors where current quote is `tighten` vs `widen` | Rate lift **≥0.02** (2 pp) at `h=16` and also `>0` at `h=64`; sign-balanced net residual `N_tighten = mean(y \| tighten)` and `N_widen = mean(−y \| widen)` (i.e., fading the widen) each **> $0.00** after `y = s·(m_{i+1+h}−m_{i+1}) − [(q_{i+1}+q_{i+1+h})/2 + $0.02]` where `s=+1` for tighten, `s=−1` for widen (so both are measured in their predicted direction) | `y` as above, one-quote delayed entry, spread+2c |
| **H-DIR-03b** | `bid_up_same` predicts **up** vs `bid_down_same` predicts **down** at `h=16` (and `h=64`) — one-sided updates | Same but states `bid_up_same` vs `bid_down_same` | Same floors: lift ≥0.02 at 16 and >0 at 64; both `N` >0 after same cost | Same |

**Why two:** `tighten/widen` is the strongest spread-state contrast (both sides move); `bid_up_same/bid_down_same` is the one-sided contrast. Testing both covers the two pre-existing directional spread partitions without searching among the other seven states.

**No other state, horizon, or cost will be considered for this family after seeing results.**

## 5. Uncertainty, controls, and gates

* **Terciles:** Three equal `time_msc` terciles within verifiable Discovery, before measurement. Require **≥1,000 events** in each `(tercile, tighten/widen)` or `(tercile, bid_up_same/bid_down_same)` cell at `h=16` (pooled ≥1,000 at `h=64`). Otherwise `INCONCLUSIVE` for that hypothesis.
* **Blocks:** Same 1,024-anchor blocks split at tercile bounds, ≥50 blocks per tercile, otherwise `INCONCLUSIVE`.
* **Resampling:** 9,999 block-bootstrap draws (seed 20260923, within-tercile) and 1,999 sign-shuffle draws within `(tercile, block, state)` — same centered p `(1+count(T*−T≥T))/10000` and 99% lower bound `T−p99(T*−T)` as H-DIR-01/02, but applied to **each hypothesis's `T = N_state` and `lift`**. Holm-Bonferroni across the **four p-values per hypothesis** (bootstrap T, shuffle T) — actually across the family: Holm across **8 p-values** (2 hypotheses × 4) at `α=0.01`.
* **Artifact gates:** (i) Terciles must agree in **sign** of `T` and `lift` with the predicted direction; (ii) `h=64` must agree in **sign** of `T` and `lift`; (iii) both `N` >0 after cost (already in floor); (iv) gap-under-one-hour subset (events where `[i, i+1+h]` contains no gap ≥3,600,000 ms) must also have `T>0` and `lift>0` — ensures a raw-gap artifact isn't driving the result.
* **Floors are binding:** A tiny p-value without `lift≥0.02` and `T>0` is not a finding. `T` is in USD after `spread+2c`.

## 6. Validation and execution separation

`SURVIVED_DISCOVERY_ONLY` would require **all** of: per-cell/tercile counts, Holm `p<0.01` for all 8, both 99% lower bounds >0, floors, and artifact gates — for **at least one** hypothesis in the family. Even then it is **not** `ROBUST`, not a strategy, not Demo-ready. Held-out stays closed; `strategy_promoted=false`, `orders_submitted=0`, `DEMO_EXECUTION=DISABLED`.

## 7. Failure preservation

If both hypotheses `REJECTED` or `INCONCLUSIVE`, the spread-state directional mechanism is rejected on this 70.78M verifiable sample and preserved. No post-hoc subset, horizon, or state will be promoted. The next highest-value action will be diagnosed separately.

