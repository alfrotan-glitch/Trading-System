# Preregistration — XAUUSD Weekly Ensemble Trend Research

**ID:** `LH-XAUUSD-W1-2026-10-17`
**Status:** every value below was frozen in
`src/qts/research/longhistory/weekly_protocol.py` (builders in
`ensemble_signals.py`) **before any holdout or replicate result of this
cycle existed**. Discovery used only the 2004–2009 pre-walk-forward
partition. `--stage dev` (walk-forward 2010–2019 only) ran as pipeline
debug before this document, so the G3 walk-forward component is
knowable pre-final — stated here as in the parent monthly cycle.
Runner: `scripts/run_longhistory_weekly.py --stage dev|final`.
**Parents:** all prior long-history cycles; this cycle runs after
`LH-XAUUSD-ENS-2026-10-17` in the same series (trial count, §5).

## 1. Question

Daily trend failed on cost (M15/daily cycles: gross-positive, net-thin,
negative walk-forward); monthly trend failed on sample size (G6) and
1990s stability. The **weekly** timeframe — never evaluated in this
repository — is the intermediate frequency: ~5x the monthly decision
count at ~1/7 the daily turnover. Do multi-horizon weekly ensembles,
weekly MA/breakout trend states, and their long-or-flat forms pass the
inherited gate chain where the neighbouring frequencies did not?

## 2. Data and windows

Weekly bars are W-FRI resamples of the complete-day BaseMax daily series
(open=first, high=max, low=min, close=last; 1,078 weeks 2004-06 →
2025-02). Replicate: Dukascopy complete-day daily resampled the same
way (2025-08 → 2026-09), informational only. Execution: decision at week
`t` fills at week `t+1` open; `fixed_units.v2` accounting; 10% vol
target on 26-week realised vol, cap 1.0x, no stops.

| Stage | Window | Purpose |
|---|---|---|
| Discovery (done, pre-freeze) | 2004-06 → 2009-12 | Candidate selection only (§4) |
| Walk-forward | expanding selection, test years 2010–2019 | G3 input |
| Holdout | selection through 2019-12-31, run 2020-01 → 2025-02 | Gates (reused calendar — disclosed) |
| Replicate | 2025-08 → 2026-09 Dukascopy weekly | Informational |

The 2020–2025 holdout calendar was used by the daily/M15 cycles for
other families; the weekly frequency and these builders were never
evaluated on it. Costs ASSUMED: verdict ceiling
`FORWARD_VALIDATION_CANDIDATE_ONLY`, `claim = none`. No DEMO/LIVE, risk
or order-path state changes; `REAL_CAPITAL_EXPOSURE = 0`.

## 3. Gates (inherited, thresholds unchanged)

G1 holdout net > 0 and Sharpe > 0 · G2 net > 0 at 2x cost · G3 WF
Sharpe > 0 and ≥ 6/10 positive years · G4 Holm p ≤ 0.05 · G5 DSR ≥ 0.95
at `N_TRIALS` (§5) · G6 ≥ 100 OOS round turns · G7 ≥ 3/4 regimes
net-positive with all present · G8 break-even ≥ 2.0x. Selection rule:
highest training Sharpe among candidates with ≥ 20 training round
turns, per group.

## 4. Candidates (9 + 1 control) and discovery record

| Group | Candidate | Definition (weeks) |
|---|---|---|
| `wk_ens` | `w_e132652_ls` | summed TSMOM signs 13/26/52, long-short |
| `wk_ens` | `w_e4132652_ls` | summed signs 4/13/26/52, long-short |
| `wk_ens` | `w_e4132652_ls_gr` | same, size × vote share |
| `wk_trend` | `w_max13_52_ls` | SMA 13/52 state, long-short |
| `wk_trend` | `w_sma52_ls` | close vs 52w SMA state, long-short |
| `wk_trend` | `w_don26_ls` | 26w close-breakout state, long-short |
| `wk_longonly` | `w_max13_52_lo` | SMA 13/52, long-or-flat |
| `wk_longonly` | `w_sma52_lo` | close vs 52w SMA, long-or-flat |
| `wk_longonly` | `w_e4132652_lo` | ensemble 4/13/26/52, long-or-flat |
| (control) | `w_boll20_2` | CONTROL 20w 2σ Bollinger reversion |

**Discovery (2004–2009, 43 configurations):** single TSMOM 4/8/13/26/
39/52 LS/LO, ensembles {4,13,26}/{13,26,52}/{4,13,26,52}/{8,26}/{4,13}
LS/LO/graded, price-vs-SMA 10/26/52 LS/LO, SMA crosses (4,26)/(10,52)/
(13,52) LS/LO, Donchian 13/26 LS/LO. Frozen-set discovery Sharpe:
`w_max13_52_lo` 1.198, `w_sma52_lo` 1.107, `w_e132652_ls` (LS form)
0.797 / LO 1.096, `w_e4132652_ls` 0.767, `w_max13_52_ls` 1.083,
`w_sma52_ls` 0.856, `w_don26_ls` 0.767; buy-and-hold 1.005 (the
2004–2009 gold bull inflates every long-biased figure — the frozen
walk-forward/holdout, not discovery, is the test).

## 5. Trial count

`DISCOVERY_TRIALS = 44` (43 discovery + control). Inherited `N = 149`
through `LH-XAUUSD-ENS-2026-10-17`. **`N_TRIALS = 193`.**
