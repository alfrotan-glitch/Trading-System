# Preregistration — XAUUSD Monthly Ensemble / USD-Conditioned Trend Research

**ID:** `LH-XAUUSD-ENS-2026-10-17`
**Status:** every value, window, threshold and gate below was frozen in
`src/qts/research/longhistory/ensemble_protocol.py` (builders in
`ensemble_signals.py`) **before any evaluation-window or replicate result
of this cycle existed**, and none may change afterwards. Discovery was
completed on data ending 1989 only; its full outcome count is recorded in
§5. Order of operations: (1) discovery on ≤1989 slices (73 + 3
configurations, §5), (2) protocol/builder code freeze, (3) `--stage dev`
pipeline debug (walk-forward folds 1990–1999 only — no evaluation window,
no replicate), committed as
`data/evidence/longhistory/ensemble_research_dev.json`; this document is
committed before `--stage final`. As in the parent monthly cycle, the dev
stage makes the walk-forward component of G3 knowable before final; the
evaluation-window component is not knowable. That fact is stated, not
papered over. Runner: `scripts/run_longhistory_ensemble.py --stage dev|final`.
**Parent cycles:** `LH-XAUUSD-D1-2026-10-10`, `LH-XAUUSD-M15-2026-10-10`,
`LH-XAUUSD-SES-2026-10-14`, `LH-XAUUSD-REV-2026-10-14`,
`LH-XAUUSD-MON-2026-10-15`.

## 1. Question

The monthly cycle's single-lookback TSMOM / USD-veto / USD-agreement
candidates passed the evaluation-window, cost, break-even and financing
gates and failed walk-forward stability (1990s), deflated Sharpe and
sample size. Two untested variations target exactly those failures
without re-tuning any frozen parent parameter:

1. **Multi-horizon majority-vote ensembles** (2/4/8, 6/12, 3/6/12,
   1/3/6/12, 1/3/12 months; one vote-share-graded sizing variant):
   averaging horizon signs is the standard variance-reduction form of
   time-series momentum (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi &
   Pedersen 2017) and flips less erratically than any single lookback.
2. **The same ensembles conditioned on the 12-month USD index**
   (short-veto and full-agreement forms), extending the parent cycle's
   best walk-forward family (`usd_agreement`, WF Sharpe 0.154) to the
   faster ensemble signal that dominated this cycle's discovery.
3. **Long-or-flat forms** of the fastest ensemble and two slow trend
   states, testing whether gold's positive long-run drift makes the
   short side the whipsaw source.

## 2. Data and windows (inherited, unchanged)

| Role | Source | Window | Size |
|---|---|---|---|
| Research | World Bank Pink Sheet monthly gold + Fed H.10 USD index (pinned, SHA-256 verified) | 1973-01-31 → 2026-09-30 | 645 months |
| Replicate (informational) | BaseMax XAUUSD monthly OHLC from 15m bars | 2004-06 → 2025-02 | 249 months |

Execution: decision at month `t` fills at month `t+1`'s published average
(TWAP convention of the parent monthly cycle). Sizing/accounting:
`fixed_units.v2`, 10% vol target (12-month realised vol), cap 1.0x, no
stops. Holdout reuse is disclosed as in the parent monthly preregistration:
the 2000–2026 calendar overlaps earlier cycles' windows for other
families; the ensemble/USD-conditioned/long-only forms were never
evaluated on it before; every configuration counts toward deflation
(§6); costs are ASSUMED so the verdict cannot exceed
`FORWARD_VALIDATION_CANDIDATE_ONLY` with `claim = none`.

| Stage | Window | Purpose |
|---|---|---|
| Discovery (done, pre-freeze) | selection 1973–1983 / test 1984–1989 | Candidate selection only (§5) |
| Walk-forward (dev) | expanding selection from 1973, test years 1990–1999 | Pipeline debug; G3 input |
| Evaluation window | selection through 1999-12-31, run 2000-01 → 2026-09 | Gates G1, G2, G4–G9 |
| Replicate | 2004-06 → 2025-02 BaseMax monthly, frozen selections | Informational, never gating |

Selection rule (inherited): within each group, highest training-window
net Sharpe at base costs among candidates with ≥ 20 training round
turns; ties to earlier registry order. (Mechanical consequence, known
pre-freeze: slow MA/breakout states reach < 20 round turns in 27 years
— `max3_12` has 19 training turns through 1999 — so no slow-MA group is
registered; the one long-only MA candidate may be ineligible in early
folds, which the selection rule handles by construction.)

## 3. Costs (ASSUMED, inherited)

Base `3 bps spread + 1 bp slippage/side + $7/lot/side`; 2x/3x stresses;
break-even bisection; financing-charged regime `+0.25 bps/day` (G9).
Swap diagnostic inherited from the parent monthly cycle is not repeated
(the turnover class is unchanged); financing G9 is the gating form.

## 4. Gates (inherited G1–G9, thresholds unchanged)

G1 evaluation net > 0 and Sharpe > 0 · G2 net > 0 at 2x cost · G3 WF
Sharpe > 0 and ≥ 6/10 positive years · G4 Holm p ≤ 0.05 across groups ·
G5 DSR ≥ 0.95 at `N_TRIALS` (§6) · G6 ≥ 100 OOS round turns (WF +
evaluation) · G7 ≥ 3 of 4 mechanical regimes net-positive OOS with all
four present · G8 break-even ≥ 2.0x · G9 financing-charged net > 0.
All must pass. Nothing here promotes a strategy, moves a risk limit, or
touches DEMO/LIVE state; `REAL_CAPITAL_EXPOSURE = 0`, LIVE LOCKED.

## 5. Candidate grid and discovery record (12 candidates + 1 control)

Builders frozen in `ensemble_signals.py`. `Δₗ` = log monthly return.

| Group | Candidate | Definition |
|---|---|---|
| `ens_fast` | `e248_ls` | sign of summed signs of Δₗ gold over 2/4/8m |
| `ens_fast` | `e248_ls_graded` | `e248_ls`, size × winning vote share |
| `ens_fast` | `e1312_ls` | sign of summed signs over 1/3/12m |
| `ens_multi` | `e612_ls` | summed signs over 6/12m |
| `ens_multi` | `e3612_ls` | summed signs over 3/6/12m |
| `ens_multi` | `e13612_ls` | summed signs over 1/3/6/12m |
| `usd_conditioned` | `e248_usdveto` | `e248_ls`; shorts only while USD index rose 12m |
| `usd_conditioned` | `e13612_usdveto` | `e13612_ls`; shorts only while USD index rose 12m |
| `usd_conditioned` | `e248_usdagree` | `e248_ls` only when 12m USD move agrees, else flat |
| `long_only` | `e248_lo` | `e248_ls` with shorts clipped to flat |
| `long_only` | `max3_12_lo` | SMA 3/12 state, long-or-flat |
| `long_only` | `ts9_lo` | 9m TSMOM sign, long-or-flat |
| (control) | `m_boll20_2` | CONTROL 20m 2σ Bollinger reversion, never a candidate |

**Discovery record (complete).** 76 configurations were evaluated on the
≤1989 partition (73 in the first grid: single-lookback TSMOM LS/LO at
1/2/3/4/6/9/12/18/24m, ensembles {1,3,12}/{3,6,12}/{1,3,6,12}/{2,4,8}/
{6,12}/{3,12}/{1,6,12}/{1,2,3,12} in LS/LO/graded forms, price-vs-SMA
5/10/12/20 LS/LO, SMA crosses (3,12)/(5,20)/(2,10)/(10,24) LS/LO,
Donchian 6/12 LS/LO, two vol-gated ensembles, one USD-veto ensemble;
then 3 USD-conditioned fast ensembles). Selection/test annualised
Sharpe for the frozen set: `e248_usdveto` 1.059/0.569 (best of all 76),
`e248_ls` 0.930/0.702, `e248_usdagree` 0.934/0.591, `ts9_lo` (as
`ts_lo_9`) 0.779/0.563, `e612_ls` 0.706/0.610, `e3612_ls` 0.763/0.515,
`e13612_ls` 0.634/0.548, `e13612_usdveto` 0.731/0.539, `e1312_ls`
0.444/0.604, `e248_lo` 0.872/0.537, `max3_12_lo` 0.838/0.596.
Buy-and-hold on the same slices: 0.662/0.139. The full ranked table is
reproducible from `scratch/` discovery scripts (not committed; the
counts and this summary are the committed record, as in parent cycles
the raw grid output is regenerated on demand).

## 6. Trial count

`DISCOVERY_TRIALS = 77` (76 discovery configurations + the re-registered
control). Inherited cumulative `N = 72` through `LH-XAUUSD-MON-2026-10-15`.
**`N_TRIALS = 149`.** No hand-edited ledger; `docs/experiment_ledger.md`
(SQLite count) is a different registry and is not touched.
