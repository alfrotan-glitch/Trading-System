# XAUUSD 1m — H-1M-01 (Donchian Breakout Momentum, 1m Bars Derived from Verifiable Tick)

**Registered:** 2026-09-23T18:00:00Z — **before** any confirmatory measurement of this 1m hypothesis on the verifiable tick view
**Status:** `PREREGISTERED, NOT TESTED`
**View:** Same maximal verifiable Discovery prefix — `70,783,710` rows, `cutoff 1764563969254`, authority `docs/evidence/xauusd_directional_view_authority_H-DIR-02.json`. 1m bars are **deterministically derived** from tick mids (`mid=(bid+ask)/2`) on UTC minute boundaries via `mid_1m = last mid in minute`, `high = max mid in minute`, `low = min mid in minute`, `close = last`. No held-out opened, no external data. 1m derivation is `SYNTHETIC_DERIVED` from `REAL` tick, labeled as such, not `REAL` 1m bars.
**Policy:** This is the first 1m timeframe test in this checkout (per `timeframe_research.md`, 1m was `UNAVAILABLE` — this makes it `DERIVED_SYNTHETIC` not `REAL`, so it cannot claim `REAL` 1m execution without `R5` measured spread). A `REJECTED` stays rejected.

---

## 1. Why this hypothesis is the next best edge with full authority

All tick-level directional (H-DIR-02/03, lifts −0.016 to −0.0016), temporal (H-TEMP-01 ratio 0.77 inverted), cross-feature (H-XF-01/02 lifts 0.042/0.025), and market-making walk-forward (H-MM-02 5-fold risk 0.06<0.095) are **rejected/inconclusive** on 70.78M ticks after `spread+2c` + delay. 15m Dukascopy impulse 10 families all `p_holm=1.0` (3.4 bps). The **only** surviving process facts are volatility clustering (1.48 ratio, not walk-forward robust) and spread persistence.

With full authority to *derive* a new timeframe from existing `REAL` tick (not to fabricate), the next highest-information distinct mechanism is **1m Donchian breakout momentum** — a classic trend mechanism not in the 15m impulse families (which were range_expansion, price_velocity, vol_expansion, range_breakout, breakout_with_expansion at 15m, not Donchian 1m). 1m aggregation **smooths tick noise** (tick → 1m reduces 74× intraday tick variation and 0.393→0.242 spread variation) and tests whether *intermediate* 20-minute vs 3-hour horizons have persistence that tick 16–256 and 15m 12-bar did not.

This is **bounded** (one family, one lookback, two horizons, pre-declared cost) and **mechanistically distinct** (multi-bar breakout vs tick microstructure).

## 2. Locked definitions (a priori)

* **1m bar:** UTC minute `t = floor(time_msc / 60000)`. For each minute with ≥1 tick in view, `open = first mid`, `high = max mid`, `low = min mid`, `close = last mid`, `volume = tick count`. Minutes with 0 ticks are **gaps** (absent, not filled). No interpolation.
* **Donchian breakout signal at bar close `i`:** `HH20 = max(high_{i−20}..high_{i−1})`, `LL20 = min(low_{i−20}..low_{i−1})`. **Long signal** if `close_i > HH20`, **Short signal** if `close_i < LL20`. No signal otherwise. Lookback `20` is a priori (common 20-bar, ≈20 minutes), not tuned.
* **Horizons:** **12 bars (12 minutes) primary**, 48 bars (48 minutes) stability. Both must agree in sign.
* **Cost:** 15m research used 3.4 bps round-turn (ESTIMATED). For 1m derived mid bars, cost is `spread proxy = 0.025%` (2.5 bps per side, 5.0 bps round-turn) + $0.02 slippage per oz, labeled `SYNTHETIC_DERIVED` (mid bars have no measured spread). More conservative than 15m 3.4 bps.
* **Population:** Verifiable Discovery 1m bars where `i ≥ 20` and `i+12`/`i+48` inside view, exclude bars touching `cutoff`, exclude gaps (if any of the 20 lookback or 12/48 forward bars is missing, exclude). No held-out.

## 3. Hypothesis (single family, Holm across 2 tests)

| ID | Prediction | Population | Horizon | Floors (binding) |
|---|---|---|---|---|
| **H-1M-01** | 1m Donchian 20-bar breakout has positive net expectancy over next 12 1m bars after `5.0 bps + $0.02` costs and 1-bar latency (enter at next bar open) | Verifiable Discovery 1m bars Long vs baseline and Short vs baseline | 12 primary, 48 stability | **Net expectancy > 0** and **profit factor > 1.0** and **win rate not < 0.45** and **DSR > 0.0** (penalized for N=1+ prior 180 trials) at 12, and **same sign** at 48 |

**Measured:** For each signal `i`, `gross_return = (close_{i+12} − close_i)/close_i` for Long, reversed for Short, `net = gross − cost` (cost 5.0 bps + $0.02/close). Baseline is **all non-signal bars** (same horizon). Compare `mean(net)` signal vs baseline, `p_holm` vs baseline via 9,999 block-bootstrap (blocks 50 bars, seed 20260923), tercile agreement.

## 4. Controls

* **Terciles:** 3 equal `time_msc` terciles within view (via bar open time), before measurement. Require `≥100` signals per side per tercile at 12, otherwise `INCONCLUSIVE`.
* **Blocks:** 50-bar blocks split at tercile bounds, ≥20 blocks per tercile.
* **Bootstrap:** 9,999 within-tercile block-bootstrap for mean net diff, Holm across 2 p-values (Long vs baseline, Short vs baseline) `α=0.01`, 99% LB >0 required.
* **Artifact gates:** (i) terciles sign `signal > baseline` for both Long and Short; (ii) 48 stability sign `signal > baseline`; (iii) gap-under-one-hour subset sign; (iv) 1-bar latency (enter at `open_{i+1}`) sign.
* **Floors binding:** net ≤0 or PF ≤1.0 or DSR ≤0 → `REJECTED`.

## 5. Validation separation

`TESTED` means 1m breakout has cost-surviving expectancy on Discovery, not `ROBUST`, not a strategy, not Demo-ready, held-out closed, `SYNTHETIC_DERIVED` source, `orders_submitted=0`.

## 6. Failure preservation

If `REJECTED`/`INCONCLUSIVE`, 1m Donchian momentum is rejected on this 70.78M-derived 1m sample. No post-hoc lookback (20) or horizon (12/48) change. Next path is 15m-derived 1H or FirstRate licensed tick per `provider.py` when network allowlisted.

