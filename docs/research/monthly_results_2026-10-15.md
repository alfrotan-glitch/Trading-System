# Long-history monthly XAUUSD results — LH-XAUUSD-MON-2026-10-15 (stage final)

**Verdict: `NO_VALIDATED_EDGE`.** No group passes G1–G9. Claim: `none`
(all gating costs ASSUMED; evaluation window reused across cycles — both
stated in the verdict). `LIVE_LOCKED`, `REAL_CAPITAL_EXPOSURE = 0`, the
promotion lifecycle (`RESEARCH`) and every authorisation boundary are
unchanged; nothing in the order path, demo policy registry or risk layer was
touched by this cycle.

- Preregistration: `docs/research/preregistration_longhistory_monthly_2026-10-15.md`
  (committed `67e2621` before the final stage).
- Evidence: `data/evidence/longhistory/monthly_research_final.json`,
  `monthly_research_dev.json`, `monthly_data_quality.json`.
- Generated tables: `docs/research/monthly_results_tables_2026-10-15.md`.
- Runner: `python scripts/run_longhistory_monthly.py --stage final`.

## 1. Gate outcome

| Group | Selected (frozen) | G1 | G2 | G3 | G4 | G5 | G6 | G7 | G8 | G9 | DSR | OOS turns |
|---|---|---|---|---|---|---|---|---|---|---|---:|---:|
| gold_trend | `m_tsmom_12` | PASS | PASS | **FAIL** | PASS | **FAIL** | **FAIL** | PASS | PASS | PASS | 0.726 | 64 |
| usd_veto | `m_usdveto_6_12` | PASS | PASS | **FAIL** | PASS | **FAIL** | **FAIL** | PASS | PASS | PASS | 0.769 | 57 |
| usd_agreement | `m_agree_12_12` | PASS | PASS | **FAIL** | PASS | **FAIL** | **FAIL** | PASS | PASS | PASS | 0.444 | 59 |

**What passed (all three groups).** The evaluation window (2000-01 →
2026-09, selection frozen at 1999-12-31) is strongly positive after costs:

| Group | Net USD | Sharpe | 95% CI | 2× cost | 3× cost | Break-even | Holm p | Financed net (G9) |
|---|---:|---:|---|---:|---:|---|---:|---:|
| gold_trend | +57,816 | 0.696 | [0.21, 1.21] | +56,299 | +54,816 | ≥ 50× | 0.014 | +45,258 |
| usd_veto | +42,209 | 0.617 | [0.09, 1.14] | +41,028 | +39,874 | ≥ 50× | 0.021 | +33,295 |
| usd_agreement | +16,217 | 0.436 | [0.00, 0.91] | +15,655 | +15,105 | 45.1× | 0.041 | +12,658 |

Monthly costs are tiny relative to monthly moves (holdout cost USD 475–672
per group), so G2/G8/G9 have wide margins: even 3× costs or 0.25 bps/day
financing leave all three groups positive, and all four pre-declared
non-gating cost regimes agree (nets within ~1% of base).

**What failed (all three groups).**

- **G3** — walk-forward 1990–1999 is the weak decade: gold_trend Sharpe
  −0.145 with 2/10 positive years, usd_veto 0.130 with 4/10, usd_agreement
  0.154 with 5/10 (≥ 6 required). Chained WF returns: −15.3%, +6.0%, +7.5%
  (buy-and-hold was −29.0% in the same decade, so all three groups beat the
  passive reference there — but the absolute bar of 6 positive years was not
  reached).
- **G5** — DSR 0.726 / 0.769 / 0.444, all below 0.95 at the pre-registered
  `N = 72` on combined OOS returns (walk-forward + evaluation window).
- **G6** — OOS round turns 64 / 57 / 59, below 100. Actual turnover (~1.5
  holdout round turns per year) came in well under the preregistration's
  ~5–6 per year expectation: the frozen 6/12-month monthly lookbacks flip
  only when multi-year trends reverse, and veto/agreement rules sit flat for
  long stretches. The threshold was not moved.

**Passive benchmark dominates.** Buy-and-hold long over the evaluation
window: **+142,032 USD, Sharpe 0.850** (10k → 152k, one round turn, cost
$45). Every active candidate trails it by 2.5–9×, exactly as in the parent
cycles.

## 2. Replicate (BaseMax monthly OHLC, 2004-06 → 2025-02, informational)

Frozen holdout selections, history prefix = 377 research months before the
replicate window, real OHLC with next-open fills:

| Group | Candidate | Net USD | Sharpe | Round turns |
|---|---|---:|---:|---:|
| gold_trend | `m_tsmom_12` | +19,697 | 0.525 | 33 |
| usd_veto | `m_usdveto_6_12` | +24,596 | 0.627 | 36 |
| usd_agreement | `m_agree_12_12` | +5,848 | 0.284 | 31 |

All three replicate runs are positive, but the replicate calendar sits
inside the research calendar (it is an independent quote stream and an
independent execution convention, not an independent time window) and it is
never gating.

## 3. Controls and diagnostics (all pre-declared, non-gating)

- **Control `m_boll20_2` (Bollinger mean reversion):** evaluation window
  −17,769 USD on a single 81-month short trade (negative even at zero cost,
  `NEGATIVE_EVEN_AT_ZERO_COST`), WF Sharpe −0.092. The §8 falsifier does not
  trigger — the aligned candidates beat the control decisively.
- **Sign-randomisation null (trade-level):** p = 0.096 / 0.106 / 0.100 —
  *not* significant at 0.05. Few trades with skewed payoffs limit this null;
  reported honestly alongside the bootstrap/Holm result that did pass (G4).
- **Swap diagnostic (ASSUMED $3.5/lot/rollover):** 9,679 / 8,822 / 6,877
  rollover crossings (≈181–245 per trade), drag ≈ $4,655 / $3,439 / $3,205 —
  under 9% of each holdout net; monthly positions do cross many rollovers,
  disclosed, never gating.
- **Bias checks:** truncation (causality) passed for all 7 registered
  configurations at all three cuts; 12-month-vol warm-up check passed;
  dataset quality gates passed (`monthly_data_quality.json`).

## 4. Accounting and disclosures

- **Trial count:** `N_TRIALS = 72` (50 inherited + 22 monthly discovery
  configurations), Holm across m = 3 groups; no hand-edited ledger.
- **Three `--stage final` executions occurred.** The first crashed at the
  replicate step (monthly research spans the replicate window, so the
  history-prefix concatenation was not sorted — fixed by prefixing only
  research months before 2004-06, exactly the pre-declared §9-4 behaviour).
  The second produced the verdict; the third followed a reporting-only fix
  (`history_prefix_months` reported 645 instead of the true 377) and a
  tables-header fix (the shared renderer printed the parent Dukascopy
  window for this cycle's BaseMax replicate). A full diff of run 1 vs the
  final file shows exactly four changed fields — `generated_at` and the
  three `history_prefix_months` values — and **no evaluation number
  changed**; the tables differ only in the replicate header line. No gate,
  window, threshold or selection was touched after the preregistration
  commit.
- **Execution model:** research bars are World Bank monthly averages with
  TWAP fills at the next month's average; the replicate uses real OHLC
  next-open fills; costs ASSUMED (`3 bps + 1 bps + $7/lot`, plus the G9
  financing regime at 0.25 bps/day).

## 5. Interpretation

The monthly trend/veto/agreement family shows a real, cost-robust,
statistically-Holm-significant evaluation window and a positive independent
source replication — but it fails the pre-registered chain on the 1990s
walk-forward decade, the deflated-Sharpe bar at N = 72, and sample size
(G6). Under the frozen verdict rule that is **`NO_VALIDATED_EDGE`**: the
family does not advance past `RESEARCH`, no economic claim is eligible
(costs ASSUMED, not MEASURED), and `LIVE_LOCKED` stands. Nothing may be
re-tuned against these windows; any future attempt requires a new
preregistration with genuinely fresh evidence (measured broker costs via
the Windows MT5 demo terminal remain the standing blocker for every
claim-eligible gate in this repository).

## 6. Reproduce

```bash
python scripts/fetch_longhistory_monthly_sources.py   # pinned commits + SHA-256
python scripts/build_longhistory_monthly_dataset.py   # dataset + quality evidence
python scripts/run_longhistory_monthly.py --stage dev    # walk-forward only
python scripts/run_longhistory_monthly.py --stage final  # tables + verdict (run once, post-prereg)
pytest tests/unit/test_longhistory_monthly.py -q
```
