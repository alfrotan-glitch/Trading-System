# Preregistration — XAUUSD Weekly Slow Hybrid Trend (USD-Conditioned)

**ID:** `LH-XAUUSD-WHYB-2026-10-17`
**Status:** frozen in `weekly_hybrid_protocol.py` before any holdout or
replicate result of this cycle. Discovery on 2004–2009 only (§3);
`--stage dev` (WF 2010–2019) is pipeline debug — its G3 component is
knowable pre-final, disclosed as in parent cycles. Runner:
`scripts/run_longhistory_weekly_hybrid.py`. Parents: the full
long-history series through `LH-XAUUSD-HYB-2026-10-17`.

## 1. Question

The monthly champion family (slow long-or-flat; slow trend with
USD-confirmed shorts) is sample-starved at monthly frequency (G6) and
eligibility-starved in walk-forward (≥20-turn rule). Does the same
mechanism at **weekly** frequency — ensemble horizons 26/39/52 weeks
(≈6/9/12 months), shorts vetoed unless the 52-week USD index rose,
plus the long-or-flat form — retain the edge with more decisions?

## 2. Data, windows, costs, gates

BaseMax complete-day daily → W-FRI weekly OHLC (1,078 weeks), joined to
a weekly USD index built in the runner from the pinned Fed H.10 daily
FX file (`datasets/exchange-rates@c023dd8`): equal-weight geometric
basket of 8 currencies (monthly cycle's basket/convention), daily
values require ≥6/8 quotes (last-valid carried), weekly = last daily
observation of the W-FRI week. Causal: a week's index uses only FX
published within that week. WF 2010–2019, holdout 2020-01 → 2025-02
(selection through 2019), Dukascopy weekly replicate 2025-08 → 2026-09
informational (history-prefixed). Costs ASSUMED inherited; gates
G1–G8 as in `LH-XAUUSD-W1-2026-10-17` (G3 ≥6/10 WF years, G5 DSR ≥0.95
at §4 N, G6 ≥100 OOS turns, G8 break-even ≥2x). Selection ≥20 training
turns. Reused holdout calendar + ASSUMED costs disclosed; verdict
ceiling `FORWARD_VALIDATION_CANDIDATE_ONLY`, claim none. No DEMO/LIVE/
risk change; `REAL_CAPITAL_EXPOSURE = 0`.

## 3. Candidates (6 + control) and discovery (2004–2009, 24 configs)

Veto/agreement/long-only/long-short forms over lookback sets
{(39),(52),(26,52),(13,26,52),(26,39,52),(39,52)} (usd_lb 52w).
Agreement forms were uniformly weak (Sharpe 0.35–0.52) and are counted
but not registered. Frozen: `wh_veto` = `wv_263952` (0.923),
`wv_132652` (0.917), `wv_2652` (0.899); `wh_lo` = `wl_263952` (1.123),
`wl_132652` (1.096), `wl_2652` (1.073) (discovery Sharpe; the 2004–2009
bull inflates long-biased forms — WF/holdout decide). Control
`w_boll20_2`.

## 4. Trial count

`DISCOVERY_TRIALS = 25` (24 + control); inherited `N = 237`;
**`N_TRIALS = 262`.**
