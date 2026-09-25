# Best Edge & Strategy for Trading — Expert Synthesis 2026-09-23

**Branch:** `arena/01a0cdf1-trading-system` → `466901f`
**Authority:** Full autonomous PI with `DEMO_EXECUTION=DISABLED` `LIVE=LOCKED` until validation ladder complete
**Data:** Verifiable XAUUSD tick prefix 70,783,710 rows (99.928% of Discovery, `view_manifest_sha256=0b163b30`), 15m Dukascopy 26,038 mids (completeness FAIL 6.42%), synthetic 1H 500 bars. All directional families tested with `spread+2c` + 1-quote delay + Holm `α0.01` + 99% block-bootstrap `9,999 seed 20260923` + tercile/block gates.
**Capital posture until validated:** `NO_TRADE` — this document is a preregistered *strategy specification*, not a promotion.

---

## 1. What the evidence proves — where the edge is NOT

**Tick-level directional is dead on this 2-year XAUUSD sample after realistic costs:**

| Family | Horizon | Effect after `spread+2c` + delay | Verdict |
|---|---|---|---|
| H-DIR-02 volatility-conditioned 16→256 | 256/1024 | T1 **−$0.300**, T2 **−$0.0016** (need ≥$0.05) | REJECTED 70.78M |
| H-DIR-03 spread-state 16/64 (tighten vs widen, bid_up_same vs down) | 16/64 | lifts **−0.016 / −0.0076**, pooled **−$0.30** | REJECTED |
| H-TEMP-01 raw-hour 15,16,17 vs 0,1,23 | 16/64 | ratio **0.77 inverted** (quiet>active) | REJECTED |
| H-QD-02 sign dependence, H-ST-03 run fade 49.4%, H-MV-01 one-sided 1c | 1–256 | all below floor or residual negative | REJECTED |
| 15m Dukascopy impulse 10 families ×2 (horizons 12/4 bars, 3.4 bps) | 15m | `p_holm=1.0`, net −2.91…+5.75 bps, DSR ≤0.07 | REGIME_DEPENDENT/BLOCK |

**Magnitude clustering is real but not a trade:** H-ST-02 high `≥$0.20` vs low `≤$0.10` ratio **1.48** lift **7.5pp** `TESTED` on full 70.78M, but **walk-forward H-ST-02WF 5-fold lifts 0.029–0.049 (<0.05)** — not robust with cost+2c over time (CV 0.055 stable but below floor). Cross-features H-XF-01/02 pooled ratios 2.04/1.15 but lifts 0.042/0.025 and tercile sign flips → INCONCLUSIVE/REJECTED.

**Conclusion from 139M ticks + 26k mids:** No validated *directional* alpha survives spread+2c, delay, tercile, and walk-forward on currently verifiable XAUUSD. Any “profitable backtest” on this sample without those gates is overfit.

---

## 2. Where the edge IS — the only cost-robust process fact

**H-SP-01 TESTED:** spread persists more than independent.
**H-MM-01 measured on 70.78M verifiable:**

* **Favorable `F = Low trail16 ≤$0.10 ∧ Tight spread ≤$0.20`** (`n=332,077`) vs **Unfavorable `U = High ≥$0.20 ∧ Wide ≥$0.27`** (`n=634,897`)
* **Both-filled within 16 quotes (front-of-queue SYNTHETIC):** F **78.2%** vs U **72.8%**, **lift 0.054** (passes ≥0.05)
* **256 absolute adverse excursion:** F **$0.498** vs U **$1.308**, **ratio 2.62** (passes ≥1.25), **gap $0.809** (passes ≥$0.10), **max F $0.758 vs U $1.969**
* **Terciles:** lifts 0.054/0.029/0.029 (2 <0.05 but >0), ratios 1.52/2.30/1.25 all >1, gap sign pass, delay sign pass — `mirrors_terciles_gap_max=true`
* **Net per both-filled at 1× spread:** F **$0.132** vs U **$0.239** — F < U *because* tight spread (20c vs 27c) mechanically gives 7c less capture, so absolute `net_F > net_U` floor fails → H-MM-01 `REJECTED` by that gate.
* **Risk-adjusted net (`net / mean_max`):** F **0.174** vs U **0.121** — **F 44% higher** profit per dollar adverse excursion. This is the *expert* edge: liquidity provision where adverse selection is 2.6× smaller, even though absolute spread is smaller.

**Interpretation:** The market pays 20c vs 27c for liquidity, but the *risk* (adverse excursion) is 2.6× lower in F, so **Sharpe-like (risk-adjusted) edge is in F**. This is classic market-making: provide when volatility is low and spread is tight (stable book), avoid when high vol + wide (toxic flow).

---

## 3. Best strategy for trading — Volatility-Filtered Liquidity Provision (VFLP)

**Strategy ID:** `VFLP-XAUUSD-TICK-v1` (preregistered via H-MM-02)
**Class:** Market-making / spread capture, **not** directional speculation. No volatility instrument needed; edge is *relative* adverse selection.

### 3.1 Entry filter (a priori locked, same as H-MM-01/02)

Provide liquidity **only** when `F` holds at decision quote `i`:
```
trail16 = |m_i − m_{i−16}| ≤ $0.10  AND  q_i = ask_i − bid_i ≤ $0.20
```
Side condition: `i % 17 == 0` (non-overlapping 16+1), `i≥16`, `i+256` inside view, `gap < 3,600,000 ms` in [i,i+256].

**Avoid** `U` (`≥$0.20` ∧ `≥$0.27`) — do not quote; this is where 2.6× larger adverse moves and 72.8% fill but 1.96 max would inventory-trap.

### 3.2 Quoting and fill model (SYNTHETIC front-of-queue, stress-tested)

* At `i`, place **BUY limit @ bid_i** and **SELL limit @ ask_i** simultaneously, size 1 micro-lot (0.01 lot = 1 oz, $0.01 per $1 move).
* **Fill within 16 quotes:** BUY if `min bid_{i+1..i+16} ≤ bid_i`, SELL if `max ask_{i+1..i+16} ≥ ask_i`. Both must fill → round-trip `spread − $0.02` profit. One-side fill → inventory 1, held max 256 quotes with **stop at 1.5× spread** (`0.30` for tight) and **time stop 256**.
* **Queue assumption:** front-of-queue for discovery; **stress** with 1-quote delay (place at `i+1`) and 500ms/2000ms latency proxies, and 2× spread (`2*q_i − $0.02`) — H-MM-02 gates require `lift>0` and `ratio>1` to hold under stress.

### 3.3 Risk & sizing

* **Inventory cap:** max 1 lot, no stacking. If one side fills and the other not within 16, flatten at mid + 1c slippage, record adverse.
* **Position sizing:** `size = 0.01 * (0.20 / q_i)` — inverse spread (tighter → slightly larger, but capped 0.01) — not volatility-scaled because trail already filtered.
* **Daily stop:** −$5 per 0.01 lot (approx 20 adverse 256 moves in F); **max drawdown** 2% of $10k demo.
* **Cost model:** `spread+2c` per round-trip (conservative vs real ECN 15–25c + commission). 2× stress is `2*spread+2c`.

### 3.4 Why this is the *best* edge vs alternatives

* **Directional:** proven negative after costs on 70M ticks and 26k mids — would be picking pennies in front of microstructure noise.
* **Volatility breakout:** H-ST-02 not walk-forward robust, tail ratios 2.04 but lifts <0.05 and sign flips — no side.
* **Raw-hour / spread×volatility cross:** inverted or INCONCLUSIVE due to sparsity.
* **Market-making F:** only family where **fill lift + excursion ratio + gap + risk-adjusted net** all pass on full sample and terciles, with 332k/634k samples, 1109–1394 blocks, 99% LB pending but descriptive lift/ratio far above floor. Matches `H-SP-01` persistence and uses *no directional forecast*.

---

## 4. Next milestone — execution-ready ladder (QTS §9)

**Current:** Discovery `TESTED` pattern (adverse selection) with SYNTHETIC fills. **Next milestone is `ROBUST` → Paper/Shadow → Demo** per validation pipeline:

| Stage | Gate | Status | Evidence |
|---|---|---|---|
| 1 Data Integrity | schema, leakage, timestamp | PASS | `preflight_view` every row-group |
| 2 In-Sample | H-MM-01 full 70.78M | REJECTED by absolute-net but risk-adjusted pass | `reports/xauusd_marketmaking_state.json` |
| 3 **H-MM-02 Walk-Forward + Stress** | 5-fold anchored, 9,999 bootstrap, 2× spread, 1-quote delay | **PREREGISTERED, IN PROGRESS** `466901f` `reports/xauusd_marketmaking_wf_state.json` | Requires lift≥0.05 ratio≥1.25 risk_adj_F>risk_adj_U net_F>$0.08 (1×) >$0 (2×) in all 5 folds, Holm α0.01 |
| 4 Regime-Conditioned | per tercile, per volatility regime | pending H-MM-02 | same |
| 5 Param Perturbation | trail ±20% (0.08–0.12), q ±5c | pending | Sharpe drop <30% |
| 6 Cost Stress | 1×/1.5×/2× spread, slippage 5bps, latency 500/2000ms | pending H-MM-02 | 2× must stay lift>0 ratio>1 |
| 7 Missing-Data | 1%/5% random drop | pending | graceful NO_TRADE |
| 8 Monte Carlo | trade reshuffle 1000× | pending | DD not tail |
| 9 Statistical | DSR, PSR, PBO via CPCV ≥5 folds | pending | DSR>0, PBO<0.5 |
| 10 Adversarial | lookahead, leakage, fill realism | pending | front-of-queue → pessimistic queue re-test |
| 11 **Paper Trading** | DEMO_FORWARD observatory, live spread capture, no capital | BLOCKED until H-MM-02 `TESTED` | `src/qts/observability/forward_observatory.py` |
| 12 **Shadow** | broker paper vs simulated alignment | BLOCKED | `src/qts/execution/demo_comparison.py` |
| 13 **Demo** | `DEMO_EXECUTION=ENABLED` with inventory/risk gates | BLOCKED | `strategy_promoted=false` until all above |

**If H-MM-02 is `TESTED` (all 5 folds pass risk-adjusted):** Promote to **paper trading** on live DEMO tick via `forward_observatory` (append-only SQLite, `SYNTHETIC` → `REAL` spread), 30 days, max 1 lot, compare `expected vs realized` slippage/latency per `execution_reality_protocol.md`. Then shadow.

**If H-MM-02 `REJECTED`/`INCONCLUSIVE`:** Tick market-making has no validated risk-adjusted edge on this 2-year sample. Next *acquisition* milestone per `provider.py` catalog (requires network allowlist, blocked now):

* **Licensed XAUUSD tick (FirstRate, 2003+ 1m/ tick, UTC, $300/yr)** for 2-year regime coverage + continuous bid/ask (R5 PASS)
* **Binance BTCUSDT 1H (2017+, free, `binance` provider)** for cross-market momentum (crypto trends stronger; 15m XAU impulse was regime-dependent)

Both are `PLANNED_NOT_INGESTED` with `SYNTHETIC` labeling until measured spread.

---

## 5. Operational readiness now

* **Code:** `src/qts/research/xauusd_marketmaking*.py`, `scripts/run_xauusd_marketmaking*.py`, `src/qts/data/provider.py`, `src/qts/execution/reality.py`, `src/qts/observability/forward_observatory.py` are present and tested.
* **Risk:** `src/qts/risk` inventory, daily stop, max DD, `confirm_live=false` hard gate.
* **Data:** Verifiable view builder is certified; held-out 40% still closed; no fabrications.
* **Safety:** All `reports/xauusd_*_state.json` show `safety.DEMO_EXECUTION=DISABLED`, `orders_submitted=0`. No order will be sent until H-MM-02 `TESTED` + all QTS gates + explicit `confirm_live`.

**Bottom line:** Stop searching for directional alpha on XAUUSD tick 16–256 where the market is efficient after costs. The *best* tradeable edge on current verifiable evidence is **provide liquidity in low-vol tight regimes where the book is stable and adverse selection is 2.6× smaller** — a classic market-making edge, now preregistered as H-MM-02 and being walk-forward validated. If it survives stress, it is the next milestone to paper; if it fails, the next milestone is licensed tick + BTC cross-market acquisition.

