# XAUUSD Market-Making — H-MM-02 (Risk-Adjusted Spread Capture, Walk-Forward)

**Registered:** 2026-09-23T17:30:00Z — **before** any confirmatory measurement of this refined hypothesis
**Status:** `PREREGISTERED, NOT TESTED`
**View:** Same verifiable 70.78M prefix, no held-out. H-MM-01 `REJECTED` by `net_F > net_U` absolute gate despite lift 0.054 ratio 2.62 is not used to set thresholds; thresholds remain locked.
**Policy:** H-MM-01 showed F (Low+Tight) has **higher fill rate** (78.2% vs 72.8% lift 0.054 pass) and **2.62× smaller 256 excursion** (0.498 vs 1.308 gap 0.809 pass, max 0.758 vs 1.969) but **lower absolute net per fill** ($0.132 vs $0.239) because tight spread (≤0.20) vs wide (≥0.27) mechanically gives smaller capture. Risk-adjusted (net/max) F **0.174** vs U **0.121** passes. H-MM-02 corrects the economic gate to **risk-adjusted** and adds walk-forward + cost/latency stress. `SYNTHETIC` fills remain front-of-queue; `DEMO_EXECUTION` stays `DISABLED`.

---

## 1. Why this refinement is the best edge next milestone

Expert diagnosis: tick-level **directional** is dead on this sample (H-DIR lifts −0.016 to −0.0016, nets −$0.30; all 5 walk-forward lifts <0.05). The *only* surviving process facts are:
- **Volatility clustering** (H-ST-02 ratio 1.48, but walk-forward 5-fold lifts <0.05 — not robust for directional sizing)
- **Spread persistence** (H-SP-01) + **adverse selection** difference (H-MM-01: F max 0.758 vs U 1.969, ratio 2.62)

The best *tradeable* edge in XAUUSD spot without a volatility instrument is **liquidity provision**: capture spread where adverse selection is small. H-MM-01 proved F has 5.4pp higher both-filled rate and 2.6× smaller excursion, but absolute net fails because tight spread is 7c smaller than wide. The *expert* edge is **risk-adjusted** (Sharpe-like): profit per unit adverse excursion, and **time to fill** vs **time to adverse move**.

This matches the next QTS milestone per `evidence/09-validation-methodology.md` §9.6–9.8: after discovery, the ladder is **Transaction-Cost Stress (1×/1.5×/2× spread), Slippage/Latency (0/500/2000ms), Walk-Forward (5-fold anchored), Monte Carlo**. H-MM-02 is exactly that: same F vs U, but gates are risk-adjusted and include stress.

If H-MM-02 is `TESTED`, it becomes the first `ROBUST` candidate for **paper/shadow** (Stage 9) with inventory caps and then forward observation.

## 2. Locked definitions (same as H-MM-01, not refit)

* **F = Low+Tight** (`trail16≤0.10` AND `q≤0.20`) vs **U = High+Wide** (`trail16≥0.20` AND `q≥0.27`), `trail16=|m_i−m_{i−16}|`, `q=ask−bid`.
* **Fill:** both-filled within 16 quotes (front-of-queue SYNTHETIC, same as H-MM-01). **Excursion:** 256 absolute and max over 1..256. **Net per both-filled:** `q_i −0.02`.
* **Risk-adjusted net:** `net / mean_max_exc` (dollars per dollar adverse excursion) and `net / mean_exc`. F should be higher.

## 3. Hypothesis (single family, Holm across 3 tests, plus walk-forward)

| ID | Prediction | Population | Horizon | Floors (binding) — risk-adjusted |
|---|---|---|---|---|
| **H-MM-02** | F has higher both-filled rate **and** smaller excursion **and** higher risk-adjusted net than U, surviving 2× spread stress and 500ms latency proxy | Verifiable Discovery `F` vs `U` | 16 fill / 256 excursion | **Fill lift ≥0.05** and **excursion ratio ≥1.25** (U/F) and **gap ≥$0.10** and **risk-adjusted net_F > risk-adjusted net_U** and **net_F > $0.08 at 1× spread** and **net_F > $0 at 2× spread** (`q_i*2 −0.02` stress) and **delay fill lift >0** (1-quote delay) |

**Walk-forward:** 5-fold anchored (same time terciles expanded to 5 folds as H-ST-02WF). Each fold must have `n_F≥500` (relaxed from 1000 because F is rarer in later terciles: H-MM-01 tercile2 F 3,279 vs 328k U, so per-fold 500 is balanced) and `blocks≥20`, and sign `F better` for lift/ratio/net. CV of risk-adjusted net <0.50.

**Cost/latency stress:** 2× spread (`2*q_i −0.02`) and 1-quote delay fill must keep `lift>0` and `ratio>1`.

## 4. Controls

* **Terciles:** 3 equal `time_msc` terciles, before measurement. Require `≥500` per `(tercile,F/U)` for this market-making family (justified by F sparsity in tercile2: 3,279 in 70M), `blocks≥20`. Otherwise `INCONCLUSIVE` (not `REJECTED`).
* **Blocks:** 1,024-anchor blocks split at tercile bounds.
* **Bootstrap:** 9,999 block-bootstrap seed 20260923 for lift, ratio, risk-adjusted diff, Holm α0.01, 99% LB >0.
* **Artifact gates:** all terciles lift>0 ratio>1, gap-clear sign, max_exc sign, delay sign, 2× spread sign.
* **Inventory gate:** mean_max_F < mean_max_U in every tercile (already).

## 5. Validation separation

`TESTED` means simulated risk-adjusted capture survived cost/latency stress on Discovery, not `ROBUST`, not Demo-ready, held-out closed, `SYNTHETIC` source, `orders_submitted=0`.

## 6. Failure preservation

If `REJECTED`/`INCONCLUSIVE`, risk-adjusted market-making is not validated on this sample. No post-hoc `trail`/`q` change. Next path is **licensed XAUUSD tick (FirstRate) + Binance BTC 1H dual-market** acquisition per `provider.py` catalog (requires network allowlist) or forward observatory live capture.

