# XAUUSD Cross-Feature — H-XF-02 (Volatility × Activity Magnitude)

**Registered:** 2026-09-23T15:00:00Z — **before** any confirmatory measurement of this hypothesis on the verifiable view
**Status:** `PREREGISTERED, NOT TESTED`
**View:** Same maximal verifiable Discovery prefix — `70,783,710` rows, `time_msc < 1764563969254`, authority `docs/evidence/xauusd_directional_view_authority_H-DIR-02.json`, manifest `reports/xauusd_directional_H-DIR-02_view_manifest.json`. No held-out opened. H-XF-01 `INCONCLUSIVE` (tercile-2 tight `n=481`) and its pooled ratio 2.04 / lift 0.042 are not used to set thresholds.
**Policy:** Thresholds locked from `docs/xauusd_state_preregistration.md`, not refit. `REJECTED` stays rejected; `INCONCLUSIVE` does not become `TESTED` by weakening `MIN_N=1000` or `MIN_BLOCKS=50`.

---

## 1. Why this hypothesis is next

H-XF-01 tested the only previously `NOT TESTED` cross-feature family (volatility × spread) and returned **INCONCLUSIVE** by design gate (tercile 2 `High+Tight n_B=481` <1000) with pooled 256 ratio **2.04** (pass), gap **$0.67** (pass), but lift **0.042** (<0.05) and tercile lifts **−0.076 / +0.048 / −0.063** (sign fails). Gap/delay ratios 2.03 but 1024 lift 0.006. The sparsity (42,086 `High+Wide` vs 8,647 `High+Tight` pooled, 21,744 vs 481 in tercile 2) shows `High+Tight` is regime-dependent and rare in later high-volatility tercile, making spread-conditioned volatility unbalanced for a cost-filtered test. The ledger family remains `NOT TESTED` for other interactions; the next highest-information distinct interaction is **volatility × activity (gap)**, which is also locked (active ≤100 ms, quiet >500 ms) and, per gap histogram, has opposite occupancy (active is minority but less sparse than `High+Tight` in high-volatility regimes). This tests whether fast arrival (active) amplifies high-volatility continuation vs quiet arrival, distinct from:
- H-ST-01 `Wide×Activity` (rejected 1.20)
- H-XF-01 `High×Spread` (inconclusive, spread-conditioned)
- H-ST-02 `High vs Low` alone
- H-VOL-01 / H-SPR-01 (unconditional gap/spread)

## 2. Locked definitions (a priori)

* **Trailing magnitude** `trail16 = |m_i − m_{i−16}|` dollars, `m=(bid+ask)/2`. **High** = **≥0.20** (≥20 cents), **Low** unused, middle 0.10–0.20 ignored. From locked “about 0.21” scale.
* **Activity at anchor `i`** `gap_i = time_msc[i] − time_msc[i−1]` ms for `i≥1` (row-group ordered, `time_msc` strictly non-decreasing within view). **Active** = `0 < gap_i ≤ 100`, **Quiet** = `gap_i > 500`, **Normal** 100–500 and **0** (same ms) are neither and ignored. Thresholds from locked gap histogram (active ≤100, quiet >500).
* **Cross state** `A = High ∧ Active` vs `B = High ∧ Quiet`. Anchors where `trail16<0.20` or `gap` is Normal/0 are ignored (exclusions counted, not repaired).
* **Horizons:** 256 primary, 1024 stability (1024 sign >1.0 if both groups ≥1,000; underpowered → `INCONCLUSIVE` not failure). One-quote delay `abs256_from_i+1` and gap-under-one-hour are also sign gates.

## 3. Hypothesis (single confirmatory family, Holm across two tests)

| ID | Prediction | Population | Horizon | Floors (binding) |
|---|---|---|---|---|
| **H-XF-02** | High-volatility with active arrival has larger absolute 256-quote mid move than high-volatility with quiet arrival, and survives spread+2c cost | Verifiable Discovery anchors `A` vs `B` | 256 primary, 1024 stability | **Ratio ≥1.25** and **gap ≥$0.10** and **lift ≥0.05** at 256; same sign & >1.0 ratio at 1024 |

**Measured:** `abs256 = |m_{i+256}−m_i|`, `cost=(q_i+q_{i+256})/2+0.02`, `exceed=(abs256>cost)`. Compare `mean(abs256)` and `P(exceed)` between `A` and `B`.

**Sampling:** `i % 257 == 0`, `i ≥ max(16,1)`, `i+256` and `i−16` inside view, exclude locked span, no repair.

## 4. Uncertainty, controls, gates

* **Terciles:** 3 equal `time_msc` terciles within view, before measurement. Require **≥1,000** anchors per `(tercile, A/B)` cell at 256 (pooled ≥1,000 at 1024). Otherwise `INCONCLUSIVE`.
* **Blocks:** 1,024-anchor blocks split at tercile bounds, ≥50 per tercile, otherwise `INCONCLUSIVE`.
* **Resampling:** 9,999 block-bootstrap (seed 20260923, within-tercile) for ratio and lift, centered p, 99% lower bound >0, Holm across two primary p-values `α=0.01`.
* **Artifact gates:** (i) all 3 terciles sign `A>B` for ratio and lift; (ii) 1024 sign `A>B` ratio>1 lift>0; (iii) gap-under-one-hour subset sign `A>B`; (iv) 1-quote delay sign `A>B`.
* **Floors binding:** miss on any of ratio/gap/lift → `REJECTED` (not `TESTED`).

## 5. Validation separation

`TESTED` means magnitude interaction survived cost on Discovery, not a directional trade, not `ROBUST`, not a strategy, no held-out opened, `strategy_promoted=false`, `orders_submitted=0`.

## 6. Failure preservation

If `REJECTED` or `INCONCLUSIVE`, volatility×activity interaction is rejected/inconclusive on this 70.78M sample. No post-hoc gap cut or trail threshold will be promoted. Next path diagnosed separately (e.g., other state labels or acquisition).

