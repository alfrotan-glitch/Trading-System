# XAUUSD Market-Making — H-MM-01 (Spread Capture in Low-Vol Tight Regime)

**Registered:** 2026-09-23T16:00:00Z — **before** any confirmatory measurement of this hypothesis on the verifiable view
**Status:** `PREREGISTERED, NOT TESTED`
**View:** Same maximal verifiable Discovery prefix — `70,783,710` rows, `cutoff 1764563969254`, authority `docs/evidence/xauusd_directional_view_authority_H-DIR-02.json`, manifest `reports/xauusd_directional_H-DIR-02_view_manifest.json`. No held-out opened. All prior directional/magnitude/cross results are not used to set thresholds except locked state definitions.
**Policy:** Execution-aware but not a live order. Simulated fills are `SYNTHETIC` source, labeled as such, never as `REAL` execution evidence. `DEMO_EXECUTION` stays `DISABLED` until this hypothesis is `TESTED` and then `ROBUST` via walk-forward and cost/latency stress.

---

## 1. Why this hypothesis is next — best edge expertise

Tick-level **directional** families are **falsified** on the 70.78M verifiable sample with large negative economics:
- H-DIR-02 T1 **−$0.300** T2 **−$0.0016**, H-DIR-03 lifts **−0.016 / −0.0076** pooled **−$0.30**, H-TEMP-01 ratio **0.77 inverted**
- Walk-forward H-ST-02WF: all 5 folds **lift <0.05** (0.029–0.049) despite sign-positive — magnitude clustering is real but not cost-robust over time
- Cross-feature H-XF-01/02: pooled ratios 2.04/1.15 but lifts 0.042/0.025 and tercile sign flips

**Process facts that did survive** and point to the *only* remaining execution edge class:
- **H-SP-01 TESTED:** spread persists more than independent draws (quote persistence, not a return predictor)
- **H-ST-02 / H-VL-01 TESTED:** low trailing-16 absolute (`≤$0.10`) → smaller 256 absolute than high (`≥$0.20`) with ratio 1.48 and lift 7.5pp full-sample, gap $0.346; low state also has narrower spread (25.2c vs 27.6c) so *scaled* move 2.88 vs 3.89 spreads — i.e., low-vol tight regimes have *both* smaller absolute moves *and* tighter spreads
- **Gap histogram:** 74× intraday tick variation, but spread is most persistent in tight regimes

Market-making (liquidity provision) does **not** require directional prediction — it requires *spread persistence* and *small adverse selection* (future mid excursion < spread/2 before both sides fill). The locked low-vol + tight-spread regime is the a priori candidate for small adverse selection. High-vol + wide-spread is the unfavorable control (large future moves, wide spread, high adverse selection). This is **mechanistically distinct** from all rejected directional/magnitude families and is the **next milestone toward execution-ready per §9 Validation Methodology — Transaction-Cost Stress & Slippage/Latency**.

If H-MM-01 fails, the verifiable tick sample has no viable execution class without a volatility instrument; the next acquisition milestone becomes **licensed XAUUSD tick with continuous bid/ask + Binance BTCUSDT 1H for cross-market** (planned providers: `mt5_history`, `binance`).

## 2. Locked definitions (a priori, from `xauusd_state_preregistration.md`)

* **Trailing magnitude** `trail16 = |m_i − m_{i−16}|` dollars, `m=(bid+ask)/2`. **Low** = **≤0.10**, **High** = **≥0.20** (middle 0.10–0.20 ignored). Cents via `(bid_c+ask_c)` halves, same as H-ST-02.
* **Spread at anchor** `q_i = ask_i − bid_i` dollars. **Tight** = **≤0.20**, **Wide** = **≥0.27** (typical 0.21–0.26 ignored).
* **Favorable state** `F = Low ∧ Tight` (`trail16≤0.10` AND `q_i≤0.20`) — a priori small-move + stable-spread regime.
* **Unfavorable state** `U = High ∧ Wide` (`trail16≥0.20` AND `q_i≥0.27`) — large-move + stressed-spread regime.
* **Simulated market-making round-trip** at anchor `i` (global row, `i % 17 == 0` to avoid overlap with 16 horizon, `i≥16`, `i+16` and `i+256` inside view):
  - Place **BUY limit at bid_i** and **SELL limit at ask_i** simultaneously at `i`.
  - **Fill model (conservative, SYNTHETIC):** BUY fills if `min_{k=1..16} bid_{i+k} ≤ bid_i` (bid touches or crosses down); SELL fills if `max_{k=1..16} ask_{i+k} ≥ ask_i`. Both must fill within 16 quotes to count as **both-filled**. If only one side fills within 16 and the other does not, it's **adverse selection** (inventory 1). If neither fills, **no trade**.
  - **Adverse selection metric:** `excursion256 = |m_{i+256}−m_i|` and also `max adverse excursion = max_{k=1..256} |m_{i+k}−m_i|`. Favorable should have smaller 256 absolute and smaller max excursion.
  - **Net capture per both-filled round-trip:** `spread_i − 0.02` (subtract $0.02 slippage stress beyond spread; spread capture is `ask_i−bid_i`, cost is 2c). No commission beyond spread+2c in this test; 2×/3× stress is later gate.
  - Queue position assumed **front-of-queue** for this discovery test; latency stress (500ms/2000ms) is a later robustness gate, not this hypothesis. This is explicitly `SYNTHETIC` and optimistic — a `TESTED` here still requires pessimistic queue/latency re-test.

## 3. Hypothesis (single confirmatory family, Holm across 4 tests)

| ID | Prediction | Population | Horizon | Floors (binding) |
|---|---|---|---|---|
| **H-MM-01** | Favorable `F` has **higher both-filled rate** within 16 quotes **and** **smaller 256 absolute adverse excursion** than unfavorable `U`, with both differences surviving cost+2c | Verifiable Discovery anchors `F` vs `U` | 16 for fill rate, 256 for excursion | **Fill-rate lift ≥0.05** (P(both-filled|F) − P(both-filled|U) ≥0.05) **and** **excursion ratio ≥1.25** (`mean excursion_U / mean excursion_F ≥1.25`) **and** **excursion gap ≥$0.10** (U−F mean) **and** **net capture per both-filled > $0.10** (mean `q_i −0.02` for F both-filled >0.10) |

Also required: **F both-filled net capture > $0** lift vs U (F net > U net) and **F adverse max excursion < U adverse max**.

**Sampling:** `i % 17 == 0` (16+1 to avoid overlap), `i≥16`, `i+16` and `i+256` inside view, exclude locked span, exclude `gap_i≥3,600,000 ms` in `[i, i+256]` for gap-clear subset gate (must keep sign). No repair.

## 4. Uncertainty, controls, gates

* **Terciles:** 3 equal `time_msc` terciles within view, before measurement. Require **≥1,000 anchors** per `(tercile, F/U)` cell for both fill-rate (16) and excursion (256). Otherwise `INCONCLUSIVE`.
* **Blocks:** 1,024-anchor blocks split at tercile bounds, ≥50 per tercile, otherwise `INCONCLUSIVE`.
* **Resampling:** 9,999 block-bootstrap (seed 20260923, within-tercile) for **fill-rate lift**, **excursion ratio**, and **excursion gap**, centered p and 99% lower bound >0 required. Holm across 3 primary p-values (fill lift, excursion ratio, gap) `α=0.01`.
* **Artifact gates:** (i) all 3 terciles sign `F better than U` for both fill lift and excursion ratio/gap; (ii) gap-under-one-hour subset sign `F better`; (iii) 1-quote delay excursion (from `i+1`) sign `F better`; (iv) queue-stress descriptive: re-test with **1-quote delay fill** (`bid_{i+1}/ask_{i+1}` as limit) must keep sign (not a floor, but noted).
* **Floors binding:** miss on any of `lift≥0.05`, `ratio≥1.25`, `gap≥$0.10`, `net> $0.10` → `REJECTED`.

## 5. Validation and execution separation

`TESTED` here means *simulated spread-capture* structure survived cost+2c on Discovery with `SYNTHETIC` fills, **not** `ROBUST`, not a strategy, not Demo-ready. Held-out stays closed; `strategy_promoted=false`, `orders_submitted=0`, `DEMO_EXECUTION=DISABLED`. A `TESTED` would proceed to **queue/latency/2× spread stress**, **walk-forward 5-fold**, and **inventory-risk (max excursion) stress** before any paper/shadow.

## 6. Failure preservation

If `REJECTED` or `INCONCLUSIVE`, low-vol tight spread does not provide a cost-surviving spread-capture advantage on this 70.78M sample. No post-hoc `trail` or `q` cut, no `H` change, no fill-window change (16/256) will be promoted. Next path diagnosed separately — acquisition of **Binance BTCUSDT 1H** and **licensed XAUUSD tick (FirstRate/Dukascopy)** for cross-market and 2-year regime coverage per `evidence/data_requirements.md` (R1–R6), with explicit `SYNTHETIC` labeling for any mid-proxy.

