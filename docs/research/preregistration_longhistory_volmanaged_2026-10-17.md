# Preregistration — XAUUSD Monthly Volatility-Managed Champion Trend

**ID:** `LH-XAUUSD-VOLM-2026-10-17`
**Status:** frozen in `volmanaged_protocol.py` before any evaluation or
replicate result of this cycle. Discovery ≤1989 only (§3); `--stage dev`
(WF 1990–1999) is pipeline debug with its G3 component knowable
pre-final, disclosed as in all parent cycles. Runner:
`scripts/run_longhistory_volmanaged.py`. Parents: the full 2026-10-17
series through `LH-XAUUSD-WHYB-2026-10-17` (N=262).

## 1. Question

The champions' signal is settled (slow monthly trend; §plateau in
`best_edge_2026-10-17.md`). What is untested is the **sizing clock**:
size currently comes from 12-month realised volatility, so de-risking
lags volatility expansions by months (the champion's −31% evaluation
drawdown sits in the 2011–15 vol regime). Does sizing from fast
3-/6-month realised volatility (Barroso & Santa-Clara volatility
management, in window form) improve the walk-forward/evaluation
profile of the two champion signals without touching the signal?

## 2. Data, windows, costs, gates

Identical to `LH-XAUUSD-ENS-2026-10-17`: World Bank monthly gold + Fed
USD index 1973–2026, WF 1990–1999, evaluation 2000–2026 (selection
≤1999), BaseMax monthly replicate informational, TWAP execution,
`fixed_units.v2`, ASSUMED base costs + G9 financing, gates G1–G9 with
unchanged thresholds (G3 ≥6/10 WF years; G5 DSR ≥0.95 at §4 N; G6 ≥100
OOS turns). Reused windows disclosed; ceiling
`FORWARD_VALIDATION_CANDIDATE_ONLY`, claim none; no DEMO/LIVE/risk
change; `REAL_CAPITAL_EXPOSURE = 0`.

## 3. Candidates (6 + control) and discovery (≤1989, 22 configs)

Signal fixed (`veto9` / long-or-flat 9m, plus 12m members); only
`sizing_vol_n ∈ {3, 6}` varies vs the 12m base:

| Group | Candidate | Discovery sel/test Sharpe (base 12m) |
|---|---|---|
| `vm_veto` | `veto9_fv3` | **0.937 / 0.615** (0.828 / 0.588) |
| `vm_veto` | `veto9_fv6` | 0.905 / 0.565 |
| `vm_veto` | `veto12_fv3` | 0.689 / 0.520 |
| `vm_lo` | `lo9_fv3` | **0.828 / 0.613** (0.779 / 0.563) |
| `vm_lo` | `lo9_fv6` | 0.820 / 0.581 |
| `vm_lo` | `lo12_fv3` | 0.585 / 0.496 |
| control | `m_boll20_2` | — |

Also evaluated and **rejected on discovery**: trailing-24m-peak
drawdown brakes (thresholds 0.80/0.85/0.90 × half/flat) on both signals
— every variant lowered selection Sharpe (braking exits gold's
recoveries). Counted in §4.

## 4. Trial count

`DISCOVERY_TRIALS = 23` (22 + control); inherited N=262;
**`N_TRIALS = 285`.**
