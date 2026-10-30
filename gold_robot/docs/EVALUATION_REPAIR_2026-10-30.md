# Evaluation — Repair of `independent/adaptive-robot-20261030@34cab34`

Date: 2026-10-30. Branch: `independent/adaptive-repair-20261030`, from
exact `34cab34` (tree `f293c00…7760`, verified before starting).
Base branch and `main` are untouched. No push, no merge, no PR,
live trading disabled. MQL5 is UNCOMPILED on Linux (no MetaEditor /
MT5); nothing here is a native MT5 result.

## Verdict: NO-GO for production, for every candidate

The failing gate is unchanged and is named for each candidate below:
native evidence missing. No native HTML + forensic CSV exists for the
repaired router, SMC, or scalp on any window, and the MQL5 code in
this branch has not passed MetaEditor. Repairing Linux-side tooling
does not move any candidate toward GO; it removes false evidence
that could have made a later Windows run look stronger than it is.

| Candidate | Failing gate |
|---|---|
| Hardened router, guard repaired (Style 7) | Native evidence missing; MQL5 uncompiled; guard fix changes router decisions, so the repaired router is a NEW variant that must be declared as the Style 7 trial in the repair-branch Windows run, not silently substituted for the old one |
| SMC Style 8 | Same, plus MQL5 uncompiled |
| M1 scalp Style 9 | Same, plus MQL5 uncompiled; M1 run now inside the one Windows workflow (see below), still pending execution |

## Defect-by-defect audit verdicts

### 1. Windows installer — CONFIRMED AND FIXED

Evidence: `QTS_Gold_Robot.mq5` lines 581–585 `#include`
ExecutionPolicy, StructureResearch, OpportunityResearch,
AdaptiveResearch, SmcResearch, ScalpResearch. `Install_QTS_Gold_Robot.ps1`
previously validated, deployed, backed up, and post-compile-checked
only the first five files (main + 4 includes). SmcResearch and
ScalpResearch were never validated against `SOURCE_CHECKSUMS.json`
and never deployed — so an old Smc/Scalp file already sitting in
`Experts` would have been compiled silently against new source, and
a missing one would only have failed at compile time with no
manifest diagnosis. Adaptive was validated before copying but never
re-checked after compilation, unlike policy/structure/opportunity.

Fix (this branch): Smc + Scalp added to manifest validation,
deployment, backup, post-compile hash verification, and rollback;
Adaptive post-compile hash check added. `Install_MT5_Canonical.ps1`
prerequisites and `SETUP_MT5_GOLD.bat` fail-fast checks extended to
all six files. Gold regression tests now assert the installer's
deployed set equals the EA's `#include` set, so a future include
added to the EA without an installer entry fails a test instead of
shipping stale. Static verification on Linux only: PowerShell
brace/paren balance and the gold tests; actual installation and
compilation remain PENDING Windows (the installer itself is
fail-closed: it refuses to install without a zero-error/zero-warning
MetaEditor log and a fresh EX5).

### 2. CopyBuffer ATR indexing — CONFIRMED AND FIXED (one site only)

Audit scope: every `CopyBuffer` call in `mt5_robot/*.mq5|*.mqh`
and every `CopyRates`/`CopyClose` use in `research/*.mq5` tools;
`ArraySetAsSeries` appears nowhere in the repo, so every copy
array is in MQL5 default (non-series) order: OLDEST first.
`CopyBuffer(handle, 0, 1, N, buf)` therefore puts shift N at
`buf[0]` and shift 1 (latest closed) at `buf[N-1]`.

- All count=1 copies (every ATR read except the guard, every H1
  MA read): index-independent, CORRECT.
- Count=2 fast/slow EMA copies in `CompletedBarSignal` and
  `CompletedOpportunitySignal`: code reads `[1]` as latest closed
  and `[0]` as the older bar, matching oldest-first order, and the
  repo's own comment says so. CORRECT.
- All `CopyRates`/`CopyClose` multi-bar reads (Structure,
  Opportunity, SMC, Scalp): code reads `[n-1]` as latest closed,
  and contiguity checks (`bars[i].time - bars[i-1].time == frame`)
  fail closed if the order were ever different. CORRECT.
- `RouterVolatilityGuardPass` (`AdaptiveResearch.mqh`):
  `CopyBuffer(atr_handle, 0, 1, 50, values)` then
  `current = values[0]` — values[0] is shift 50, the OLDEST bar,
  not the current ATR. CONFIRMED DEFECT: the guard abstained or
  passed on volatility from 50 bars ago. The percentile count
  itself is order-insensitive, so only the reference bar was
  wrong. Fix: `current = values[ROUTER_ATR_LOOKBACK_BARS-1]`.
  Window (50), percentile (0.90), and abstention rule are
  UNCHANGED — this is an indexing correction, not a retune, but
  it changes router decisions, so it is a new router variant for
  trial accounting (see below).
- The Python mirror (`research/router_logic.py`) had the same
  defect in its contract: it documented "values[0] = most recent"
  and its test encoded most-recent-first input. Both are corrected
  together: the mirror now takes CopyBuffer order (oldest first)
  and reads the LAST element, and its test includes the exact
  bug discriminator (oldest bar spiking must not abstain the
  guard; latest closed bar spiking must).
- `research/*.mq5` tools pass `rates[]` straight to
  `CustomRatesUpdate` without indexing: NOT A DEFECT.

Parity statement (exact, not inflated): after this repair, Python
and MQL5 agree on regime thresholds, 3-bar persistence, transition
abstention, the ATR guard reference bar, SMC construction, and
scalp signal construction, as far as Linux static review and
mirror unit tests can show. They do NOT agree on, and the mirror
does not model, candidate scoring (priority + capped ratio −
spread term), sizing, session, fills, or broker preflight. Full
decision-by-decision parity is a Windows task (see the Windows
guide, Step 5) with a predeclared kill rule: >5% chosen-style
mismatch on the same closed bars invalidates the mirror, not the
EA. No parity claim beyond the mirror scope above is made here.

### 3. 2x cost calculation — CONFIRMED AND FIXED (false figure)

Evidence (reproduced numerically before fixing): a hand ledger
(gross 150, charges 30, 1x net 120) produced
`robustness_2x_costs_net = 120.0` — the UNDOUBLED net — because
the code reported `gate["net_usd"]`, which `edge_gate` never
doubles, while its mean-cost stress also excluded slippage
entirely. A reader of the old field would have believed a
strategy survived doubled costs when the figure had never been
doubled at all. That is false evidence, and it is the single most
important repair in this branch.

Fix: the 2x gate now passes stress = mean charged per trade
(slippage included iff the gross basis is PRE_SLIPPAGE, exactly
matching `edge_gate`'s charge definition), and the reported 2x
figure is that gate's `stressed_net_usd` = gross − 2×charged.
Hand-verified: 1x 120, 1.5x 105, 2x 90, slippage-doubled 110 on the
same ledger. For ACTUAL_EXECUTED_FILLS, slippage is already inside
gross, so the slippage-doubled figure is reported as
NOT_APPLICABLE rather than double-counted (1x 130, 2x 110 on the
same ledger with slippage treated as diagnostic only). Spread
stress is parameterised: with no per-trade spread USD in a ledger,
it is NOT_MEASURABLE, never invented; with a supplied (ASSUMED
unless measured) spread it is net − 0.5×spread×N (1.5x) and
net − 1.0×spread×N (2x). The genuine native spread stress is a
separate Tester run with a doubled spread model, counted as its
own trial. Costs remain ASSUMED ($10/lot round-turn, $0.10 stop
slippage, tester tick spread) until a measured WMMarkets statement
exists; the EA's `AssumedRoundTurnFeePerLot` is a round-turn
figure applied once per trade (budget and TP multiple), not per
side — no per-side double-count was found in the EA.

### 4. Walk-forward, WFE, counterfactuals, cost robustness — REPAIRED, honestly labelled

The previous `walk_forward_folds` output was NOT walk-forward:
it sliced the daily series into 5 chronological chunks and
reported each chunk's net/Sharpe under the name "mean_oos_sharpe",
with no in-sample/out-of-sample structure at all (and no fitting
anywhere, since rules are frozen). Calling that walk-forward was
false labelling. It is kept under `chronological_slices` (and the
legacy `walk_forward_folds` key for test compatibility) and must
be described as holdout slices, never as WF.

Genuine walk-forward added (`walk_forward`, expanding window,
frozen rules, no refit): segments 1..4 each take ALL earlier days
as in-sample and the next segment as out-of-sample; no parameter
is fitted or selected on any window, because the rule was frozen
before the first segment — in-sample is a stability reference,
not a training window, and a refit-based WF would be a different
design and a new trial. WFE is defined per fold as
WFE_net = OOS net / IS net and WFE_sharpe = OOS Sharpe / IS
Sharpe; when an in-sample denominator is ≤ 0 the ratio is
UNDEFINED (None), never clipped or signed away, and the fold is
judged on its OOS net alone and flagged. Aggregate WFE is the
mean of DEFINED folds only, with the defined count reported.
Pass requires mean OOS Sharpe ≥ 0.30, at least folds−2 OOS
segments positive, every defined WFE_net ≥ 0, and at least one
defined WFE. A single chronological split is a HOLDOUT, not WF,
and is labelled as such wherever it appears.

Counterfactuals added, with a hard honesty boundary: best static
style, random router (expected daily series = per-day mean across
candidates, plus a fixed-seed Monte Carlo distribution of the
random-choice lottery), and a shuffled-regime-label placebo (trade
nets fixed, labels shuffled; a regime split whose placebo p sits
near 1 explains nothing). These are computed ONLY when
per-candidate ledgers from the same window/costs are supplied;
with a single ledger they report NOT_COMPUTABLE. A router that
cannot beat both the best static candidate and the random router
on identical data has not demonstrated selection skill. All three
are unit-tested on synthetic controls (hand-computed best/random
nets, a perfectly split regime placebo with p = 0.0).

### 5. Untouched periods and false evidence — BLOCKED ON LINUX, PROVED

Data audit first, before any claim: the clone has no `data/raw/`
(`data/` holds `evidence/`, `fixtures/`, `research/`, `sqlite/`
only). The only bar file is `data/fixtures/XAUUSD_1H_500.csv`:
500 H1 bars, 2020-01-01 to 2020-01-21, opens repeatedly exactly
2000.00 — synthetic-looking, not broker data, wrong timeframe
(H1) for every candidate (M15, M1). `data/research/experiments/`
holds aggregate strategy-screen summaries (DEV/VAL), not bars,
and their DEV/VAL labels prove they were already used for
screening. `data/evidence/longhistory/` holds JSON summaries
only, no bars. "Untouched" is defined relative to ALL prior work:
Jan–Feb 2026 and every window used for screening or tuning are
contaminated and can never serve as OOS for these candidates.

Conclusion: immediate development/OOS PnL testing on Linux is
BLOCKED — there are no usable untouched broker bars locally, and
none were invented or downloaded (no source is authorised).
Synthetic controls were used ONLY to validate tooling maths
(walk-forward, WFE, placebo, cost arithmetic, guard indexing).
The separate future-forward validation requirement is preserved
as a distinct gate this work does NOT satisfy: a pre-chosen
window after 2026-10-30, at least 3 months, no Jan–Feb 2026
overlap, native, safety_on, with unmodified HTML + forensic CSV
+ a measured cost statement. Eliminating false evidence outranks
producing a positive-looking number, and no positive after-cost
edge is claimed anywhere in this branch.

### 6. All ten EntryStyles through one Windows workflow — FIXED (statically), execution PENDING

Evidence of the gap: `MakeTesterPresets.ps1` and
`RunAutomaticTester.ps1` were hardcoded to NINE styles (0–8);
`CompareMT5Reports.ps1` matched only `EntryStyle [0-7]` and
listed eight labels; `BuildTradeForensics.ps1` listed eight
names. Style 9 (M1 scalp) had no preset, no runner slot, and no
comparison/forensic slot — and a forced M15 preset for it would
have failed the EA's OnInit (M1 + 15-minute cap required), so the
previous "one workflow" covered nine styles while the tenth was
manual-only. Worse, the runner's completeness check
(`reports_parsed == names.Count`) compared a maximum of 8
comparison labels against 9 runner names, so it could never
have reached TESTS_FINISHED_REVIEW_REQUIRED.

Fix (this branch): all four scripts now enumerate styles 0–9.
Style 9 presets are M1 (`QTS_M1_M1_SCALP*.set`,
`SignalTimeframe=1`, `MaxPositionMinutes=15`); the runner
verifies those two values for Style 9 and `SignalTimeframe=15`
for styles 0–8, writes `Period=M1` vs `Period=M15` into the
Tester `.ini` files, and runs all ten in one invocation; the
comparison regex now accepts `[0-9]` with ten labels and the
forensics script ten names. Static verification on Linux:
preset/runner/comparison/forensics scripts reviewed line by line,
enum coverage 0–9 asserted against the EA, installer dependency
set asserted (see §1). Native Tester execution for all ten
styles is PENDING Windows — MQL5 is uncompiled here, and no
native result is claimed.

### 7. Preserved fixes (regression-checked, not re-done)

- `edge_gate` BOOTSTRAPS 20000 / 40-trial cap: unchanged; tests
  for 20-trial resolution and 41-trial unresolved+warned pass.
- Unknown `strategy_id` raising: unchanged; Python tests pass.
- Router hardening (3-bar persistence, transition abstention,
  ATR 90th-percentile guard): thresholds unchanged; only the
  guard's reference bar is corrected (§2).
- SMC Style 8 and M1 scalp Style 9: thresholds unchanged; no
  retuning on any return was performed or attempted.
- Preregistration: the frozen document is NOT edited. The guard
  correction and workflow/evaluator repairs are recorded in the
  addendum below, and the repaired router counts as the Style 7
  trial in any repair-branch Windows run.

## Tests run on Linux (repair branch, before patch export)

- `gold_robot` tests: **193 passed** (base 184 + 9 new: ATR-guard
  discriminator, SMC/Scalp/Adaptive installer tests, repaired-2x
  hand arithmetic ×2, walk-forward WFE formula + undefined base,
  counterfactuals, regime placebo). Two failures encountered
  during development were test-side arithmetic errors (a guard
  percentile miscount and an exact-equality assertion on a Monte
  Carlo mean) and were fixed in the tests, not by weakening code.
- Python unknown-strategy + exit-rules tests: **22 passed**,
  run with `PYTHONPATH=src` (the plain invocation's collection
  failure is a pre-existing pyproject quirk, not a code failure).
- Manifest `--check` after every `gold_robot` change (regenerated
  with `update_manifest.py --write`): **90 files valid** at repair
  end (88 at adaptive-branch push + 2 new repair documents).
- Full QTS fast suite: see the final report for the bounded run
  actually performed on this branch (its collection requires
  optional dependencies such as `hypothesis` that are absent in
  this shell, and several files error at collection for that
  reason alone). It is NOT claimed as passed unless the final
  report states a completed count; test-count growth alone is
  never presented as evidence of edge.
- Correction to the previous evaluation document: its "84 files
  valid" line was written before the final manifest regeneration;
  the verified count at the adaptive-branch push was 88, and the
  repair-branch count is stated in the final report. The old
  document's line is corrected in place with a dated note, not
  silently rewritten.

## Trial ledger (repair branch)

- Strategy trials: the repaired router is the Style 7 trial for
  any repair-branch Windows run (it supersedes the adaptive-branch
  router; running both routers as separate claims would count
  both). Styles 0–9 in one Windows run = 10 trials minimum.
- Evaluation-method trials: each robustness perturbation actually
  run (cost multiples, spread model, slippage stress, threshold
  perturbations) is an additional trial and must be added to
  `trials_tested` (cap 40 for edge_gate tail resolution; beyond
  40, DSR/Holm over the ledger-counted list must be used).
- Not trials: installer, preset, runner, comparison, and
  evaluator repairs that change no strategy decision (except the
  guard reference-bar correction, which does change router
  decisions and is counted above as the Style 7 trial).
- Future-forward window: NOT satisfied by this work. It remains a
  separate gate after any tester pass, as a frozen step of its own.

## Costs — MEASURED vs ASSUMED (unchanged)

ASSUMED everywhere in this branch: $10/lot round-turn, $0.10 stop
slippage, tester tick spread. MEASURED (required for any claim):
commission, swap, and spread from a WMMarkets account statement
for XAUUSD@, with statement date and timestamp/price basis
confirmed. Until then the maximum status any candidate can reach
is RESEARCH_POSITIVE_NOT_VALIDATED, never validated.
