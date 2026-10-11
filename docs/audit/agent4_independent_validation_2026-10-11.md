# Agent 4 — independent validation and risk review — 2026-10-11

**Mandate:** QTS multi-agent protocol, Agent 4. Independently review the candidate
strategies and their evidence; challenge positive results; recommend PASS / FAIL /
INSUFFICIENT EVIDENCE against the pre-registered acceptance gates. No modification of
any candidate to improve its result on the holdout. No broker interaction. No orders.

**Candidates under review:** the frozen long-history XAUUSD studies —
intraday M15 `LH-XAUUSD-M15-2026-10-10` (holdout selections `ma_32_128_atr3`,
`donchian_384_192_atr3`, `session_brk_b0`, `rexp_k10_h16`) and daily
`LH-XAUUSD-D1-2026-10-10` (best `ma_20_100_atr3`, `rexp_k10_h3`), whose recorded
verdict is `NO_VALIDATED_EDGE`.

**Tooling:** `scripts/agent4_independent_validation.py` (from-scratch re-implementation of
both studies' engines, families, selection rules, regime labels and statistics; no
`qts.research.longhistory` imports), evidence
`data/evidence/longhistory/agent4_validation.json`, tests
`tests/unit/test_agent4_validation.py`.

---

## Recommendation

**FAIL — no candidate is validated. Do not promote anything beyond RESEARCH.**

1. **Against the pre-registered gates (G1–G7): every group FAILS.** The best groups pass
   2 of 7 (M15 `ma_cross`, `donchian`) or 4 of 7 (daily `ma_cross`,
   `volatility_expansion`). The binding failures are G2 (net at 2× cost), G3
   (walk-forward), G4 (Holm-adjusted significance), G5 (DSR ≥ 0.95) and G7 (regimes).
   Agent 4 re-derived every gate outcome independently; all agree with the recorded
   evidence.
2. **Independently and additionally, Agent 4's own robustness checks produce new
   negative evidence** (chronological instability, cost fragility at 1.5×, negative
   second holdout half, a sign flip under a data-preparation sensitivity for the
   Donchian selection). Details in §4. None of it rescues a candidate; several items
   would have failed a candidate even if the pre-registered gates had passed.
   The deepened round adds: every surviving candidate's holdout net is SMALLER than
   its single best trade (top-1 concentration 1.95×–3.99× of net, §4.7); the daily
   "survivors" repeat the M15 chronological instability (§4.8); unmodeled swap drag
   consumes up to 42 % of the daily Donchian edge; and treating both studies as one
   joint search (N=66) the best OOS DSR anywhere is 0.1165 vs the 0.95 gate (§4.9).
3. **Separately: INSUFFICIENT EVIDENCE for any economic claim.** All costs are
   ASSUMED (6.077 bps round turn at $1,300). No broker cost has been measured
   (`CLAIM_ELIGIBLE_BASES = {MEASURED}`). Even a gate-passing result would earn at most
   `FORWARD_VALIDATION_CANDIDATE_ONLY`, never a claim. This is a standing limitation of
   every number reviewed here, in both directions.

The recorded verdict `NO_VALIDATED_EDGE` is **correct and stands**.

---

## 1. What was independently verified

### 1.1 Full reproduction from pinned sources (deterministic)

| Step | Result |
|---|---|
| `fetch_longhistory_sources.py` | all 4 sources fetched from GitHub at pinned commits, SHA-256 verified, manifest identical except `generated_at` |
| `build_longhistory_dataset.py` | identical quality evidence; 475,286 raw 15m bars; 474,388 research bars after the complete-day filter |
| `run_longhistory_research.py --stage final` (daily) | verdict, gates, and all result fields identical to the committed evidence; the only difference is the `periods_per_year` field, exactly as disclosed in the M15 preregistration §9 |
| `run_longhistory_intraday.py --stage final` (M15) | **byte-identical** to the committed evidence except `generated_at`; bias checks `all_passed=True` reproduced |

### 1.2 Independent re-implementation (the strongest check)

`scripts/agent4_independent_validation.py` re-implements, from the preregistration text
only: the execution engine (next-open fills, stop-vs-range with gap opens, re-entry
block, forced close, calendar rebalance), ALL signal families of BOTH studies (daily:
tsmom, ma_cross, donchian, range expansion, nr7, trend-gated Donchian, RSI(2), Bollinger
control; M15: ma_cross, donchian, range expansion, session breakout), the training-window
selection rule, the cost model, the walk-forward calendar, the regime labels, the block
bootstrap, the Holm correction and the deflated Sharpe ratio (own Bailey–López de Prado
implementation, including a fresh normal-PPF).

**715 of 715 cross-checks matched** against the committed evidence of BOTH studies,
including (M15):

* holdout **selections** per group (identical candidates picked independently);
* holdout net/gross/cost/Sharpe/max-DD/round-turns for all four groups (net within
  0.1 %, turns exact, e.g. `ma_32_128_atr3` +$1,092.55 / Sharpe 0.214 / 1,154 turns);
* 2× and 3× cost stress, zero-cost P&L, and **break-even cost multipliers to three
  decimals** (1.157×, 1.215×, 0.163×);
* all ten walk-forward folds: per-year per-group selections, test-year nets and turns;
* walk-forward composite Sharpes (exact: −0.717, −0.247, −1.030, −6.727);
* buy-and-hold baseline (+$8,795.66, Sharpe 0.860) and the Dukascopy replicate;
* the statistical layer: one-sided bootstrap p-values, sign-randomisation p-values
  (own seeds, agreement within Monte-Carlo noise), Holm-adjusted p-values (1.00 all),
  DSR (0.0003, 0.0042, 0.0, 0.0 — exact to 4 decimals), and the G1–G7 gate arithmetic
  re-derived from the raw evidence fields;
* **independent re-derivation of the G7 regime attribution** (12-month trend ×
  expanding-median volatility labels, rebuilt from scratch): regime bar counts are
  EXACT (e.g. M15 `ma_cross` UP_HIVOL 58,266 / UP_LOWVOL 162,328 / DOWN_HIVOL 22,830 /
  DOWN_LOWVOL 108,456 bars) and per-regime net P&L matches to the cent, for both
  studies;
* **the complete statistical layer of BOTH studies**: one-sided bootstrap p-values and
  block-bootstrap Sharpe intervals (own seeds, agreement within Monte-Carlo noise),
  trade-level sign-randomisation nulls (p-value, observed net and trade count), Holm
  step-down adjustments, the selection criterion itself (training-window Sharpe of
  every selected config), the walk-forward summaries (Sharpe, chained return,
  positive/traded years), the holdout-only DSR with its skew/kurtosis inputs, the
  gates DSR on the OOS composite at the pre-registered trial counts (M15 N=40; daily
  N=26, correctly including the Bollinger falsification control), the trial counts
  themselves, and the G1–G7 gate arithmetic re-derived from the raw evidence fields
  for both studies.

The DAILY study is verified with the same completeness (273 checks): all six group
selections identical (`tsmom_L126`, `ma_20_100_atr3`, `donchian_55_20_atr2`,
`rexp_k10_h3`, `gated_er60_025`, `rsi2_t10_sma200`); holdout metrics exact
(`ma_20_100_atr3` +$530.11 / Sharpe 0.2995 / 14 turns; `rexp_k10_h3` +$673.05 /
0.3867 / 134 turns); 2×/3× cost stresses (+$506.15 / +$381.23 for the two above); all
ten walk-forward folds (162 per-year selection/net/turn checks); buy-and-hold
+$8,795.66 / 0.8648; and the Dukascopy daily replicate, including exact reproduction of
the pre-registered 25 % warm-up rule that marks `tsmom` and `ma_cross`
`NOT_EVALUABLE_INSUFFICIENT_WARMUP` (evaluated groups match to the cent: −$296.65,
+$335.17, −$158.67, +$15.54).

**Conclusion: the evidence is genuine, reproducible and correctly computed.** The
numbers in the reports are what the frozen code actually produces from the pinned data.
The failure below is a failure of the strategies, not of the pipeline.

## 2. Bias audit

| Bias class | Finding |
|---|---|
| **Look-ahead (signals)** | None found. All builders use trailing windows (`shift(1)` channels, rolling/`ewm` indicators, explicit past-only loops). The repo's truncation (causality) checks pass for all 14 M15 configurations at three cut points; Agent 4 re-implemented the same check on its own builders (tests included) and it passes. |
| **Look-ahead (engine)** | None found. Decisions at close `t` fill at open `t+1`; stops fill at the stop or the open on a gap (conservative); entries cannot trade the price that produced the signal. Event order verified by code review and by unit tests on synthetic paths. |
| **Look-ahead (selection)** | None found. Selection uses training windows ending before each test window; the holdout selection froze at 2019-12-31 and ran once. Independently re-derived; identical selections. |
| **Look-ahead (calendar)** | Minor, disclosed, immaterial. `tsmom`'s month-end flag uses the index calendar; a truncated series would differ on the final bar. This affects the daily `tsmom` group only, which failed G1 outright (holdout net −$379). The complete-day filter also uses end-of-day knowledge (a day is complete only when it ends) — a sample-hygiene choice, pre-registered; see §4.5 for its measured effect. |
| **Survivorship / selection of data** | Bounded, disclosed. One instrument (XAUUSD — fixed by project mandate, not chosen after performance screening). One vendor stream for 2004–2025 (BaseMax); the only independent candidate series was rejected by the second-source check, so no price corroboration exists for the research window. The Dukascopy replicate's price basis is unvalidated. These cap the strength of ANY result on this data, positive or negative. |
| **Multiple testing** | Handled. `N_TRIALS = 40` counts every configuration evaluated on the shared 2020–2025 holdout across both cycles. Earlier studies used different series. DSR ≈ 0 for all groups; Agent 4 verified DSR still fails at N=100, so the correction is not the binding constraint — the raw Sharpes are simply too low. |
| **Overfitting** | Present where it matters: the two "surviving" M15 selections are not stable out of their favourable window (§4.1, §4.2). The gate chain (G3/G5) caught this; Agent 4's chronological diagnostics confirm it more starkly than the gates do. |

## 3. Baselines

On the 2020–2025 holdout, buy-and-hold (+$8,795.66, Sharpe 0.860, max DD −21.9 %)
beats every candidate by roughly 8× to 30×. `ma_32_128_atr3` (+$1,092.55) and
`donchian_384_192_atr3` (+$288.09) do not add timing value over holding gold in this
window, and both had negative walk-forward 2010–2019 results (Sharpe −0.717, −0.247;
chained returns −53.6 %, −22.4 % against +34.4 % for buy-and-hold).

## 4. Adversarial diagnostics (frozen selections; no re-tuning)

### 4.1 Chronological stability — the decisive new evidence

One continuous run of each frozen selection over the **full** 2004–2025 research
series (single position path, base costs):

| Selection | Full-run net (2004–2025) | Full-run Sharpe | Max DD | Losing streak |
|---|---:|---:|---:|---|
| `ma_32_128_atr3` | **−$2,704** | −0.03 | −65.2 % | 8 consecutive years (2012–2019) |
| `donchian_384_192_atr3` | +$1,032 (≈0.5 %/yr) | 0.10 | −37.6 % | 2013–2019 mostly negative; 2024 negative |

`ma_32_128_atr3` — the best M15 holdout performer — **loses money over the full
sample**. Its positive holdout is carried by 2020 (+$1,843) and 2006–2011. Per-year
P&L is in the evidence file. This is the overfitting picture the composite gates
summarise; stated per year it is worse.

### 4.2 Holdout halves

| Selection | 2020-01 → 2022-06 | 2022-07 → 2025-02 |
|---|---:|---:|
| `ma_32_128_atr3` | +$1,678 | **−$535** |
| `donchian_384_192_atr3` | +$800 | **−$508** |

Both survivors' holdout positivity comes entirely from the first half. In the most
recent ~2.6 years both lose money net of assumed costs — the opposite of the
stability a promotion requires.

### 4.3 Cost sensitivity — worse execution kills both survivors

Independent cost grid on the holdout (net USD):

| Selection | 0.5× | 1.0× (base) | **1.5×** | 2× | 3× | Break-even |
|---|---:|---:|---:|---:|---:|---:|
| `ma_32_128_atr3` | +5,427 | +1,093 | **−2,024** | −4,266 | −7,036 | 1.157× |
| `donchian_384_192_atr3` | +989 | +288 | **−369** | −983 | −2,098 | 1.215× |

A 1.5× cost assumption — a routine difference between a quoted spread and a realized
one on gold — makes both negative. The margin of safety over the ASSUMED cost is
16–22 %. **Financing is assumed to be zero on top of that**: 661 of 1,154 (ma_cross)
and 154 of 231 (donchian) holdout round turns cross at least one 22:00 rollover
(1,551 and 622 nights held); at a typical −$3.5/lot/night swap this adds ≈ −$282 and
−$114 of unmodeled drag — 26 % and 40 % of the candidates' entire holdout net. Every
unmodeled cost component points the same way: down.

### 4.4 Execution-timing (bar-stamp convention) stress

The preregistration discloses that the source's stamps may mark bar open or close. If
stamps mark closes, every fill is effectively one bar later. Re-running the frozen
selections with a one-bar-extra fill delay: `ma_32_128_atr3` +$1,093 → +$206 (−81 %,
Sharpe 0.214 → 0.096); `donchian_384_192_atr3` +$288 → +$784; the two failed groups
stay negative. No sign flips — the stamp ambiguity neither rescues the failed groups
nor materially strengthens the survivors — but the best candidate's P&L is highly
sensitive to execution timing, which is itself a fragility.

### 4.5 Sample-construction sensitivity (complete-day filter)

Including the 898 partial-day bars (0.19 % of the series) that the pre-registered
complete-day filter excludes, and re-running the frozen selections on the holdout:
`ma_32_128_atr3` +$1,093 → +$1,117 (robust); `donchian_384_192_atr3` +$288 →
**−$77 — a sign flip**. The Donchian selection's entire holdout margin is inside
data-preparation noise. (The filter itself is pre-registered and defensible — partial
sessions cannot fairly signal — but a result that changes sign on 0.19 % of the data
has no margin to stand on.)

### 4.6 Trade-level quality (holdout, independent engine)

| Selection | Turns | Win rate | Expectancy/trade | Profit factor | Avg hold | Stop exits |
|---|---:|---:|---:|---:|---:|---:|
| `ma_32_128_atr3` | 1,154 | 26.6 % | +$0.95 | 1.029 | 83.5 bars | 55 % |
| `donchian_384_192_atr3` | 231 | 21.7 % | +$1.25 | 1.029 | 176 bars | 72 % |

Profit factor 1.03 on both: gross wins exceed gross losses by 3 %. With ASSUMED costs
and no measured financing, a 3 % gross margin is not a durable edge — it is a rounding
error away from zero, which is exactly what the 1.5× cost row shows.

### 4.7 Single-trade concentration — every "edge" is one trade (both studies)

Holdout round turns sorted by net P&L (independent engine, frozen selections):

| Selection (study) | Turns | Holdout net | Best single trade | Top-1 / net |
|---|---:|---:|---:|---:|
| `donchian_384_192_atr3` (M15) | 231 | +$288.09 | +$1,150.77 | **3.99×** |
| `donchian_55_20_atr2` (daily) | 19 | +$160.22 | +$387.03 | **2.42×** |
| `ma_20_100_atr3` (daily) | 14 | +$530.11 | +$1,035.16 | **1.95×** |
| `ma_32_128_atr3` (M15) | 1,154 | +$1,092.55 | +$801.07 | 0.73× |
| `rexp_k10_h3` (daily) | 134 | +$673.05 | +$288.21 | 0.43× |

Remove ONE trade and the daily Donchian, daily MA-cross and M15 Donchian holdout
results all turn **negative**. The two "survivors" with positive net in both holdout
halves and lower concentration (`rexp_k10_h3`) fail the walk-forward and significance
gates instead. An edge that exists only because of one trade is not an edge; it is a
coin flip that has already been flipped.

### 4.8 Daily-study adversarial diagnostics (frozen selections)

**Holdout halves (2020-01→2022-06 / 2022-07→2025-02):**

| Daily selection | Half 1 net | Half 2 net | One-day fill lag | Swap drag @ $3.5/lot/night |
|---|---:|---:|---:|---:|
| `ma_20_100_atr3` | −$656.84 | +$1,289.60 | +$604.87 | −$69.60 |
| `rexp_k10_h3` | +$444.36 | +$218.96 | +$821.23 | −$42.38 |
| `donchian_55_20_atr2` | −$169.85 | +$348.13 | +$234.87 | −$67.88 |
| `tsmom_L126` | −$1,558.30 | +$1,216.12 | −$303.00 | −$254.41 |
| `gated_er60_025` | −$231.30 | −$90.78 | −$330.57 | −$14.38 |
| `rsi2_t10_sma200` | −$372.90 | −$486.57 | −$302.78 | −$31.98 |

Same pattern as M15: the daily MA-cross edge exists only in the second half of the
holdout (−$657 then +$1,290); only `rexp_k10_h3` is positive in both halves, and its
net falls 86 % from 1× to 3× cost (+$673 → +$97) — execution-cost dominated. The
one-day fill lag moves every net by ±14–64 % (no sign flips — daily signals are slow —
but the magnitudes are clearly noise-dominated). Daily-bar positions cross the
overnight roll on EVERY held day while the engine books financing as zero: at the same
−$3.5/lot/night assumption used for M15, the unmodeled swap drag is up to 42 % of the
daily Donchian net (+$160.22 vs −$67.88 drag) and would push `tsmom_L126` further
below zero.

### 4.9 Cross-study multiple testing (Agent-4 addition)

Both studies searched the same instrument (26 daily + 40 M15 configurations). Treated
as one joint search, the multiple-testing burden is N=66. Recomputing the OOS DSR
(WF composite + holdout) at N=66:

| Study | Best OOS DSR at N=66 (group) |
|---|---|
| Daily | 0.1165 (`ma_cross`) |
| M15 | 0.0023 (`donchian`) |

Every group in both studies remains orders of magnitude below the pre-registered
G5 threshold of 0.95 — the multiple-testing conclusion is not close.

## 5. Gate-by-gate (Agent 4 re-derivation, M15 holdout stage)

| Gate | ma_cross | donchian | session_breakout | volatility_expansion |
|---|---|---|---|---|
| G1 holdout net & Sharpe > 0 | PASS | PASS | FAIL | FAIL |
| G2 net > 0 at 2× cost | FAIL | FAIL | FAIL | FAIL |
| G3 WF Sharpe > 0 & ≥6/10 years | FAIL (−0.717; 2/10) | FAIL (−0.247; 4/10) | FAIL | FAIL |
| G4 Holm p ≤ 0.05 | FAIL (1.00) | FAIL (1.00) | FAIL | FAIL |
| G5 DSR ≥ 0.95 | FAIL (0.0003) | FAIL (0.0042) | FAIL (0.0) | FAIL (0.0) |
| G6 ≥100 OOS turns | PASS | PASS | PASS | PASS |
| G7 all regimes, ≥3 positive | FAIL | FAIL | FAIL | FAIL |
| **Passes all** | **no** | **no** | **no** | **no** |

Daily study (gate arithmetic re-derived and verified against the committed evidence):

| Gate | donchian | ma_cross | vol_exp | tsmom | trend_gated | mean_rev |
|---|---|---|---|---|---|---|
| G1 holdout net & Sharpe > 0 | PASS | PASS | PASS | FAIL | FAIL | FAIL |
| G2 net > 0 at 2× cost | PASS | PASS | PASS | FAIL | FAIL | FAIL |
| G3 WF Sharpe > 0 & ≥6/10 years | FAIL (0.142; 5/10) | PASS (0.168; 6/10) | FAIL (0.014; 5/10) | FAIL (−0.071; 3/10) | FAIL (0.536; 2/10) | FAIL (−0.333; 5/10) |
| G4 Holm p ≤ 0.05 | FAIL (1.00) | FAIL (1.00) | FAIL (1.00) | FAIL (1.00) | FAIL (1.00) | FAIL (1.00) |
| G5 DSR ≥ 0.95 | FAIL (0.063) | FAIL (0.117) | FAIL (0.073) | FAIL (0.014) | FAIL (0.020) | FAIL (0.0003) |
| G6 ≥100 OOS turns | FAIL (69) | FAIL (61) | PASS (375) | FAIL (47) | FAIL (12) | PASS (133) |
| G7 all regimes, ≥3 positive | FAIL (2) | PASS (3) | PASS (3) | FAIL (1) | FAIL (1) | FAIL (1) |
| **Passes all** | **no** | **no** | **no** | **no** | **no** | **no** |

Best daily groups pass 4 of 7 (`ma_cross`, `volatility_expansion`), blocked by
G4/G5 and — for `rexp_k10_h3` — G3; `ma_20_100_atr3` additionally fails G6 power
(61 OOS turns in ~15 years).

## 6. What would change the verdict

1. **Measured all-in round-turn costs and M15 bar depth** from the Windows MT5 DEMO
   terminal (`qts data mt5-depth`, `qts demo cost-check --record` — read-only). These
   are the decisive inputs: the survivors' break-even multiples (1.16×, 1.22×) mean
   measured costs could only confirm the failure or (if materially cheaper) justify a
   **new preregistration** on fresh data.
2. A licensed, independent long-history price series (the second-source check rejected
   every current candidate).
3. Fresh out-of-sample data beyond the reused 2020–2025 window, under a new
   preregistration, for the Donchian/MA families only if (1) and (2) land.

None of these change the current verdict: FAIL.

## 7. Boundaries observed

- No strategy definition, parameter, gate threshold, or evidence file of the frozen
  studies was modified. The 2020–2025 holdout was used only to evaluate frozen
  selections and run diagnostics; nothing was re-selected or re-tuned on it.
- No broker connection, no orders, no DEMO or LIVE state change. `LIVE_LOCKED`,
  `REAL_CAPITAL_EXPOSURE = 0`, risk limits and authorization policies unchanged.
- New files: this report, `scripts/agent4_independent_validation.py`,
  `data/evidence/longhistory/agent4_validation.json`,
  `tests/unit/test_agent4_validation.py`. The committed evidence files of the frozen
  studies were re-generated during reproduction and restored byte-identical (verified
  by SHA-256); nothing in `data/evidence/longhistory/` belonging to the prior cycles
  was altered.
- **One out-of-mandate repair, disclosed: `tests/test_conftest_git_status.py` was
  fixed.** The test failed on the pristine baseline commit `055f1ca` (reproduced
  deterministically with `pytest tests/integration tests/test_conftest_git_status.py`
  and under the full `pytest -n auto` suite): its bare `import conftest` binds to
  `tests/integration/conftest.py` whenever a worker collects that directory first,
  because the integration conftest then occupies the top-level module name. The fix
  exercises `_git_status_paths()` in a fresh subprocess where only `tests/` is on
  `sys.path`, so the import is unambiguous. No product code, guard semantics or
  assertion strength was changed.

## 8. Verification suite (this branch)

| Check | Result |
|---|---|
| `ruff check src/ tests/` (+ the new script and test) | pass |
| `mypy src` | 182 files, no issues |
| `bandit -q -r src` | pass |
| `pytest` (fast suite) | **1477 passed, 0 failed** (347 honest skips) |
| `pytest --run-integration --run-research` | **1820 passed, 0 failed** (4 skips) |
| `node --check` over `src/qts/desktop/ui/js` | pass |
| `npm test` (UI) | 48 pass, 0 fail |

For the record: the pristine baseline commit `055f1ca` fails
`tests/test_conftest_git_status.py` in the same environment (see §7); the suite
above is green only after the disclosed test repair.

## 9. Reproduce

```bash
python scripts/fetch_longhistory_sources.py        # pinned, SHA-256-verified (github.com only)
python scripts/build_longhistory_dataset.py        # deterministic
python scripts/agent4_independent_validation.py    # 715/715 cross-checks + diagnostics
pytest tests/unit/test_agent4_validation.py -q     # engine invariants on synthetic data
```

## 10. Not claimed

No edge. No profitability claim of any kind. This review confirms a negative result
and adds independent evidence for it. `NO_VALIDATED_EDGE` stands.
