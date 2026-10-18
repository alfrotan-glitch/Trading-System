# QTS Long-History XAUUSD Edge Research — Expert Handbook

Date: 2026-10-17. Status: **RESEARCH-ONLY — `NO_VALIDATED_EDGE`** — LIVE LOCKED,
`REAL_CAPITAL_EXPOSURE = 0`, costs **ASSUMED** (not MEASURED). This handbook
consolidates everything the 2026-10-17 edge hunt established so the knowledge
survives independently of any single cycle document. It promotes nothing.

---

## 1. Mandate and governance

- Objective: find the best XAUUSD trading edge that passes the repository's own
  frozen validation gates (G1–G9 lineage) — a profitable-looking backtest is
  not success.
- No gate may be weakened, no candidate re-tuned on a reused holdout, and no
  ASSUMED-cost result may be presented as a claim. Reused windows must be
  disclosed and counted in the DSR trial count.
- Claim eligibility requires MEASURED costs (Windows MT5 demo terminal), which
  remain unavailable in this environment.

Gates (frozen thresholds): G1 holdout profitable; G2 2×/3× cost stress
profitable; G3 walk-forward composite Sharpe > 0 with ≥6/10 positive years;
G4 Holm-adjusted significance; G5 deflated Sharpe ratio ≥ 0.95 at the
cumulative trial count; G6 ≥100 out-of-sample round turns; G7 regime stability
(incl. DOWN regimes); G8 break-even cost ≥ 2×; G9 financing-charged net > 0.

## 2. Data assets

- **Monthly (primary):** World Bank Pink Sheet gold monthly average price +
  Fed H.10 equal-weight 8-currency USD index, 645 months 1973-01→2026-09
  (`data/raw/longhistory/processed/xauusd_worldbank_monthly_utc_197301_202609.csv`;
  o=h=l=c=monthly average by construction). Cross-source correlation vs BaseMax
  0.997771 over 249 common months. Rebuild:
  `scripts/fetch_longhistory_monthly_sources.py` + `build_longhistory_monthly_dataset.py`.
- **Weekly:** BaseMax XAUUSD weekly bars + Fed H.10 daily USD index sampled
  W-FRI (`xauusd_basemax_weekly_*`, research window 2004-06→2025-02).
- **Replicates:** BaseMax monthly (249 rows) and Dukascopy daily files in the
  same processed directory; monthly cycles use the history-prefix replicate
  (`replicate_with_context`) so warm-up/USD context matches.
- Provenance detail: `docs/research/longhistory_data_provenance_2026-10-10.md`.

## 3. Engine and frozen conventions (`fixed_units.v2`)

- Fixed signed ounces between fills; fill costs charged on traded notional;
  decision at month *t* close fills at month *t+1*'s average; window runs start
  flat and force-close at the final average.
- Costs (ASSUMED): spread 3 bps + slippage 1 bp per side, + $7/lot/side
  (1 lot = 100 oz); G9 financing at +0.25 bps/day.
- Sizing: fraction = clip(0.10 / (12-month log-return vol × √12), max 1.0) of
  equity, rebalanced monthly (10% annualised vol target, no leverage).
- Engine: `src/qts/research/longhistory/{engine,runner,stats,ensemble_signals,forward}.py`.
  Old pre-v2 artifacts are historical diagnostics only (ARCH-060).

## 4. Trial ledger (all cycles preregistered, freeze-before-final)

| Cycle | Protocol | Discovery partition | Cum. N | Verdict |
|---|---|---|---|---|
| ENS 2026-10-17 | `LH-XAUUSD-ENS-2026-10-17` | ≤1989 monthly (76 cfg) | 149 | NO_VALIDATED_EDGE |
| W1 2026-10-17 | `LH-XAUUSD-W1-2026-10-17` | 2004-2009 weekly (43 cfg) | 193 | NO_VALIDATED_EDGE |
| HYB 2026-10-17 | `LH-XAUUSD-HYB-2026-10-17` | ≤1989 slow-hybrid (43 cfg) | 237 | NO_VALIDATED_EDGE |
| WHYB 2026-10-17 | `LH-XAUUSD-WHYB-2026-10-17` | 2004-2009 weekly-hybrid (24 cfg) | 262 | NO_VALIDATED_EDGE |
| VOLM 2026-10-17 | `LH-XAUUSD-VOLM-2026-10-17` | ≤1989 (22 cfg incl. brakes) | 285 | NO_VALIDATED_EDGE |
| Wave-6 (discovery only) | — | ≤1989 (22 cfg) | 307 | no cycle frozen |
| Wave-7 (discovery only) | — | ≤1989 (20 cfg) | 327 | no cycle frozen |
| Wave-8 (discovery only) | — | ≤1989 (10 cfg) | 337 | no cycle frozen |
| Wave-9 (discovery only) | — | ≤1989 (6 cfg) | 343 | no cycle frozen |
| Wave-10 (discovery + dev only) | — | ≤1989 + 1990–99 dev (12 cfg: US 10Y yield & real rate) | 355 | no cycle frozen |

The next gated cycle must use **N = 355** in its DSR. Per-cycle evidence:
`data/evidence/longhistory/{ensemble,weekly,hybrid,weekly_hybrid,volmanaged}_research_final.json`;
Wave-10 discovery/dev evidence: `data/evidence/longhistory/wave10_treasury_real_rate.json`;
preregistrations and results under `docs/research/`.

## 5. The champions (best candidates; still unvalidated)

**`ts9_lo`** — 9-month time-series momentum, long-or-flat, monthly.
Evaluation 2000-01→2026-09 (+$10,000 start): net **+$70,989**, Sharpe **0.837**
(bootstrap CI [0.32, 1.30]), max DD −31.0%, 16 round turns, break-even > 50×,
Holm p ≈ 0.01, financing-charged +$59,931, **DSR 0.945 at N=237** (gate 0.95 —
missed by 0.005). Fails G3 (1990s leg), G5, G6 (16 turns, structural at
≈0.6 turns/yr for a 9-month trend), G7 (flat in DOWN regimes earns nothing).

**`veto9`** — 9-month trend, shorts only while the USD index rose over 12 m.
Evaluation: net **+$49,897**, Sharpe **0.662**, DSR 0.752 @N=237, financing
+$39,392, 26 round turns (45 OOS incl. walk-forward), 6/9 gates. Only candidate
positive standalone in **every decade** (Sharpe 0.750 / 0.268 / 0.752 / 0.192 /
1.098 for 1973-89 / 1990s / 2000s / 2010s / 2020-26); `ts9_lo` decades:
0.711 / −0.253 / 0.936 / 0.314 / 1.244.

Financing fragility (audit F-1, 2026-10-17): both champions' G9 pass rests
on the assumed symmetric 0.25 bps/day. Re-costed break-evens are ≈3.3
(`ts9_lo`) and ≈2.4 (`veto9`) bps/day — at a broker whose measured
`swap_long` exceeds that, the financing-charged result fails G9. Never
quote the financing-charged nets without the broker's measured swap
(`docs/audit/independent_research_audit_2026-10-17.md` §4,
`data/evidence/longhistory/champion_financing_sensitivity.json`).

Robustness (post-hoc, disclosed, non-gating): long-only lookback plateau
6–15 m evaluation Sharpe 0.79–0.96 (9 m is interior, not a spike; the higher
10–11 m scores were explicitly **not** adopted); veto plateau positive in the
1990s at every lookback 7–15. Buy-and-hold still beats both on raw evaluation
return (+$142,032, Sharpe 0.850) — the champions are risk-shaped, not
return-maximal.

Fragility audit (2026-10-17, independent verifier conventions, post-hoc):
delaying fills by 1–2 extra months does **not** hurt — `ts9_lo` Sharpe
0.836 → 0.847/0.851, `veto9` 0.662 → 0.671/0.674 (the edge is slow-moving,
not a fill-timing artifact). Evaluation-start jitter 2000→2010 keeps
`ts9_lo` Sharpe in 0.79–0.88 and `veto9` in 0.62–0.72; drawdowns are
start-invariant (−0.310 / −0.360, set by the 2011–15 episode). The headline
numbers are not artifacts of the window start or the execution convention.

Data-definition audit (2026-10-17, descriptive): on BaseMax broker daily
data aggregated to **month-end closes** (2004-06→2025-02, 249 months),
`ts9_lo` nets +$24,066 / Sharpe 0.681 and `veto9` +$14,850 / 0.462, vs
+$31,376 / 0.762 and +$22,210 / 0.573 on Pink Sheet monthly averages over
the same window (B&H 0.667 vs 0.813). Champions survive a different source
and bar convention with ~80–90% Sharpe retention and higher turnover
(18/31 vs 14/23 turns); no sign flips. Note: `datasets/gold-prices` is the
**same** World Bank upstream (it is this repo's own pinned gold source),
not an independent check — do not cite it as one.

**Forward status (frozen, paper only):** both champions LONG since 2023-02,
target 1.0, size 0.4728 as of 2026-09-30 (gold 4319.0). Protocol
`docs/research/forward_validation_champions_2026-10-17.md`; state
`data/evidence/longhistory/forward_champions_state.json`.

## 6. Independent verification (new, 2026-10-17)

`scripts/verify_champions_independent.py` — a stdlib+numpy reimplementation
sharing no code with `qts.research.longhistory` — reproduces both champions on
the evaluation window: `ts9_lo` net $70,988.62 vs $70,989 (dev 0.001%, Sharpe
dev 0.0005), `veto9` net $49,897.43 vs $49,897 (dev 0.001%, Sharpe dev 0.0002),
drawdowns and segment counts identical. Verdict **AGREE**
(`data/evidence/longhistory/champion_independent_verification.json`).
Scope note: this verifies the engine's arithmetic under the frozen
conventions; it does not validate the conventions, the ASSUMED costs, or the
edge itself.

Trial-ledger audit (2026-10-17, scripted): recomputing `N_TRIALS` from the
protocol modules reproduces the full chain 26 (daily) → 40 → 47 → 50 → 72
(monthly) → 149 → 193 → 237 → 262 → 285, and every committed final's
recorded DSR `num_trials` matches its cycle (149/193/237/262/285; monthly
72). The Waves 6–8 increments (+22/+20/+10 → 337) rest on the ARCH prose
ledger and their discovery outputs. The DSR denominators are not
hand-edited.

## 7. Falsified branches — do not retry

- **Weekly translations** of the champion mechanism (W1, WHYB): twice weak
  (best Sharpe 0.562, DSR ≤ 0.144). The mechanism is monthly-horizon-specific.
- **Faster ensembles / blends:** dilute Sharpe (equal-sleeve blend 0.737,
  negative 1990s) and DSR. More signals ≠ better.
- **Fast (3/6 m) volatility sizing (VOLM):** improves ≤1989 discovery, dilutes
  evaluation DSR (0.917/0.657 vs champions 0.945/0.752), drawdown unchanged.
  12 m sizing stands. Drawdown brakes rejected on discovery (they exit gold's
  recoveries).
- **Hysteresis bands (Wave-6):** ±2% identical to champions; wider is
  monotonically worse. **Basket-relative trend** (`close/usd`): selects weaker
  than plain trend (selection Sharpe 0.66–0.75).
- **Volatility-regime gate (Wave-7):** holding champions only when 12 m vol is
  below its trailing quantile is neutral (selection Sharpe 0.826 vs 0.828).
- **Extension (anti-chase) gate (Wave-7):** flat when price > (1+x)·12 m mean
  helps 1973–78 and 1984–89 but forfeits the 1979–81 blow-off (episode net
  +$6,712 → +$470 for `ts9_lo`); no plateau across x∈{10,15,20,25}% (selection
  Sharpe 0.48/0.88/0.76/0.92) — regime-dependent, rejected.
- **Extreme mean reversion / USD-momentum primary (Wave-7):** monthly
  contrarian-at-extremes is negative-to-flat; USD-momentum alone (0.78/0.33
  selection/check) trails the gold-trend champions.
- **Real-price (CPI-deflated) trend (Wave-8):** trend on CPI-deflated gold
  (BLS CPI-U NSA via `datasets/cpi-us@dceeb87`, PDDL; CPI lagged 1 m for
  release timing) peaks at 9 m exactly like nominal — the same edge with a
  deflated ruler. The LS form trails `veto9` on selection (0.767 vs 0.828);
  its check-window strength concentrates in the single 1982–89 disinflation
  regime (SR 0.55 vs 0.32; the real bear ran 1980–2001, mostly outside the
  check window). `real9_lo` beats `ts9_lo` only +0.04/+0.08 — noise. The
  real-extremity (valuation) gate is harmful (selection 0.51/0.58 vs bases
  0.78/0.83). Not a distinct validated mechanism; do not re-run deflation
  variants without a new idea.
- **Inflation-regime conditioning (Wave-9):** gating the champions on CPI
  YoY level (>3%) or 6 m inflation momentum collapses the check window
  (`ts9_lo` gates: −0.05/−0.03 vs base +0.563 on 1984–89 — the profitable
  longs there were disinflationary-grind longs the gate forbids); pure
  inflation-momentum timing is negative (−0.57/−0.73 check). "Gold as
  inflation-hedge timing" is folklore at monthly frequency; do not retry.
- **Wave 10 — US 10Y Treasury nominal & real interest-rate conditioning**
  (`N = 343 + 12 = 355`, discovery `<=1989` + `1990–1999` dev walk-forward;
  `datasets/bond-yields-us-10y@2383155` Fed H.15 GS10 combined with 1m-lagged
  US CPI YoY `r10 = y10 - cpi_yoy_lag1`, evaluation window `2000–2026`
  untouched):
  1. Long-side yield/real-rate filters (`ts9_lo` gated by `y10` falling, `r10`
     falling, or `r10 < 3%/4%`) degrade discovery (`1973–1989` SR `0.506–0.697`
     vs `ts9_lo` `0.711`), confirming that the long side of gold trend wants no
     macro confirmation.
  2. Short-side 10Y yield confirmation (`veto9_y10_up12`, shorts only when 10Y
     yield rose over 12m) scores strongly on `<=1989` (`1973–1983` SR `+0.946`,
     `1984–1989` SR `+1.160`, full `<=1989` SR `+1.004`), **but collapses on
     the `1990–1999` dev walk-forward (`SR = −0.244`, `net = −$2,065`, `3/10`
     positive years)** because the late-1990s Rubin strong-dollar / Asian-crisis
     gold bear market occurred while 10Y Treasury yields were *falling*
     (`7.8% → 4.5%`). Real-rate short confirmation (`veto9_r10_up12`) also turns
     negative in the 1990s (`SR = −0.076`), and joint USD+real-rate short
     confirmation (`veto9_usd_and_r10_up`, `1990s SR = +0.250`, `5/10` positive
     years) still trails plain `veto9` (`1990s SR = +0.268`) and fails G3
     (`>=6/10` positive years). Stopped at dev; `2000–2026` holdout untouched;
     all 12 trials counted (`N_TRIALS = 355`; `ts9_lo` DSR at `N=355` is `0.941`).
- **Monthly data SHA-256 & Pink Sheet quantization reconciliation:**
  - Canonical LF build of `xauusd_worldbank_monthly_utc_197301_202609.csv`
    (645 rows `1973-01-31..2026-09-30`) has SHA-256
    `0db007ba59f46006a6844897a2471b75e800ed2949c091fe6d376be1def433cd`
    (replicate `1a6ab6301978c1ab4e4fab2663c9351363e0af5a63f83502718bdff78912d16c`).
  - A Windows checkout without `lineterminator="\n"` produced CRLF (`\r\n`)
    hash `74338c63b14d454046034809d4b4ee73c2d8ef6d1b3986074c4fbb857608fa83`
    on identical numerical rows; `scripts/build_longhistory_monthly_dataset.py`
    and `scripts/fetch_longhistory_*_sources.py` now enforce LF (`\n`) and
    `-c core.autocrlf=false`.
  - Comparing `datasets/gold-prices@f6e9761` (which rounds 643/645 months to
    whole dollars) against the raw 2-decimal World Bank Pink Sheet
    (`awongstory/commodity-price-forecast-xgboost@c4a9f73`, 624 overlapping
    months `1973-01..2024-12`) shows `max |diff| = $0.50`, `mean |diff| =
    $0.2387`, `corr = 0.99999989`, and virtually identical evaluation metrics
    (`ts9_lo` `+$70,924.16` / SR `0.8360` vs `+$70,988.62` / SR `0.8365`;
    `veto9` `+$49,729.29` / SR `0.6606` vs `+$49,897.43` / SR `0.6618`).
- **Cross-asset ports:** frozen slow TSMOM basket Sharpe −0.007 on 11 FX pairs;
  champions trail buy-and-hold on World Bank silver (trend Sharpe 0.250 vs B&H
  0.417) and platinum (0.146), all trend forms negative 2020-24 on both
  (`data/evidence/longhistory/xmetal_replication.json`). Assessed
  **gold-specific**; do not claim a generic trend/metals premium.

## 8. Forward validation protocol (the only honest path left)

- Both champions frozen verbatim; no re-tuning. Forward clock started
  2026-10; state updated with `scripts/forward_champion_state.py --record`.
- Checkpoints (pre-declared): 24 months — continuation requires both forward
  Sharpes > 0; 36 months — full re-evaluation. `N_TRIALS` frozen at 262 for
  the forward readout (cycles after the freeze do not contaminate it).
- MEASURED costs (MT5 demo) remain required before any claim; the forward
  readout alone cannot promote anything while costs are ASSUMED.

Expectation-setting (iid-bootstrap scenario on 2000–2026 returns — assumes the
future resembles that window; **not** a forecast and not a gate): joint
probability both champions post a positive forward-24 Sharpe ≈ 0.80.
Combined-DSR projection at the frozen N=262 if forward performance repeats
history: `ts9_lo` median DSR crosses 0.95 around the 24-month checkpoint
(+24 m: median 0.958; +60 m: 0.977; +120 m: 0.991), while `veto9` remains
below for a decade (0.755 → 0.884). Read: the forward clock is a genuinely
informative validation path for `ts9_lo` on a 2–5-year horizon; `veto9`'s
role is decade-robustness, not G5 clearance. The frozen protocol's own
checkpoint criteria govern regardless.

## 9. What could change the verdict

1. **Genuinely new data:** forward months as they accrue (already frozen), or
   an independent long-history price source never used for selection.
2. **MEASURED costs** from a Windows MT5 demo terminal (also unblocks the
   claim-eligibility question and the M15 cost-sensitivity blocker).
3. A *new mechanism* (not a re-parameterisation) discovered on ≤1989 (or
   weekly 2004-2009) partitions only, frozen under N ≥ 355, that beats the
   champions on discovery and survives the 1990–1999 dev walk-forward by a
   margin large enough to matter — Waves 6–10 showed the plausible mechanism
   tweaks (hysteresis, relative trend, vol-regime and extension gates,
   extreme mean reversion, USD-momentum, real-price deflation,
   inflation-regime conditioning, and US 10Y Treasury nominal/real-rate
   conditioning) do not.
Nothing else. In particular: re-running existing cycles, loosening G6 for
slow trend, or cherry-picking lookbacks 10–11 m post-hoc are prohibited.

## 10. Operator runbook

```bash
.venv/bin/python scripts/verify_champions_independent.py   # engine cross-check (expect AGREE)
.venv/bin/python scripts/forward_champion_state.py --record  # extend forward record (paper only)
.venv/bin/python scripts/run_longhistory_<cycle>.py --stage final  # frozen cycles only; do not re-run to "improve"
.venv/bin/ruff check src tests scripts; .venv/bin/mypy src; .venv/bin/pytest -q
```

## 11. Safety invariants (binding)

- LIVE LOCKED; `REAL_CAPITAL_EXPOSURE = 0`; no order path touched by any of
  this research. DEMO authority, risk limits and promotion state unchanged.
- Costs ASSUMED until MEASURED; verdict `NO_VALIDATED_EDGE` until G1–G9 pass
  in a single frozen cycle under measured costs on non-reused data.
- Every future cycle: preregister → freeze (commit) → run final once → count
  all discovery trials in N.
