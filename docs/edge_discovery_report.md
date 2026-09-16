# Edge Discovery Report — Autonomous Research Laboratory
Generated: 2026-09-16T14:45:00Z
Code version: 0.1.0
Data version: 20260916-010-572728d9 (XAUUSD 1H 500 bars, plus 2000-bar 86ca2f9c)
Trial ledger: 75 trials, registry 69 strategies, distinct hypotheses ~8, campaigns 15

## A. Edge discovery capabilities implemented
- **Registry** `src/qts/research/registry.py` 13 fields, rejects undocumented.
- **Families** `src/qts/research/strategies.py` 5 + `invented_strategies.py` 4 (state-machine, event-driven shock, multi-timeframe, volatility-normalized) — bounded spaces, factory.
- **Position Management** `src/qts/research/position_management.py` 6 exit policies (fixed, volatility, trailing, time, breakeven, momentum-decay) — joint entry+exit hypotheses tested OOS.
- **Feature Discovery** `src/qts/research/feature_discovery.py` 6 controlled features (returns_1, range_5, volatility_20, spread_proxy, session_hour, range_compression) with timestamp semantics, lineage, no leakage, no locked contamination.
- **Search control**: `ExperimentStore` every variation trial, `trial_count` feeds DSR, counts winners/losers/discarded/param/feature/failed.
- **Locked protection**: 300/100/100 frozen, access_log, discovery never reads locked; `DiscoveryPipeline` enforces no bypass.
- **Pipeline** 18 stages enforced via `DiscoveryPipeline` (DATA_QUALITY→...→PROMOTION_DECISION), no re-entry, `overall_passed` requires all mandatory.
- **Scorecard** `src/qts/edge/scorecard.py` independent dimensions, no single score hides failures.
- **Lifecycle** `src/qts/edge/promotion.py` 10-state RESEARCH→LIVE_ELIGIBLE + VALIDATING, one-way, no manual DB promotion.
- **Intelligence** `src/qts/research/intelligence.py` inspects data/evidence, generates falsifiable `HypothesisSpec` with 8 provenance fields.
- **Campaigns** `src/qts/research/campaign.py` bounded (max_trials≤100, runtime, combinations, seed) + `campaign_engine.py` 11 steps autonomous (review data→review failures→plan→hypotheses→experiments→store→attack→eliminate→refine→re-test→evidence portfolio), never LIVE.
- **Budget** explicit max_trials/runtime/feature/param/mutation/retries/data/seed, STOP when exhausted.
- **Memory** `src/qts/research/memory.py` durable `research_memory`, `has_failed_similar` prevents rediscovery.
- **Novelty** `src/qts/research/novelty.py` fingerprint family+mechanism+features+param_keys, reports total vs distinct (e.g., 75 vs 8).
- **Statistical** `src/qts/research/statistical.py` White Reality Check, Hansen SPA, permutation, minimum backtest length, drawdown ES, parameter surface — each documented purpose/assumptions/inputs/limitations, reference, tests, failure modes.
- **Adversarial** `src/qts/research/adversary.py` reports best_for/best_against, verdict BREAKS/SURVIVES, never only favorable.
- **Data Audit** `src/qts/data/audit.py` inspects sources, reports limitation, recommends expansion.
- **Economics** `docs/experiment_governance.md` tracks trial/family/param/feature/search depth/selection/dataset/timeframe/symbol/manual/re-runs, no N reset, no hidden retries.
- **Desktop** 10 new views: Research Lab, Hypothesis Explorer, Campaign Runner, Experiment Ledger, Candidate Explorer, Failure Analysis, Evidence Viewer, Data Observatory, Strategy Lifecycle, Research Memory.

## B. Strategies tested
Registry 69, experiments 75, campaigns 15 (including 5 initial families + 1 autonomous demo + tests):
- C-85ee6935 trend 6 — BLOCKED
- C-05672610 breakout 3 — BLOCKED
- C-08b269cc mean_reversion 6 — BLOCKED
- C-766d1c21 momentum 6 — BLOCKED
- C-99305d7d volatility 6 — BLOCKED
- Autonomous C-c6cd8c31 trend 6 — BLOCKED (distinct 6)
- Autonomous C-... volatility 6 — BLOCKED
- Test campaigns (trend 3 each ×4) — BLOCKED
- Invented strategies (state-machine, event shock, multi-timeframe, vol-normalized) via manual runs — BLOCKED (no survivor)
- sma_breakout via `qts edge validate` — BLOCKED

Every campaign bounded, reproducible seed, no hidden.

## C. Strategies surviving each gate
**None survive all gates.** Example sma_breakout N=75 DSR 0.12 vs PSR 0.85:
- OOS Sharpe 0.02 net FAIL, WFE 0.59 PASS but insufficient, CPCV PBO 0.33 PASS (now stable) but DSR 0.12 FAIL, perturbation 69.6% FAIL, regime range -5.17 FAIL, null 0.45 FAIL, placebo FAIL, cost BE 3bps FAIL, expectancy -48.32 PF0.97 FAIL, economic -48.36 FAIL, shadow diff 144bps FAIL.
- All 69 campaign candidates similarly blocked at DSR/perturbation/regime/economic despite OOS up to 3.75 — proves high return insufficient.

## D. Current best candidates — factual, no subjective ranking
Ranked for inspection only (by OOS, not promotion, per governance):
1. trend_313315 fast5 slow30 OOS 3.75 DSR 0.12 PBO 0.33 BLOCKED
2. volatility_deaa86 atr7 mult2.0 OOS 3.12 BLOCKED
3. trend_1768e0 fast10 slow30 OOS 3.05 BLOCKED
4. trend_a154c1 fast5 slow20 OOS 2.07 BLOCKED
5. state_machine compressed→expansion OOS ~0.8 BLOCKED (invented, not yet validated)
No candidate promoted beyond RESEARCH.

## E. Why rejected candidates failed
- Multiple-testing: DSR 0.40→0.12 as N 33→75, PSR 0.85 insufficient for N=75.
- Overfit: earlier PBO 0.83, now 0.33 but still other gates fail; parameter surface unstable isolated peak.
- Regime: range -5.17 worst, trend 4.46 vs high_vol 1.6 — dependent.
- Perturbation: tiny param change collapses >20%.
- Null/placebo: random 0.45 close to real net 0.02 — false correlation.
- Cost: BE 3bps <20bps needed, economic remaining -48.36 <0.
- Shadow/paper 144bps — not live.
- White Reality Check p≈0.65, Hansen SPA p≈0.7 — not significant.

## F. Scientific evidence
- Dataset: 572728d9 500 rows + 86ca2f9c 2000 rows XAUUSD 1H, quality 12/12 PASS, missing 0.2%, UTC, gap 0.
- Locked 300/100/100 frozen true access_log 0.
- Trial 75 DSR N=75, distinct 8 (novelty report: total 75 distinct 8 largest cluster ~12).
- Walk-forward 5 folds WFE 0.59 OOS 0.02, CPCV 6 folds PBO 0.33, PSR 0.85 DSR 0.12 fail, perturbation 7 fail, regime 3 worst -5.17, null 5 max 0.45, placebo 5 fail, evidence `edge_validation.json` + `autonomous_campaign.json`.

## G. Economic evidence
- Expectancy -48.32 PF0.97 win 0.416 avg_win 276 avg_loss -280 max_dd 8418 shortfall -559 turnover 499.
- Economic remaining -48.36 after cost 0.01 + uncertainty 0.02 + penalty 0.01 vs >0 and >20% cost FAIL, BE 3bps.
- Stress 1.0/1.5/2.0× PF flat 1.03 — no edge beyond costs.
- Position management joint hypotheses (fixed vs trailing vs time) all fail OOS.

## H. Paper/shadow evidence
- Paper `paper_trades.json` simulated fills/PnL/drawdown; Shadow `shadow_intents.json` would-be/skipped; consistency diff 144bps paper not live.
- Execution-aware: next-bar-open, spread/slippage/latency 100ms, partial fills, bid/ask asymmetry studied; mid-price edge not validated.

## I. Desktop application architecture
See `docs/desktop_application_report.md` — FastAPI+pywebview, 15+ endpoints, 10 research views, health 7 checks, one-click `QTS.exe`.

## J. User workflow
See `docs/user_operation_guide.md` — double-click → health → dashboard, Research Lab shows WHAT thinking, WHY hypothesis, EXPECTS, FAILED, LEARNED, NEXT.

## K. Packaging/build instructions
See `docs/desktop_application_report.md` packaging: `pip install pyinstaller && pyinstaller packaging/qts.spec` → `dist/QTS.exe`, `scripts/create_shortcut.ps1`, `launch_desktop.bat`.

## L. Remaining blockers
- No validated edge (DSR, regime, perturbation, null fail).
- Economic edge too small vs uncertainty/cost.
- Shadow/paper discrepancy.
- Single 500-row sample limitation explicitly reported — need 5000+ bars, multi-year, multi-symbol/timeframe, real bid/ask.
- Live gate ready false, blocked reasons include environment not live, validation BLOCKED, PBO/DSR, etc. **KEEP NO_TRADE**.

## M. Exact test counts/results
- `python -m pytest tests -q`: **171 passed, 2 warnings** (20 desktop + 19 edge/capital + 132 others). All scientific/safety green.
- Edge validation `qts edge validate --strict` BLOCKED (passed false economic false).
- Research `qts research campaign` bounded 6-12 trials each BLOCKED, `qts research autonomous` 6-12 trials BLOCKED, adversarial verdict BREAKS for all, White p 0.65 SPA p 0.7 not significant.
- Audit: `data/evidence/edge_validation.json` N=75, `autonomous_campaign.json` 11 steps, `autonomous_research.json`, `data_source_audit.json` (2 sources, limitation), `desktop_health.json` 7/7 PASS Running, `campaigns_summary.json` 69 registry 75 trials.

## N. Explicit LIVE status
- **LIVE TRADING LOCKED**
- Checklist: validated_edge ✗, forward_observation ✗/partial, risk_configuration ✓, mt5_connectivity ✗ (MOCK), reconciliation ✓, human_approval ✗.
- Blocked: `environment not live`, `NO_VALIDATED_EDGE`, `validation BLOCKED`, `DSR low`, `regime dependent`, `cost BE low`, `shadow diff high`, `data limitation`.
- No unrestricted live, no override, no convenience bypass — explicit confirmation required even if eligible (gated via `PromotionLedger`).

---

### Autonomous Campaign Detailed (per deliverable 20)
- **Research question**: Search for durable XAUUSD edge under conservative execution (spread 3bps × multiplier, slippage, latency 100ms, next-bar-open).
- **Hypotheses**: 6 generated (trend persistence, breakout failure, volatility expansion, range compression, time-of-day, event shock) — each with 8 provenance fields.
- **Mechanism**: e.g., volatility clustering, time-of-day liquidity.
- **Data used**: 500+2000 XAUUSD 1H, limitation reported, no silent substitution.
- **Trial count**: 6-12 per autonomous batch, total 75, distinct 8.
- **Strategies tested**: classic 5 families + 4 invented (state-machine etc.) + 6 exit policies joint.
- **Failed candidates**: 75 all, 0 surviving.
- **Surviving**: none — would require OOS>0.3, DSR>0.95, PBO<0.5, BE>20bps, regime stable, null separation, etc.
- **Strongest for** (example trend_313315): WFE 0.59, PSR 0.85.
- **Strongest against**: DSR 0.12, PBO 0.33 (now pass but still), perturbation 69.6%, regime -5.17, cost 3bps, null 0.45, placebo fail, White p0.65, SPA p0.7.
- **DSR**: 0.12 (N=75), **PBO**: 0.33, **Reality Check**: p0.65, **SPA**: p0.7.
- **Cost sensitivity**: BE 3bps vs 20bps needed — sensitive.
- **Execution sensitivity**: shadow diff 144bps — sensitive.
- **Regime**: trend 4.46 pass, range -5.17 fail, high_vol 1.6 pass — dependent.
- **Robustness**: perturbation fragile, parameter surface unstable isolated peak.
- **Forward**: 10/90 signals but no edge, forward not validated.
- **Unresolved uncertainty**: single 500-row sample, no multi-market, no real tick, no 2020-2024 varied regimes.
- **Never winner by return**: top OOS 3.75 still BLOCKED.
- **Self-audit verdict**: BLOCK — over-search, perturbation, regime, N reset NO, leak NO, but overfit YES → keep NO_TRADE.
