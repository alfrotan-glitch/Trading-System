# H-ST-02 Walk-Forward Temporal Robustness — Preregistered Validation

**Registered:** 2026-09-23T14:00:00Z — **before** walk-forward measurement, after H-ST-02 TESTED (ratio 1.48 on full Discovery)
**Status:** `PREREGISTERED, NOT TESTED`
**Purpose:** Stage 6 of evidence ladder — does the already-TESTED magnitude clustering (high 16-quote absolute → larger 256-quote absolute) survive temporal walk-forward on the verifiable 70.78M view? This is *validation* of a surviving process structure, not a new discovery hypothesis, and not a directional trade. Even if walk-forward passes, it remains process structure (not a strategy) until execution, paper, and risk are cleared.
**View:** Same verifiable Discovery prefix `70,783,710` rows, same authority/manifest, no held-out opened. Held-out stays closed.

---

## 1. Why this validation is next

H-ST-02 (ratio 1.48, 1.25 floor) and its cost variant H-VL-01 (lift 7.5pp) are the *only* structures that survived the cost filter on XAUUSD ticks. All directional/state hypotheses (H-DIR-02, H-DIR-03 a/b, H-MS, H-QD, H-MV, H-TEMP-01) were rejected with negative lifts and/or inverted ratios. The continuous mandate requires validation of surviving structure via OOS and walk-forward before any execution-ready claim, even though magnitude is not a trade. Temporal walk-forward tests whether clustering is a stable process property or a single-period artifact.

## 2. Locked definitions (same as H-ST-02, not refit)

* **High state** = top tercile of trailing 16-quote absolute mid change (locked quantile family from H-ST-02). Low state = bottom tercile. Middle tercile ignored.
* **Horizons:** 256 primary (same as original), 64 stability optional but 256 is the decision horizon.
* **Cost:** `abs256 > (q_i + q_{i+256})/2 + 0.02` for exceed rate. Ratio uses raw dollar `mean(|m_{i+256}-m_i|)`.
* **Population:** Same verifiable view, but split by time into **5 sequential folds** (each 20% of `time_msc` span: `fold = floor( (time_msc - time_min)*5 / (cutoff - time_min) )`). Within each fold, the same H-ST-02 contrast (high vs low) is measured with the same non-overlapping anchor sampling `i % 257 == 0`.

No thresholds are refit; the high/low quantile cutoffs are recomputed *within* each fold from that fold's own trailing-16 distribution (not from full sample), to avoid leakage.

## 3. Decision rules (all must pass; otherwise REJECTED as not walk-forward-robust)

* **Fold floors:** Each fold independently: `n_high ≥ 1,000`, `n_low ≥ 1,000`, `blocks ≥ 50` per fold (blocks are 1,024-anchor blocks within fold), `ratio ≥ 1.25`, `gap ≥ $0.10`, `lift ≥ 0.05`.
* **Sign gate:** All 5 folds must have `ratio > 1.0` and `lift > 0` (same direction).
* **Stability:** Coefficient of variation of `ratio` across folds < 0.20 and max fold ratio / min fold ratio < 1.5.
* **Bootstrap (per-fold):** 9,999 within-fold block-bootstrap (seed 20260923 + fold), 99% lower bound for ratio > 1.0 and for lift > 0, Holm across 10 p-values (5 ratios + 5 lifts) α 0.01.

If any fold fails floors, sign, or bootstrap, H-ST-02 is **not walk-forward-robust** (remains TESTED but not ROBUST). If all pass, it is **ROBUST** (still not a strategy, still not Demo-ready, still needs execution and risk).

## 4. Held-out separation

This walk-forward is *within* Discovery only. The held-out 40% (≈69M rows, `time_msc ≥ 1764563969254` plus the 50,716 omitted rows) remains untouched. A surviving walk-forward would be followed by OOS confirmation on held-out (Stage 7) and only then by execution simulation. No inference from held-out is made here.

## 5. Failure preservation

If walk-forward fails, H-ST-02 remains TESTED on full Discovery but is not temporally robust; this is recorded and no post-hoc fold selection will be promoted.

