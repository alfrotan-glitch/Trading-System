# Preregistration — XAUUSD Calendar-Seasonality (Session / Weekday / Scheduled-Event) Research

**ID:** `LH-XAUUSD-SES-2026-10-14`
**Status:** every value, window, threshold and gate in this document was
written and frozen before any walk-forward, evaluation-window, replicate or
final-stage result of this cycle existed, and none changed afterwards. The
first execution was `--stage dev` (walk-forward folds 2010–2019 only — no
evaluation window, no replicate), used as a pipeline debug exactly as §6
defines it, run after this text and the candidate code reached their final
form; post-dev edits were bookkeeping only (bar counts, the cost-regime list
matching the already-written code, and §10.6). This document is committed
before `--stage final` is run. Code:
`src/qts/research/longhistory/seasonal_protocol.py`,
`seasonal_signals.py`. Runner: `scripts/run_longhistory_seasonal.py --stage
dev|final`. Stamp-basis evidence (collected before this freeze):
`data/evidence/longhistory/stamp_basis_probe.json`.
**Parent cycles:** `LH-XAUUSD-D1-2026-10-10`, `LH-XAUUSD-M15-2026-10-10`
(`preregistration_longhistory_2026-10-10.md`,
`preregistration_longhistory_m15_2026-10-10.md`). Data provenance, execution
engine, costs, selection rule and gates are inherited unchanged except where
§10 says otherwise.

This document fixes the question, candidates, windows, selection rule, gates
and verdict rule before this cycle's results exist. A failed gate is a failed
gate. Nothing here may be re-tuned against the holdout or the replicate. If a
value must change, the change is a new experiment with a new ID.

## 1. Question

Does any simple, causal, calendar-anchored (time-of-day session, trading
day-of-week, or scheduled payrolls-release) XAUUSD rule produce positive net
performance after ASSUMED costs that survives the same chain of tests as the
parent cycles: walk-forward selection on 2010–2019 out-of-sample years, the
2020-01-01 → 2025-02-28 evaluation window with training-only selection, 2× and
3× cost stresses, a multiple-testing correction over every configuration
evaluated on this research series, and a mechanical regime split?

This family is **genuinely untested in this repository.** The edge-discovery
map lists hour/session/day-of-week structure (`H-TOD-01`) as `NOT TESTED /
BLOCKED` behind an unconfirmed clock; the long-history cycles tested trend,
breakout, volatility-expansion and price-conditioned session-breakout rules
but no signed calendar-drift rule; the tick campaign's `H-TEMP-01` tested
hour-of-day *magnitude* (rejected), not direction. The two blockers that held
`H-TOD-01` are now resolved for the bar data: (a) the broker-clock conversion
is established (`server_gmt23_to_utc`, verified against an explicit-UTC
reference series), and (b) bar stamp semantics are established by the
pre-freeze probe below.

This is a **research** question. A pass earns forward validation, not a claim.
Every cost in this cycle is ASSUMED, so no economic-edge claim can result.

## 2. Data and windows

Identical to the parent cycles:

| Role | Source | Window (UTC, complete trading days, 22:00 roll) | Size |
|---|---|---|---|
| Research (selection, walk-forward, evaluation window) | BaseMax XAUUSD 15-minute bars, server clock → UTC | 2004-06-11 → 2025-02-28, complete trading days only | 474,388 bars |
| Replicate (informational, final stage only) | Dukascopy mirror 15-minute mid bars, UTC | 2025-08-06 → 2026-09-16 | 26,030 complete-day bars |

**Stamp basis (established before this freeze).** The parent M15 cycle stated
that open-vs-close stamp semantics were unestablished. Two independent,
rule-based probes over 2004–2019 only (no return signs examined) now agree
that the stamps mark the bar **OPEN**:

1. *Maintenance-break probe:* the CME/spot gold halt (17:00–18:00 ET) leaves
   winter hour 22 UTC completely absent (0 bars over 2,270 winter days) and
   summer hour 21 UTC empty, with the first bar after the halt stamped 23:00 /
   22:00 — the open-stamp prediction, 4/4 features; the close-stamp prediction
   fails all four.
2. *NFP release-spike probe:* on 179 first-Friday 08:30 ET releases, relative
   intrabar range peaks at the release minute itself (delta 0: 2.22× the
   hour-matched baseline) rather than at the following bar (delta +15: 1.50×),
   i.e. the bar stamped 12:30/13:30 contains the reaction.

Evidence: `data/evidence/longhistory/stamp_basis_probe.json` (probes agree,
`established_basis = OPEN_STAMP`). Any bar whose open stamp is missing is not
invented: gaps stay gaps.

**Holdout reuse (disclosed, material).** The 2020–2025 evaluation window was
already evaluated by the daily and M15 cycles for *other* families, and the
replicate window was viewed by several earlier studies. Neither window is a
fresh sample for this cycle. The protections this cycle adds are: the calendar
family was never evaluated on either window; every configuration evaluated on
this series counts toward the deflation (`N_TRIALS = 47`, §7); and the verdict
cannot exceed `FORWARD_VALIDATION_CANDIDATE_ONLY` with `claim = none` in any
case (costs ASSUMED). The prior research brief's instruction not to run
further parameter sweeps on the reused holdout applies to re-tuning the *tested*
families; this cycle adds a new family under a new preregistration, as the M15
cycle did after the daily cycle. This deviation-from-freshness is stated
wherever a result is reported.

## 3. Execution model (inherited, unchanged)

Identical to the parent cycles: a decision at the close of bar `t` fills at
the open of bar `t+1`; positions are marked open→close with gap-to-open
handling; windows are self-contained (forced exit at the final close); initial
equity USD 10,000; no leverage (position cap 1.0× equity); vol-target sizing
(10% annualised over 60 trading days in bars, the parent no-stop convention);
no protective stops in any candidate (horizons are calendar-bounded);
accounting identity (ledger net = equity change) is tested.

## 4. Costs (ASSUMED)

Inherited: `CostModel(spread_bps=3, slippage_bps=1 per side, commission=$7 per
lot per side, financing=0)`, about 6.1 bps round turn at $1,300. Gating uses
this base plus the 2× and 3× stresses and the break-even multiplier, exactly as
the parent cycles.

Pre-declared non-gating diagnostics (reported, never used for selection):

1. **Spread regimes** (four) from `docs/research/m15_cost_sensitivity_2026-10-11.md`:
   canonical `xauusd_default` ($0.30/oz spread, $0.10/oz slippage/side, $0
   commission), WM measured median ($0.24/oz spread, $0.10/oz slippage,
   $0 commission, `MIXED` — spread MEASURED, slippage ASSUMED), WM median +
   ECN commission ($0.24/oz + $0.10/oz + $7/lot/side), and WM
   reopen-hour stress ($0.39/oz, $0.15/oz, $7/lot/side).
2. **Overnight (swap) diagnostic:** trades are counted for 22:00 UTC rollover
   crossings between entry and exit stamps; drag = crossings × $3.5 per lot
   per night (`ASSUMED`, the figure already disclosed in the agent-4 audit),
   lots estimated from the entry fraction and entry price at initial equity.
   The session family is designed to never cross the rollover; the diagnostic
   verifies that claim mechanically.

## 5. Candidate grid (7 configurations, all counted as trials)

Session windows are fixed **ex ante** from the standard FX session taxonomy in
UTC; they were not searched on any sample. The session family is flat in
[21:00, 24:00) UTC — the maintenance halt and rollover hours — so no session
trade can ever hold through the 22:00 rollover.

| Group | Candidate | Definition |
|---|---|---|
| `session_drift` | `sd_all` | Trade every completed window occurrence: Asia [00:00,07:00), Europe [07:00,13:00), US [13:00,21:00) UTC. Occurrence return `r = close[last bar of window] / open[first bar of window] − 1` per window per trading day. Direction per window = sign of the expanding mean of past occurrence returns for that window if `|t| ≥ 2.0` and `n ≥ 250`, else flat. Entry decision at the last bar before the scheduled window start, executed at the engine's next-available open; scheduled window end → flat at the next open (fill rule below). Occurrence statistics require the window's first and last bars to exist. |
| `session_drift` | `sd_strongest` | Same statistics and windows, but only the single window with the highest `|t|` (ties: Asia > Europe > US) is traded per day, and only if that `|t| ≥ 2.0` with `n ≥ 250`; the other windows are flat. |
| `weekday_drift` | `wd_all` | Trade whole trading days by day of week of the trading-day label (Mon–Fri). Occurrence return `r = open[first bar of day D+1] / open[first bar of day D] − 1` (the exact gross return the hold earns). Direction per weekday = sign of the expanding mean of that weekday's past occurrence returns if `|t| ≥ 2.0` and `n ≥ 250`, else flat. One position per trading day, decided at the previous day's last bar, entered at the day's first open (22:00), exited at the next day's first open. The decision bar is identified by the *next row's stamp* (session calendar, never future data): a decision fires where the trading-day label changes. Decision bars carry `rebalance=True`, so a repeated direction resizes to the current vol-target size each day and the parent truncation check's final-bar rebalance exemption covers exactly the cut bar. Across the weekly gap this makes Friday's close decide Monday (the next existing row is Sunday 22:00, labelled Monday), so all Mon–Fri labels trade. |
| `nfp_drift` | `nfp_h4` | US payrolls (first Friday of the month, 08:30 ET → 12:30/13:30 UTC by the US DST rule) in the year range of the data. Reaction bar `R` = the bar stamped at the release minute (open stamps). Enter at the open of `R+1`, hold exactly 4 M15 bars (1 hour), exit at the open after bar `R+4`. Occurrence return `r = open[R+5]/open[R+1] − 1`. Direction = sign of the expanding mean of past event returns if `|t| ≥ 2.0` and `n ≥ 48` events, else flat. If no bar exists at the release stamp, the event is skipped entirely (no trade, no occurrence). A window whose bars are not contiguous contributes no occurrence to the statistics (the decision still comes from past occurrences only, per the fill rule below). |
| `nfp_drift` | `nfp_h16` | As `nfp_h4` with a 16-bar (4-hour) hold: enter at `R+1` open, exit after `R+16`, `r = open[R+17]/open[R+1] − 1`. |
| (control) | `wd_perm1_control` | CONTROL, never a candidate. `wd_all` with every weekday's direction taken from the *next* weekday's statistics (Mon←Tue, …, Fri←Mon; a fixed relabeling with no data access). It shares the full machinery; if the control outperforms the aligned candidates, calendar alignment itself is suspect. Counts as a trial. |

**Placebo control windows (frozen).** The session-family control candidate is
the placebo spec below: identical machinery on a fixed +3 h rotation of the
taxonomy that stays inside the tradable span — Asia [03:00,10:00), Europe
[10:00,16:00), US [16:00,21:00) UTC, still flat [21:00,24:00).

| Group | Candidate | Definition |
|---|---|---|
| (control) | `sd_placebo_h3_control` | `sd_all` on the placebo windows above. Counts as a trial. Never a candidate. |

**Fill rule at missing bars (frozen).** Decisions are taken from bar-level
stamps only — either the bar's own stamp (session/NFP: the schedule is calendar
knowledge, not future data) or the next row's stamp (weekday: the trading-day
label of the next scheduled/existing row) — and execute at the engine's
next-available open. If a window's first bar is
missing, the scheduled decision still executes at the next existing row; if the
scheduled last bar of a window is missing, the scheduled flat decision
executes at the next existing row, which can delay the exit by one bar and, in
rare source gaps, into the halt/rollover hours. The swap diagnostic (§4)
counts actual 22:00 UTC rollover crossings per trade, so any such leak is
measured rather than assumed away. Occurrence statistics require the window's
first and last bars to exist; middle gaps do not delete an occurrence.

**Grid size:** 5 candidates + 2 controls = 7 configurations.
`N_TRIALS_THIS_CYCLE = 7`; `N_TRIALS = 40 + 7 = 47` — every configuration
evaluated across the daily (26), M15 (14) and this cycle (7) on the same
research series feeds the Deflated Sharpe Ratio. Holm's step-down runs across
this cycle's three groups, as it ran across each cycle's groups.

**Sign convention (frozen):** `dir = sign(expanding mean of r)` taken only when
`|t| ≥ t_floor` with `t_floor = 2.0` and the warm-up count is met
(`min_occurrences = 250` for session/weekday, `min_events = 48` for NFP);
otherwise the position is 0. Statistics for a decision use only occurrences
that are complete and knowable at that bar (per-group expanding statistics
lagged by one occurrence; the NFP decision at bar `R` uses only events before
the current one). No other filter, no stacking, no fitted boundary, no regime
condition is permitted.

**Must-not-trade conditions (frozen):** flat in [21:00,24:00) UTC for the
session family; flat until warm-up is met; flat when the t-floor is not met;
no NFP trade when the release or required bars are missing; no same-window
re-entry blocking is needed (state is re-decided at every window boundary).

## 6. Windows, selection and stages (inherited)

- Walk-forward: expanding training from 2004-06-11, one test year per fold,
  2010–2019. Within each group the candidate with the highest training net
  Sharpe at base costs (≥ 20 training round turns, ties to the earlier
  candidate) is frozen for that year.
- Evaluation window ("holdout"): selection once on data through 2019-12-31,
  then a single run on 2020-01-01 → 2025-02-28 per group, at base, 2×, 3× and
  zero cost, with break-even bisection and the trade-level sign-randomisation
  null. Reused from the parent cycles — disclosed in §2.
- Replicate: frozen holdout selections run unchanged on the Dukascopy series.
  Because these builders fit expanding statistics, the replicate plans are
  built on the concatenation of the research series and the replicate series
  (history prefix), so the frozen rule ("expand from the start of available
  history, warm up, then trade") is evaluated with its natural history; the
  run window itself is replicate-only. Informational, not a gate.
- Stages: `dev` = walk-forward only (pipeline debugging, never evaluates the
  evaluation window or replicate). `final` = everything, run once after this
  document is committed.

## 7. Statistics and gates

Inherited: annualised Sharpe on per-bar returns including flat bars
(√23,184); circular block bootstrap (block 20) Sharpe intervals; one-sided
block-bootstrap p-values (2,000 draws); Holm across the three groups; DSR with
`N_TRIALS = 47` on combined out-of-sample returns (walk-forward + evaluation
window); trade-level sign-randomisation null; causal regime labels
(12-month trend × expanding-median volatility in bar units).

| Gate | Test (unchanged thresholds from the parent cycles) |
|---|---|
| G1 | Evaluation-window net P&L > 0 **and** Sharpe > 0 at base cost |
| G2 | Evaluation-window net > 0 at 2× cost |
| G3 | Walk-forward 2010–2019 Sharpe > 0 **and** ≥ 6 of 10 test years net positive |
| G4 | Holm-adjusted p ≤ 0.05 across this cycle's groups |
| G5 | DSR ≥ 0.95 with `N = 47` on combined out-of-sample returns |
| G6 | ≥ 100 out-of-sample round turns (walk-forward + evaluation window) |
| G7 | Net positive in ≥ 3 of 4 regimes, all four present out-of-sample |
| **G8 (new, stricter)** | Evaluation-window **break-even cost multiplier ≥ 2.0** — a pass must tolerate doubling the assumed all-in cost before any forward-validation recommendation. Added by this cycle; it can only fail a candidate, never pass one. |

**Verdict rule.** Any group passes G1–G8 →
`FORWARD_VALIDATION_CANDIDATE_ONLY`; the claim is still `none` (costs
ASSUMED; the evaluation window is reused — both stated in the verdict).
No group passes → `NO_VALIDATED_EDGE`, naming the failing gates. Nothing here
places orders or changes DEMO/LIVE state, risk limits, or authorisation.

## 8. Minimum effect, sample and risk thresholds (pre-stated)

- **Economic:** positive net after base costs (G1) and at 2× costs (G2), plus
  break-even ≥ 2× base cost (G8). A candidate whose zero-cost P&L is positive
  but base-cost P&L ≤ 0 is rejected as cost-incapable; a candidate negative
  even at zero cost is rejected outright.
- **Sample:** ≥ 100 out-of-sample round turns (G6); ≥ 20 training turns for
  eligibility in any selection window (inherited); warm-ups of 250 completed
  occurrences / 48 events are stated in §5.
- **Risk:** no gate may be evaluated on a group whose regime coverage is
  incomplete (G7); the evaluation-window max drawdown and exposure are
  reported for every group (reporting requirement, not a gate — the parent
  cycles did not gate drawdown either, and adding a gate after seeing no
  results would be as arbitrary as removing one).
- **Multiplicity:** 47 trials deflation + Holm across groups (G4/G5).

## 9. What would falsify the family

- Any group failing any of G1–G8 → the group's mechanism does not produce a
  tradable edge here, and the precise failing gate names where.
- The control (`wd_perm1_control`) passing while an aligned weekday candidate
  fails → calendar alignment is not the operative factor.
- Directions that flip sign across walk-forward folds (reported per fold) →
  non-stationarity, reported even if a gate passes.

## 10. Deviations from the parent cycles (all pre-declared)

1. New families (session/weekday/NFP) and new candidate builders; everything
   else is inherited by reference so it cannot drift.
2. New gate G8 (break-even ≥ 2×), stricter than the parents.
3. Replicate plans use a research-series history prefix (§6); the parent
   cycles' stateless indicators needed no prefix.
4. Two pre-declared non-gating diagnostics (cost regimes, swap crossings, §4).
5. Holdout reuse disclosed (§2); `N_TRIALS = 47` counts this cycle's seven
   configurations on top of the parents' forty.
6. Trial-count bookkeeping: as in ARCH-020/021, the count lives in this
   preregistration and `seasonal_protocol.N_TRIALS` (47) and is used for
   Holm/DSR. `docs/experiment_ledger.md` is a generated aggregate of the
   SQLite experiments table (`qts edge`), not a hand-edited document, and is
   not modified by this cycle — no manual adjustment of any trial count.

## 11. Out-of-scope (blocked, not attempted here)

- `H-TOD-01` on the canonical 730-day tick archive: the release asset
  (`XAUUSD_730d_...zip`, 1.02 GB) redirects to `release-assets.githubusercontent.com`,
  which is unreachable from this sandbox (host allowlist), and the 40% locked
  holdout must not be opened without the operator's download. This cycle runs
  on the bar series only.
- Measured commission, slippage, financing: still require the Windows MT5
  DEMO terminal (`qts demo cost-check --record`). Costs remain ASSUMED.
- Cross-asset conditioning (DXY, real yields), futures basis, order flow:
  no data in the repository (documented information-gap audit).
