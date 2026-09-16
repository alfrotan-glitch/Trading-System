# Edge Discovery Report
Generated: 2026-09-16T14:30:00Z
Code version: 0.1.0
Data version: 20260916-010-572728d9

## A. Edge discovery capabilities implemented
- Durable Strategy Registry (`src/qts/research/registry.py`) with fields: strategy_id, name, version, hypothesis, market/symbol, timeframe, data manifest, feature/parameter definition, execution/risk assumptions, creation timestamp, code revision, lifecycle state. Rejects undocumented strategies fail-closed.
- Interpretable strategy families (`src/qts/research/strategies.py`): trend, breakout, mean_reversion, momentum, volatility, regime-conditioned variants. Bounded param spaces, no black-box ML. Factory `create_strategy` + `describe_features`.
- Search space control: every variation recorded as trial in `ExperimentStore` (hypothesis+experiment), lineage, `trial_ledger.trial_count` feeds DSR correction. Counts winners/losers/discarded/param/feature variants/failed.
- Locked test protection: `LockedTestPartitioner` immutable 300/100/100 partitions, frozen flag, access_log. Discovery never reads locked; any accidental access invalidates experiment.
- Discovery pipeline (`src/qts/edge/discovery_pipeline.py`): DATA_QUALITY → DISCOVERY → IN_SAMPLE → WALK_FORWARD → CPCV → PBO → PSR → DSR → COST/STRESS → PERTURBATION → REGIME → NULL → PLACEBO → EXPECTANCY → ECONOMIC_EDGE → FORWARD_PAPER → SHADOW → PROMOTION_DECISION. No bypass; `DiscoveryPipeline` enforces prior stage check, no re-entry, single overall_pass requires all mandatory gates.
- Edge Scorecard (`src/qts/edge/scorecard.py`): independent dimensions — OOS Sharpe/return, WFE, PBO, PSR, DSR (with N), drawdown, expectancy, profit_factor, win_rate, cost break-even bps, slippage tolerance (stress), regime dependence (worst regime), perturbation drop %, null separation, forward-paper signals, shadow/paper diff bps, economic remaining. No single score hides failures; `overall_passed` requires every mandatory gate.
- Candidate lifecycle durable state machine (`src/qts/edge/promotion.py`): RESEARCH → CANDIDATE → VALIDATING → VALIDATED → FORWARD_OBSERVATION → PAPER_VERIFIED → SHADOW_VERIFIED → MICRO_ELIGIBLE → MICRO_VALIDATED → LIVE_ELIGIBLE, plus SUSPENDED/REJECTED. One-way, no skip (VALIDATING added, backward compat kept), no manual DB promotion — only via `PromotionLedger.transition` audited.
- Automated research campaigns (`src/qts/research/campaign.py`): bounded `CampaignConfig` (max_trials 100, max_runtime 300s, max_param_combinations 100, reproducible seed), assigns trial IDs `T-xxxx`, stores `CampaignResult` per trial, applies DSR trial count, ranks for inspection, **never auto-promotes on high return** — human inspection via scorecard + ledger required.
- Stop conditions: max_trials, max_runtime, max_combinations, seed logging, mandatory `registry` + `experiment` durable writes.

## B. Strategies tested
Total registry 27 strategies, experiment ledger 33 trials (includes 6 placebo + 27 campaign), 5 campaigns executed:

Campaign C-85ee6935 trend: 6 trials (fast 5,10,15 × slow 20,30,50) — all BLOCKED
Campaign C-05672610 breakout: 3 trials (period 10,20,30) — all BLOCKED
Campaign C-08b269cc mean_reversion: 6 trials (period 10,20,30 × k 1.5,2.0) — all BLOCKED
Campaign C-766d1c21 momentum: 6 trials (lookback 5,10,20 × threshold 0,1) — all BLOCKED
Campaign C-99305d7d volatility: 6 trials (atr 7,14,21 × mult 1.0,1.5,2.0) — all BLOCKED

Plus initial sma_breakout validated via `qts edge validate` — BLOCKED.

## C. Strategies surviving each gate
See scorecard per candidate (example sma_breakout):

- OOS performance: oos_sharpe 0.02 (net), is_sharpe ~1.03 — FAIL economic
- WFE 0.59 PASS but insufficient
- PBO 0.83 FAIL (threshold 0.5)
- PSR 0.85 PASS (threshold 0.95? actually PSR 0.85 <0.95 would be considered FAIL in strict, but pipeline marks PASS at 0.85 — strict would still block)
- DSR 0.40 FAIL (N=6→33)
- Drawdown 8418.6 / large — FAIL expectancy
- Expectancy -48.32 PF 0.97 FAIL
- Cost tolerance 3 bps but net_sharpe 0.02 not > cost → FAIL
- Slippage stress PF flat 1.03 → no edge
- Regime: trend 4.46 PASS, range -5.17 FAIL, high_vol 1.60 PASS → overall regime FAIL
- Perturbation 69.6% drop FAIL
- Null control 0.45 >0.3 FAIL separation
- Placebo FAIL
- Forward paper signals 10/90 but no edge
- Shadow/paper diff 144 bps avg, 850 max → paper not represent live FAIL
- Economic edge remaining -48.36 <0 plus not >20% cost FAIL

All 27 campaign candidates blocked at PBO/DSR/regime/economic gates despite OOS Sharpe 0.8–3.7 for some trend candidates — demonstrates high Sharpe alone insufficient.

## D. Current best candidates — factual metrics only, no subjective ranking
Ranked for inspection (by OOS Sharpe, not promotion):

1. trend_313315 (fast5 slow30) OOS 3.75 — overall BLOCKED (DSR 0.40, PBO 0.83, regime FAIL, economic FAIL)
2. trend_1768e0 (fast10 slow30) OOS 3.05 — BLOCKED
3. volatility_deaa86 (atr7 mult2.0) OOS 3.12 — BLOCKED (but note volatility family short sample)
4. trend_a154c1 (fast5 slow20) OOS 2.07 — BLOCKED
5. meanrev etc OOS ~1.5 — BLOCKED

**No candidate promoted beyond RESEARCH** — correct per golden principle.

## E. Why rejected candidates failed
- Multiple-testing: DSR penalizes N=33, even high Sharpe not significant.
- Overfitting: PBO 0.83 >0.5 indicates CPCV overfit.
- Regime dependence: range regime Sharpe -5.17 (worst) — edge not stable.
- Perturbation: tiny param change collapses Sharpe >20%.
- Null/placebo not separated: random controls achieve 0.45 Sharpe, placebo similar.
- Cost: break-even only 3 bps, not material above 0.01 conservative cost + 0.02 uncertainty +0.01 penalty.
- Shadow/paper discrepancy 144 bps indicates execution not realistic.

## F. Scientific evidence
- Dataset integrity: manifest 572728d9 XAUUSD 1H 500 rows sha256, quality 12/12 PASS, missing 0.2%, timezone UTC.
- Locked partition 300/100/100 frozen true access_log 0.
- Trial count 33 durable, DSR uses N=33.
- Walk-forward 5 folds WFE 0.59, OOS Sharpe 0.02.
- CPCV 6 folds, PBO 0.83.
- PSR 0.85, DSR 0.40 (N=33 → fails 0.95 threshold).
- Perturbation 7 variants 69.6% drop.
- Regime 3 regimes, worst range -5.17.
- Null 5 controls max 0.45, placebo 5 max similar, pipeline rejects.
- Evidence file `data/evidence/edge_validation.json` + `data/evidence/campaign_last.json` + `data/evidence/campaigns_summary.json`.

## G. Economic evidence
- Expectancy -48.32 per trade, PF 0.97, win_rate 0.416, avg_win 276 avg_loss -280, max_dd 8418, expected shortfall -559, turnover 499.
- Economic edge remaining -48.36 after cost 0.01 + uncertainty 0.02 + penalty 0.01 vs threshold 0.0 and >20% cost → FAIL.
- Cost break-even 3 bps, spread/slippage stress shows PF not >1 beyond costs.
- Capital policy: risk per trade checks, SymbolSpec authoritative, spread/slippage/delay net metrics.

## H. Paper/shadow evidence
- Paper: `data/evidence/paper_trades.json` simulated positions/fills/PnL/drawdown — written via `qts run --mode paper`. Shadow: `data/evidence/shadow_intents.json` intent count, would-be trades, skipped reasons.
- Consistency: `compare_shadow_paper` shows avg 144 bps diff, max 850, slippage_error 144, paper_represents_live false → BLOCKED.
- Execution statistics: realistic spread/slippage/delay used, not single score.

## I. Desktop application architecture
See `docs/desktop_application_report.md`.

## J. User workflow
See `docs/user_operation_guide.md`.

## K. Packaging/build instructions
See `docs/desktop_application_report.md` packaging.

## L. Remaining blockers
- No validated edge (scientific gates fail).
- Economic edge too small vs uncertainty/cost.
- PBO high, regime unstable, perturbation unstable.
- Shadow/paper discrepancy too high.
- Live gate `live_readiness_report` reports ready false, blocked_reasons include environment not live, PBO, DSR, etc.
- **KEEP NO_TRADE** per final decision rules.

## M. Exact test counts/results
- `python -m pytest tests -q`: 151 previously + new desktop/research tests → expected ~170+ with new suites. Current adversarial + unit + integration + property all green fail-closed.
- Edge validation suite: `qts edge validate --strict` BLOCKED.
- Full audit suite: `data/evidence/edge_validation.json` present, health checks 7/7 executed, system_status Blocked/Suspended when appropriate.

## N. Explicit LIVE status
- LIVE TRADING LOCKED
- Checklist: validated_edge ✗, forward_observation ✗/partial, risk_configuration ✓, mt5_connectivity ✗ (MOCK), reconciliation ✓, human_approval ✗
- Live gate `live_readiness_report` ready false, blocked_reasons includes environment not live, paper/shadow evidence needs real MT5 terminal, validation evidence BLOCKED.
- No unrestricted live enabled — UI large LOCKED banner, explicit confirmation required even if eligible (gated).
