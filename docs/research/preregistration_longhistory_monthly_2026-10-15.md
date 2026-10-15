# Preregistration — XAUUSD Monthly Long-History (Trend / USD-Veto / USD-Agreement) Research

**ID:** `LH-XAUUSD-MON-2026-10-15`
**Status:** every value, window, threshold and gate below was frozen in
`src/qts/research/longhistory/monthly_protocol.py` (with the candidate builders
in `monthly_signals.py`) **before any walk-forward, evaluation-window or
replicate result of this cycle existed**, and none changed afterwards. The
discovery search that selected the candidate set (§5) was completed on data
ending 1989 only, i.e. strictly before the frozen windows, and its full
22-configuration outcome is recorded in §5 so nothing is hidden. Order of
operations: (1) discovery on ≤1989 slices, (2) protocol/builder code freeze,
(3) dataset build + quality evidence, (4) `--stage dev` pipeline debug
(walk-forward folds 1990–1999 only — no evaluation window, no replicate),
output committed as `data/evidence/longhistory/monthly_research_dev.json`;
this document was written **after** that dev run and is committed before
`--stage final`. No frozen value was touched by the dev run, and the dev stage
by design cannot evaluate the evaluation window — but its walk-forward numbers
are visible in the committed evidence, and because G3 is computed from those
same walk-forward folds, the walk-forward component of the G3 outcome is
knowable before final while the evaluation-window component is not. Both facts
are stated here rather than papered over. Runner:
`scripts/run_longhistory_monthly.py --stage dev|final`. Data pipeline:
`scripts/fetch_longhistory_monthly_sources.py` (pinned commits + SHA-256),
`scripts/build_longhistory_monthly_dataset.py` (quality gates + evidence).
**Parent cycles:** `LH-XAUUSD-D1-2026-10-10`, `LH-XAUUSD-M15-2026-10-10`,
`LH-XAUUSD-SES-2026-10-14`, `LH-XAUUSD-REV-2026-10-14`
(`preregistration_longhistory_2026-10-10.md`,
`preregistration_longhistory_m15_2026-10-10.md`,
`preregistration_longhistory_seasonal_2026-10-14.md`,
`preregistration_longhistory_reversal_2026-10-14.md`, and the accounting
addendum `preregistration_longhistory_fixed_units_v2_2026-10-14.md`). Engine
(`fixed_units.v2`), costs, selection rule and gate arithmetic are inherited
unchanged except where §9 says otherwise.

This document fixes the question, candidates, windows, selection rule, gates
and verdict rule before this cycle's evaluation results exist. A failed gate
is a failed gate. Nothing here may be re-tuned against the holdout or the
replicate. If a value must change, the change is a new experiment with a new
ID.

## 1. Question

Does any simple, causal, **monthly** XAUUSD rule — time-series momentum on
gold, momentum with a dollar-strength veto, or gold/dollar trend agreement —
produce positive net performance after ASSUMED costs that survives the
inherited chain of tests: walk-forward selection on 1990–1999 out-of-sample
years, the 2000-01 → 2026-09 evaluation window with training-only selection,
2× and 3× cost stresses, a financing-charged cost regime, break-even
robustness, multiple-testing correction over every configuration evaluated on
this research series, and a mechanical regime split?

The frequency is genuinely new: every prior long-history cycle ran daily or
intraday bars on the 2004–2025 BaseMax stream; none tested monthly decisions,
and none tested the World Bank / Fed public monthly series. The USD-index
conditioning family (veto / agreement) is new this cycle as well.

This is a **research** question. A pass earns forward validation, not a
claim. Every gating cost in this cycle is ASSUMED, so no economic-edge claim
can result.

## 2. Data and windows

| Role | Source | Window (UTC, month-end stamps) | Size |
|---|---|---|---|
| Research (discovery ≤1989, walk-forward, evaluation window) | World Bank Pink Sheet monthly gold USD/oz (`datasets/gold-prices` @ `f6e97610178379ef8db280702fcaa3ec0875c5c2`, PDDL) + Fed H.10 daily FX (`datasets/exchange-rates` @ `c023dd8b8f879610641a7391c0394c3bbb42d0f7`, PDDL) | 1973-01-31 → 2026-09-30 | 645 months |
| Replicate (informational, final stage only) | BaseMax XAUUSD 15-minute bars aggregated to monthly OHLC (same pinned stream as the parent cycles) | 2004-06 → 2025-02 | 249 months |

**Price series.** Research gold is the monthly average price
(`open = high = low = close = monthly average`), month-end stamped. The USD
index is the equal-weight basket `AU/CA/DK/JP/NZ/SE/CH/UK`, each series taken
**as published** (currency per USD), as `exp(mean(log(rate/first)))` of the
basket; monthly value = last daily observation of the month. The published
README's sign-convention claim is wrong — conventions were probed empirically
against known dollar-cycle points before any use (probe table in
`monthly_data_quality.json`, e.g. 1985-03 12-month +27.9% dollar peak). Quality evidence
(`data/evidence/longhistory/monthly_data_quality.json`): 645 contiguous months,
zero missing, month-end basket coverage asserted ≥ 6 of 8 currencies on every
month-end across the full FX span, end-of-month FX lag ≤ 7 days across the
research window, `o=h=l=c` validation on all research rows, and cross-source
agreement with the BaseMax monthly closes over the shared 2004–2025 span of
**corr = 0.997771** (Pearson on closes over 249 overlap months; a level
comparison, stated as an information check, not an execution-price claim).
Single-quantity months and pre-1973 months are
excluded by the build gates; gaps are never interpolated.

**Execution model (monthly, frozen).** A decision at the close of month `t`
(the published month-`t` average) fills at month `t+1`'s published average —
a preregistered TWAP into the next monthly average, the only execution the
monthly-average series supports. A month with no position change earns
`old_pos × (avg_t − avg_{t−1})`. The replicate uses the parent engine's
convention unchanged: real monthly OHLC with next-open fills — an independent
quote stream **and** an independent execution convention versus the research
TWAP convention. Decisions use only data published at or before month `t`;
the builders' expanding statistics are causal (verified by truncation checks).

**Sizing, risk, accounting (inherited `fixed_units.v2`).** Vol-target size
`0.10 / (12-month realised vol × √12)`, capped at 1.0× equity; target
∈ {−1, 0, 1}; units sized from notional before fill cost
(`held = frac × E / entry_price`); fixed signed ounces until an actual
entry/exit/rebalance; fill costs charged on `|Δposition|`; no protective
stops; no leverage beyond the 1.0 cap; initial equity USD 10,000; windows
self-contained with forced close at the end; accounting identity tested.
Where the 12-month vol is undefined (warm-up or a degenerate zero-variance
window) the target is NaN-masked to a no-change decision — no close-without
re-entry churn. `o=h=l=c` bars are valid input to the engine.

**Holdout reuse (disclosed, material).** The 2000–2026 evaluation window
calendar-overlaps the parent cycles' 2020–2025 evaluation window, which was
already evaluated for *other* families on other bars; the replicate window
sits inside the research calendar (it is a source replication, not a fresh
time window). Neither is a fresh sample. The protections this cycle adds: the
monthly frequency and the USD-veto/agreement families were never evaluated on
either window before; every configuration evaluated on this research series
counts toward the deflation (`N_TRIALS = 72`, §7); earlier runs of the
discovery with a buggy USD index are counted once inside those 72 (their
numbers were discarded, their trial slots retained); and the verdict cannot
exceed `FORWARD_VALIDATION_CANDIDATE_ONLY` with `claim = none` in any case
(costs ASSUMED).

## 3. Stage windows (frozen)

| Stage | Window | Purpose |
|---|---|---|
| Discovery (done, pre-freeze) | selection 1973–1983 / test 1984–1989, disjoint from everything below | Candidate selection only (§5) |
| Walk-forward (dev) | expanding selection from 1973, test years **1990–1999** (one test year per fold) | Pipeline debug at `--stage dev`; G3 input at final |
| Evaluation window (holdout) | selection through **1999-12-31**, single run **2000-01 → 2026-09** | Gates G1, G2, G4, G5, G6, G7, G8, G9 |
| Replicate | 2004-06 → 2025-02 on BaseMax monthly OHLC, frozen selections with research-series history prefix | Informational, never gating |

`RESEARCH_END = 2026-09-30`, `DEV_END = 1999-12-31`,
`HOLDOUT_START = 2000-01-01`, `WF_TEST_YEARS = 1990..1999`.

**Selection rule (inherited):** within each group, the candidate with the
highest training net Sharpe at base costs, requiring ≥ 20 training round
turns; ties go to the earlier candidate in the frozen registry order.

## 4. Costs (ASSUMED)

Inherited gating base: `CostModel(spread_bps=3, slippage_bps=1 per side,
commission=$7 per lot per side)` — about 6.1 bps round turn at $1,300/oz —
plus the pre-declared 2× and 3× stresses and the break-even bisection.

**New this cycle (frozen):**

1. **Financing-charged regime (gating, G9):** `COST_FINANCING = COST_BASE +
   0.25 bps of notional per calendar day`, charged symmetrically on long and
   short positions overnight — about $3.5 per lot per night at $1,400/oz.
   `ASSUMED`, deliberately conservative, never used for selection. The
   evaluation window must stay net-positive under this regime (G9).
2. **Cost-regime diagnostics (non-gating):** the four pre-declared regimes
   from `docs/research/m15_cost_sensitivity_2026-10-11.md` (canonical
   `$0.30+$0.10+$0`; WM measured median `$0.24+$0.10+$0` MIXED; WM median +
   ECN `$0.24+$0.10+$7`; WM reopen stress `$0.39+$0.15+$7`), reported for the
   evaluation window, never used for selection or gates.
3. **Overnight swap diagnostic (non-gating):** 22:00-UTC rollover crossings
   counted strictly inside each evaluation-window trade; drag = crossings ×
   `$3.5 per lot per night` (`ASSUMED`) × lots implied by the entry fraction
   at initial equity. Reported per group; monthly positions cross many
   rollovers, so this is a disclosed drag estimate, not a claim of zero.

## 5. Candidate grid and discovery record (7 configurations; all counted)

Builders are frozen in `monthly_signals.py`. `Δₗx` = log monthly return;
lookback `L` months; vol window 12 months.

| Group | Candidate | Definition |
|---|---|---|
| `gold_trend` | `m_tsmom_6` | `target = sign(Δₗ gold over 6 months)` |
| `gold_trend` | `m_tsmom_12` | `target = sign(Δₗ gold over 12 months)` |
| `usd_veto` | `m_usdveto_6_12` | `+1` if gold 6m trend > 0; `−1` if gold 6m trend < 0 **and** 12m USD index change > 0 (dollar strengthening); else `0`. (Short only when the dollar confirms; long only on positive gold trend; flat otherwise.) |
| `usd_veto` | `m_usdveto_12_12` | Same rule with a 12-month gold lookback. |
| `usd_agreement` | `m_agree_6_12` | `G = sign(Δₗ gold 6m)`, `U = −sign(Δₗ usd 12m)`; `target = sign(G+U)` when `G·U ≥ 0`, else `0`. Trades only when gold and the dollar agree (gold up / dollar down → long; gold down / dollar up → short). |
| `usd_agreement` | `m_agree_12_12` | Same rule with a 12-month gold lookback. |
| (control) | `m_boll20_2` | CONTROL (group `monthly_reversion`), never a candidate: 20-month 2σ Bollinger mean-reversion — buy below the lower band, sell above the upper band, exit at the mean. Non-gating; counts as a trial. |

**Discovery record (frozen, complete).** All 22 monthly configurations
evaluated during discovery (on ≤1989 slices only) are counted in
`N_TRIALS`; six were frozen as candidates, the rest are listed here so the
deflation cannot be questioned. Selection 1973–1983 / test 1984–1989,
selection/test annualised Sharpe at ~7–9 bps round-turn costs:

| Config | Sel | Test | Disposition |
|---|---|---|---|
| `usdveto_6_12` | 0.826 | 0.533 | frozen |
| `usdveto_12_12` | 0.744 | 0.512 | frozen |
| `agree_6_12` | 0.729 | 0.541 | frozen |
| `agree_12_12` | 0.696 | 0.533 | frozen |
| `tsmom_6` | 0.729 | 0.603 | frozen |
| `tsmom_12` | 0.650 | 0.566 | frozen |
| `agree_6_6` | — | 0.537 | counted, not frozen |
| `agree_12_6` | — | 0.504 | counted, not frozen |
| `agree_6_3` / `agree_12_3` | — | 0.377 / 0.332 | counted, not frozen |
| `usdveto_6_6` / `usdveto_12_6` | — | 0.666 / 0.571 | counted, not frozen |
| `usdmom_3/6/12/24` | — | −0.215 / 0.262 / 0.271 / 0.576 | evaluated, **dropped** (weaker/absent edge) |
| `longflat_6` / `longflat_12` | — | 0.546 / 0.778 | evaluated, **dropped** (long-and-flat subsumed by trend tests; not frozen) |
| `tsmom_3` / `tsmom_24` | — | 0.367 / 0.282 | counted, not frozen |
| `rev_6` | — | −0.739 | counted, not frozen |
| `boll20_2` (control) | — | −0.398 | control; negative on selection ✓ |

**Grid size:** 6 candidates + 1 control = 7 configurations registered in this
cycle. `N_TRIALS_THIS_CYCLE = 22` — every configuration evaluated in discovery
on this research series (§5 table) counts, not only the seven registered;
`N_TRIALS = 50 + 22 = 72` — the parent count through `LH-XAUUSD-M15-REV-
2026-10-14` (26 daily + 14 M15 + 7 seasonal + 3 reversal = 50) plus the 22,
because this cycle's evaluation window overlaps the parent holdout calendar.
The Deflated Sharpe Ratio uses `N = 72`. Holm's step-down runs across this
cycle's three gating groups (m=3).
Trial-count bookkeeping lives in this document and
`monthly_protocol.N_TRIALS`; `docs/experiment_ledger.md` is a generated
aggregate and is not hand-edited (ARCH-020/021 precedent).

## 6. Statistics and gates

Inherited: annualised Sharpe on monthly returns including flat months
(`√12`); circular block bootstrap (block 20, seed 11) one-sided p-values
(2,000 draws) with Holm step-down across the three groups; DSR with
`N_TRIALS = 72` on combined out-of-sample returns (walk-forward 1990–1999 +
evaluation window); trade-level sign-randomisation null; causal regime labels
(24-month trend sign × 12-month realised vol vs its expanding median, in
monthly units).

| Gate | Test |
|---|---|
| G1 | Evaluation-window net P&L > 0 **and** Sharpe > 0 at base cost |
| G2 | Evaluation-window net > 0 at 2× cost |
| G3 | Walk-forward 1990–1999 Sharpe > 0 **and** ≥ 6 of 10 test years net positive |
| G4 | Holm-adjusted p ≤ 0.05 across this cycle's three groups |
| G5 | DSR ≥ 0.95 with `N = 72` on combined out-of-sample returns |
| G6 | ≥ 100 out-of-sample round turns (walk-forward + evaluation window); ~5–6 round turns per year are expected on the frozen grid |
| G7 | Net positive in ≥ 3 of 4 regimes, all four present out-of-sample |
| G8 | Evaluation-window **break-even cost multiplier ≥ 2.0** (inherited from the seasonal cycle; can only fail a candidate) |
| **G9 (new, this cycle)** | Evaluation-window net P&L **> 0 under `COST_FINANCING`** (base + 0.25 bps/day symmetric, §4). A strategy whose edge dies when overnight carry is charged is not robust. Can only fail a candidate. |

**Verdict rule.** Any group passes G1–G9 →
`FORWARD_VALIDATION_CANDIDATE_ONLY`; the claim is still `none` (costs
ASSUMED; the evaluation window is reused — both stated in the verdict).
No group passes → `NO_VALIDATED_EDGE`, naming the failing gates. Nothing
here places orders or changes DEMO/LIVE state, risk limits, or authorisation.

## 7. Minimum effect, sample and risk thresholds (pre-stated)

- **Economic:** positive net after base costs (G1), at 2× costs (G2),
  break-even ≥ 2× (G8), and positive with financing charged (G9). A candidate
  whose zero-cost P&L is positive but base-cost P&L ≤ 0 is rejected as
  cost-incapable; negative even at zero cost is rejected outright.
- **Sample:** ≥ 100 OOS round turns (G6); ≥ 20 training turns for selection
  eligibility (inherited); the research window is 645 months with ~5–6 round
  turns per year expected, so G6 is reachable only if the frozen candidates
  actually trade (no-trade folds report `cid = None`).
- **Risk:** no gate may be evaluated on a group whose regime coverage is
  incomplete (G7); evaluation-window max drawdown and exposure are reported
  for every group (reporting requirement, not a gate).
- **Multiplicity:** 72 trials deflation + Holm across groups (G4/G5).

## 8. What would falsify the family

- Any group failing any of G1–G9 → the group's mechanism does not produce a
  tradable edge here, and the precise failing gate names where.
- The Bollinger control outperforming an aligned candidate → mean reversion,
  not trend/veto/agreement structure, is the operative factor.
- USD-veto or agreement selections flipping between `flat` and `long` across
  walk-forward folds (reported per fold) → non-stationarity, reported even
  if a gate passes.
- Evaluation-window net turning negative only under `COST_FINANCING` → the
  edge is an overnight-carry artefact (G9's purpose).

## 9. Deviations from the parent cycles (all pre-declared)

1. Monthly frequency, new dataset family (World Bank + Fed public series),
   and three new candidate families; everything else inherited by reference.
2. TWAP-into-next-month-average execution on the research series (§2), with
   the replicate kept on the engine's real-OHLC next-open convention.
3. New gating cost regime and gate G9 (financing charged, §4/§6).
4. Replicate plans use a research-series history prefix (builders fit
   expanding statistics); the run window itself is replicate-only.
5. Evaluation window starts 2000-01 (not the parent 2020-01) because the
   monthly series reaches back to 1973; overlap with parent windows
   disclosed in §2.
6. `N_TRIALS = 72` counts this cycle's 22 discovery configurations on top of
   the inherited 50 (§5). Trial count not hand-edited (ARCH-020/021).
7. Preregistration text committed after the dev-stage pipeline run (§Status),
   with the frozen protocol code preceding that run — disclosed, not
   concealed.

## 10. Out-of-scope (blocked, not attempted here)

- **Measured costs:** commission/spread/slippage/financing measurement still
  requires the Windows MT5 DEMO terminal (`qts demo cost-check --record`),
  unavailable in this sandbox. Costs remain ASSUMED; no claim is eligible.
- **DXY / real yields / cross-asset conditioning:** no verified monthly
  history in the repository beyond the Fed H.10 basket USD index.
- **Finer-than-monthly structure on this data:** the World Bank series is a
  monthly average; intraday/daily questions stay with the parent cycles.
- Any parameter sweep on the 2000–2026 evaluation window: none may follow
  this freeze; re-tuning after seeing final results requires a new ID.
