# XAUUSD Temporal — H-TEMP-01 (Raw-Hour Magnitude)

**Registered:** 2026-09-23T13:30:00Z — **before** any confirmatory measurement of this hypothesis on the verifiable view
**Status:** `PREREGISTERED, NOT TESTED`
**View:** Same maximal verifiable Discovery prefix as H-DIR-02/03 — `global_row < 70,783,710`, `time_msc < 1764563969254`, 70,783,710 rows, authority `docs/xauusd_directional_view_authority_H-DIR-02.json`, manifest `reports/xauusd_directional_H-DIR-02_view_manifest.json`. No held-out opened. Descriptive temporal (`reports/xauusd_temporal_discovery_state.json`) is **descriptive only** and not a hypothesis test; its raw-hour means are not used to set thresholds.
**Policy:** Thresholds are *a priori* session-based, not data-derived. A `REJECTED` stays rejected.

---

## 1. Why this hypothesis is next

H-DIR-02 (volatility-conditioned 16→256 directional) and H-DIR-03 (spread-state 16/64 directional) were both strongly rejected on the verifiable 70.78M view (lifts −0.016 to −0.0016, nets −$0.30, all gates false). Nine prior microstructure/state directional hypotheses were also rejected. The remaining untested orthogonal dimension with high prior is **temporal/intraday structure**, which was previously BLOCKED (`timestamp_interpretation_confirmed=false`). The descriptive temporal run shows strong raw intraday variation without claiming UTC: ticks 77k at raw_hour 0 vs 5.75M at 16 (74×), mean_abs_16 0.476 at raw_hour 0 vs 0.169 at 22 (2.8×), spread 0.393 at 0 vs 0.242 at 18 (1.6×). This magnitude range exceeds the 1.48 volatility ratio that defines H-ST-02.

Crucially, H-VL-01 showed that magnitude survives spread+2c cost with a 7.54pp lift. If temporal magnitude is even larger, it may also survive cost. Temporal magnitude is therefore the **highest-information distinct mechanism** not yet tested, and it can be tested **without claiming UTC** by using raw `time_msc % 86400000 // 3600000` as a provisional session label.

## 2. Locked definitions (a priori, not data-derived)

* **Raw hour** `rh = (time_msc % 86400000) // 3600000` — integer 0..23, provisional, no UTC claim. Computed from raw `time_msc` exactly as stored, no offset inference.
* **Active set** `A = {15,16,17}` — *a priori* expected high-activity session (London close / NY afternoon overlap, 15:00–17:59 raw). Justified by known FX session structure (London 08–16 UTC, NY 13–21 UTC, overlap 13–16), not by the just-measured tick counts.
* **Quiet set** `Q = {0,1,23}` — *a priori* expected low-activity (Asian early / close, 00:00–01:59 and 23:00–23:59 raw). Justified as known low-liquidity hours, not by the measured 77k vs 5.7M.
* Other hours 2–14, 18–22 are **ignored** for this hypothesis (neither active nor quiet) and counted separately.

These sets are *declared before* any confirmatory measurement. The descriptive's observation that `A` happens to contain the three highest tick counts and `Q` the three lowest is *post-hoc* and does not change the thresholds.

## 3. Hypotheses (single confirmatory family, Holm across two tests)

| ID | Prediction | Population | Horizon | Floors (binding) |
|---|---|---|---|---|
| **H-TEMP-01** | Active raw hours have larger absolute 16-quote mid move than quiet raw hours, and the difference survives spread+2c cost | Verifiable Discovery anchors where `rh ∈ A` vs `rh ∈ Q` (current quote's `rh`) | 16 primary, 64 stability (64 must agree in sign and clear floors) | **Ratio ≥1.25** and **dollar gap ≥$0.10** and **exceed-spread+2c lift ≥0.05** at 16; same sign and >1.0 ratio at 64 |

**Measured:** For each anchor `i` (global row), define `abs16 = |m_{i+16} − m_i|` where `m=(bid+ask)/2`, `spread cost` `c = (q_i + q_{i+16})/2 + $0.02` with `q=ask−bid`, and `exceed = (abs16 > c)`. Compare `mean(abs16)` and `P(exceed)` between `A` and `Q`.

**Sampling:** Anchors `i % (h+1) == 0` with `h=16` (primary) and `h=64` (stability), `i+16` and `i+64` inside verifiable Discovery, `i` and `i+16`/`i+64` must be in same raw-hour set? No — state of anchor `i` determines group; exit may be in different raw hour (allowed, counted, not repaired). Non-overlapping within horizon.

## 4. Uncertainty, controls, and gates

* **Terciles:** Three equal `time_msc` terciles within verifiable Discovery, before measurement. Require **≥1,000 anchors** in each `(tercile, A/Q)` cell at `h=16` (pooled ≥1,000 at `h=64`). Otherwise `INCONCLUSIVE`.
* **Blocks:** 1,024-anchor blocks split at tercile bounds, ≥50 blocks per tercile, otherwise `INCONCLUSIVE`.
* **Resampling:** 9,999 block-bootstrap draws (seed 20260923, within-tercile) for ratio and lift, centered p and 99% lower bound >0 required. Holm-Bonferroni across the two primary p-values (ratio and lift) at `α=0.01`. No iid p-values.
* **Artifact gates:** (i) Terciles must agree in **sign** (A > Q) for both ratio and lift; (ii) `h=64` must agree in sign and ratio >1.0; (iii) gap-under-one-hour subset (no gap ≥3,600,000 ms in `[i, i+64]`) must also have `A > Q`.
* **Floors are binding:** p-value without ratio ≥1.25, gap ≥$0.10, and lift ≥0.05 is not a finding.

## 5. Validation and execution separation

`TESTED` here means magnitude structure survived cost on Discovery, **not** a directional trade. Even if `SURVIVED`, it is **not** `ROBUST`, not a strategy, not Demo-ready. Held-out stays closed; `strategy_promoted=false`, `orders_submitted=0`.

## 6. Failure preservation

If `REJECTED` or `INCONCLUSIVE`, raw-hour magnitude is rejected on this 70.78M verifiable sample and preserved. No post-hoc hour subset will be promoted. Next path will be diagnosed separately.

