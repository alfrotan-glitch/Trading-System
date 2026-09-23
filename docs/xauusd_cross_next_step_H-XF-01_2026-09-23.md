# XAUUSD Cross-Feature — H-XF-01 (Volatility × Spread Magnitude)

**Registered:** 2026-09-23T14:20:00Z — **before** any confirmatory measurement of this hypothesis on the verifiable view
**Status:** `PREREGISTERED, NOT TESTED`
**View:** Same maximal verifiable Discovery prefix as H-DIR-02/03, H-TEMP-01, H-ST-02WF — `global_row < 70,783,710`, `time_msc < 1764563969254`, 70,783,710 rows, authority `docs/xauusd_directional_view_authority_H-DIR-02.json`, manifest `reports/xauusd_directional_H-DIR-02_view_manifest.json`. No held-out opened. Descriptive temporal and walk-forward are not used to set thresholds.
**Policy:** Thresholds are *locked* from `docs/xauusd_state_preregistration.md` (occupancy distribution, not refit), not data-derived. A `REJECTED` stays rejected.

---

## 1. Why this hypothesis is next

H-DIR-02/H-DIR-03 (directional 16→256, spread-state 16/64) and H-TEMP-01 (raw-hour magnitude) were all strongly rejected (lifts −0.016 to 0.036, nets −$0.30, ratio 0.77). H-ST-02 magnitude clustering (high vs low trailing-16 absolute) was TESTED on full Discovery (ratio 1.48, lift 7.5pp) but **failed walk-forward H-ST-02WF**: 5-fold ratios 1.19/1.23/1.25/1.16/1.36, lifts all **<0.05** (0.029–0.049), no fold cleared floors despite sign-positive and CV 0.055. Thus magnitude alone is not temporally robust to cost+2c.

Remaining untested family explicitly listed as `NOT TESTED` in ledger: **Cross-feature conditionals — Interactions other than wide×activity, recent volatility, and persistence leave/stay**. The highest-information such interaction is volatility × spread state: does a wide spread *amplify* high-volatility clustering, or does a tight spread *absorb* it? This is mechanistically distinct from:
- H-ST-01 (wide×activity vs wide×quiet, rejected 1.20)
- H-ST-02 (high vs low volatility alone)
- H-SPR-01 / H-ST-04 (widen vs tighten, leave vs stay)
and has strong prior: wide spreads occur in stressed, illiquid regimes which plausibly precede larger continuations than the same high-volatility regime with tight spreads.

## 2. Locked definitions (a priori, from locked state preregistration)

* **Trailing magnitude** `trail16 = |m_i − m_{i−16}|` dollars, where `m=(bid+ask)/2`. High = **≥0.20** dollars, Low = **≤0.10** dollars (middle unused) — exact thresholds from `xauusd_state_preregistration.md`'s “about 0.21” scale. Computed from censored integer halves to avoid float drift.
* **Spread state** `q = ask−bid` dollars at anchor `i`. **Tight** = `q ≤ 0.20`, **Wide** = `q ≥ 0.27` (typical 0.21–0.26 ignored, from occupancy distribution). Thresholds are locked, not refit on this view.
* **Cross state** `A = High ∧ Wide` vs `B = High ∧ Tight`. Anchors that are High but typical spread, or not High, are ignored (counted as exclusions, not repaired).
* **Horizons:** 256 primary, 1024 stability (1024 must agree in sign and >1.0 ratio if both groups ≥1,000; underpowered is INCONCLUSIVE not failure, per state prereg). 1-quote delay window `i+1 … i+1+256` is also a descriptive gate (must keep sign).

## 3. Hypothesis (single confirmatory family, Holm across two tests)

| ID | Prediction | Population | Horizon | Floors (binding) |
|---|---|---|---|---|
| **H-XF-01** | High-volatility with wide spread has larger absolute 256-quote mid move than high-volatility with tight spread, and the difference survives spread+2c cost | Verifiable Discovery anchors where `A` vs `B` (current quote's state) | 256 primary, 1024 stability | **Ratio ≥1.25** and **dollar gap ≥$0.10** and **exceed-spread+2c lift ≥0.05** at 256; same sign and >1.0 ratio at 1024 |

**Measured:** For each anchor `i` (global row, `i % 257 == 0` with `i ≥ 16`, `i+256` inside view), define `abs256 = |m_{i+256} − m_i|`, `cost = (q_i + q_{i+256})/2 + $0.02`, `exceed = (abs256 > cost)`. Compare `mean(abs256)` and `P(exceed)` between `A` and `B`.

**Sampling:** Non-overlapping within horizon, exclude triples touching locked span (`time_msc ≥ cutoff` or row ≥ 70,783,710), exclude backward timestamps. No repair, no imputation.

## 4. Uncertainty, controls, and gates

* **Terciles:** Three equal `time_msc` terciles within verifiable Discovery, before measurement. Require **≥1,000 anchors** in each `(tercile, A/B)` cell at 256 (pooled ≥1,000 at 1024). Otherwise `INCONCLUSIVE`.
* **Blocks:** 1,024-anchor blocks split at tercile bounds, ≥50 blocks per tercile, otherwise `INCONCLUSIVE`.
* **Resampling:** 9,999 block-bootstrap draws (seed 20260923, within-tercile) for ratio and lift, centered p and 99% lower bound >0 required. Holm-Bonferroni across the two primary p-values (ratio and lift) at `α=0.01`.
* **Artifact gates:** (i) Terciles must agree in **sign** (A > B) for both ratio and lift; (ii) 1024 must agree in sign and ratio >1.0; (iii) gap-under-one-hour subset (no gap ≥3,600,000 ms in `[i, i+256]`) must also have `A > B`; (iv) 1-quote delay `abs256_from_i+1` must also have `A > B`.
* **Floors are binding:** p-value without ratio ≥1.25, gap ≥$0.10, and lift ≥0.05 is not a finding.

## 5. Validation and execution separation

`TESTED` here means magnitude structure conditioned on spread survived cost on Discovery, **not** a directional trade. Even if `SURVIVED`, it is **not** `ROBUST`, not a strategy, not Demo-ready. Held-out stays closed; `strategy_promoted=false`, `orders_submitted=0`.

## 6. Failure preservation

If `REJECTED` or `INCONCLUSIVE`, volatility×spread magnitude interaction is rejected on this 70.78M verifiable sample and preserved. No post-hoc spread cut will be promoted. Next path will be diagnosed separately (e.g., volatility×activity or 15m timeframe).

