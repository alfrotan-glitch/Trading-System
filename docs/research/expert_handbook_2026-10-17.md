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

The next gated cycle must use **N = 327** in its DSR. Per-cycle evidence:
`data/evidence/longhistory/{ensemble,weekly,hybrid,weekly_hybrid,volmanaged}_research_final.json`;
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

## 9. What could change the verdict

1. **Genuinely new data:** forward months as they accrue (already frozen), or
   an independent long-history price source never used for selection.
2. **MEASURED costs** from a Windows MT5 demo terminal (also unblocks the
   claim-eligibility question and the M15 cost-sensitivity blocker).
3. A *new mechanism* (not a re-parameterisation) discovered on ≤1989 (or
   weekly 2004-2009) partitions only, frozen under N ≥ 307, that beats the
   champions on discovery by a margin large enough to matter — Wave-6 showed
   the two most plausible mechanism tweaks do not.
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
