# Deep Repository and Trading-Edge Audit — 2026-10-09

## Scope and evidence

This audit inspects the public `main` tree at merge commit `5cad2b865a2b49bfc7d6cab7c71de708daeba13b` (PR #9). It distinguishes source-code facts from conclusions that require a fresh local test run. This document is an audit record, not a claim that the repository has passed new tests.

## Executive decision

**Engineering: materially hardened, but not fully closed. Trading edge: NOT ESTABLISHED. DEMO execution: blocked until authorization is valid. LIVE must remain locked.**

PR #9 is merged and its description records completed-bar TSMOM semantics, bounded completed-bar warmup, close-path safety, registry resealing, and test gates. The current source also contains the state-root path module and the demo authorization validator. However, the following issues remain visible in the current `main` source/evidence.

## Findings

### P0 — DEMO authorization artifact is incompatible with its validator

File: `data/evidence/demo_execution_authorization_2026-09-23.json`

The artifact's `risk_ceiling` includes `max_drawdown_pct: 5`. In `src/qts/lifecycle/demo_authorization.py`, `_RISK_CEILING_FIELDS` does not include `max_drawdown_pct`, and `_validate_risk_ceiling()` rejects any unknown key with a fail-closed error. Therefore the checked-in authorization cannot validate as written and DEMO execution remains disabled by policy.

**Required resolution:** do not edit the authorization JSON or recompute its hash as a workaround. The canonical risk model currently enforces an absolute USD drawdown cap but has no percentage-drawdown field or percentage-based enforcement. Therefore removing `max_drawdown_pct` would silently discard a stated 5% limit. Either implement percentage drawdown end-to-end in canonical risk authority/engine/context and test it, then have the owner re-issue the artifact under the new contract, or obtain an explicit owner decision to withdraw that percentage limit and issue a new artifact with only supported limits. Keep execution disabled until the chosen contract is implemented, owner-authorized, and fully validated.

### P1 — CLI evidence, audit, and paper/shadow databases were working-directory-relative (fixed in this PR candidate)

Files: `src/qts/cli/ops.py`, `src/qts/config/paths.py`.

The dry_run, micro, paper, and shadow paths wrote evidence and/or SQLite state through relative Path("data/...") calls. The audit sink also used the default relative logs/audit.jsonl path. Launching commands from another directory could split durable state between the repository and the caller cwd.

This PR candidate registers canonical artifacts and environment overrides for dry_run, micro, paper_trades, shadow_intents, paper/shadow SQLite databases, and the audit JSONL sink.

The affected writers now resolve through artifact_path() before creating directories or files. A regression test verifies state-root anchoring and environment override behavior. CI is the final verification gate for this candidate.

### P1 — State-root behavior had a documented-contract inconsistency (fixed in this PR candidate)

File: `src/qts/config/paths.py`, `state_root()`.

The module describes one cwd-independent state root, but the implementation deliberately returns the current working directory when it differs from the detected repository root and contains a `data/` directory. This may support isolated fixtures, but it makes the production contract conditional and can cause two processes to resolve different durable state depending on their launch directory.

The cwd-based exception was removed in this PR candidate. Isolated tests and portable installations must select their state root explicitly with `QTS_STATE_ROOT` or injected paths. A regression test creates a foreign cwd containing a `data/` directory and asserts that `state_root()` and the artifact path remain anchored to the detected repository root. CI is the final verification gate.

### P0 — No validated trading edge; the canonical evidence explicitly blocks promotion

File: `data/evidence/edge_validation.json`.

Observed fields:
- Dataset provenance: `SYNTHETIC:fixture:XAUUSD_1H_500.csv`
- Dataset size/span: 500 bars / approximately 20.83 days
- Readiness: `BLOCKED_INSUFFICIENT_DATA`
- Required for claim eligibility: at least 5,000 bars and 180 days from an allowed real/historical/broker-derived source
- Trial ledger: 304 trials
- Walk-forward efficiency and out-of-sample Sharpe checks: failed
- Gross/net cost decomposition: not implemented; blocks
- Randomized control and placebo: not executed
- CPCV/PBO: unavailable
- Perturbation: reported Sharpe changes from 1.02 to -1.63
- PSR: approximately 0.455
- DSR: approximately 0.0013
- Net expectancy: 0.0000 and profit factor 0.00 in the reported artifact
- Final conclusion: `BLOCKED_INSUFFICIENT_DATA`

This 1-hour synthetic fixture cannot validate the registered 15-minute XAUUSD TSMOM strategy. It is suitable for mechanism/contract tests only, not for a profitability claim.

### P1 — Public evidence for a strategy family is not evidence for this exact implementation

The registered strategy `DEMO-XAUUSD-TREND-TSMOM-V1` is an EMA 12/48 crossover on completed 15-minute bars with a fixed 0.01 lot and a fixed 3.0 price-unit stop. Published research supports time-series momentum as a broad phenomenon across liquid futures over monthly horizons; it does **not** establish that this exact intraday XAUUSD rule, broker feed, spread, stop, holding period, or sizing is profitable.

The strategy should remain a frozen DEMO benchmark, not be labelled profitable or live-eligible.

## What is already present on main

The merged PR #9 describes and the current source contains:
- completed-bar rather than quote-count strategy semantics;
- startup warmup from bounded, completed broker bars, with the forming bar excluded;
- close-safety tests intended to exercise the real order journal and engine;
- a registry resealer that cross-checks registered parameters and recomputes hashes;
- documented fast, extended, and DEMO test gates;
- a fail-closed DEMO authorization validator.

Presence of these components is not equivalent to proving the current runtime is ready. In particular, the authorization mismatch above prevents DEMO order permission.

## Trading-edge plan: evidence first, no fabricated winner

Do not attempt to make the current synthetic artifact pass by changing thresholds or relabelling provenance. Do not optimize on forward DEMO outcomes.

1. **Acquire real broker data:** use the pinned WM Markets DEMO terminal and exact symbol mapping `XAUUSD@`; preserve raw data, timestamps, broker/server clock-offset provenance, gaps, bid/ask where available, and immutable hashes. Determine the maximum actual history available before selecting the research horizon.
2. **Use one canonical dataset per experiment:** first validate the 15-minute bars from real M1/tick data and separately verify any broker-provided M15 bars. Do not mix synthetic fixtures into claim-eligible results.
3. **Freeze a small, production-inspired candidate set before evaluation:**
   - benchmark A: the existing EMA 12/48 completed-bar trend rule;
   - benchmark B: a volatility-normalized breakout/trend rule with predeclared entry, exit, and stop rules;
   - benchmark C: a simple mean-reversion control only if market microstructure and spread costs make it plausible.
   Keep this to a few distinct hypotheses, not hundreds of indicator variants.
4. **Simulate executable prices:** enter at the next realistically available bid/ask, include spread, commission, swap/financing, slippage, rejected/partial fills, session gaps, and stop execution assumptions. Report measured costs separately from assumptions.
5. **Separate time chronologically:** development, validation, and locked final holdout must not overlap. Use walk-forward folds and a randomized/placebo control. Track every tried configuration; compute PSR/DSR and PBO only when their inputs are valid.
6. **Stress without selecting on the holdout:** cost multipliers, modest parameter perturbations, session/time windows, and regime slices must be preregistered. Require positive net expectancy after costs, stability, acceptable drawdown, and enough independent observations. If a candidate fails, reject it rather than tuning against the holdout.
7. **Only then run forward DEMO:** compare realized broker P&L to predicted costs and slippage. DEMO is execution evidence, not proof by itself of a durable edge.

## Acceptance gates

- [ ] Owner authorization is valid under the canonical risk-ceiling schema; otherwise DEMO orders remain disabled.
- [ ] `micro` artifact paths use the canonical state root and are tested from a foreign cwd.
- [ ] State-root behavior is consistent with its documented contract and covered by regression tests.
- [ ] Current fast, extended, DEMO, static, registry-hash, and UI gates run on the exact candidate commit; all failures are classified.
- [ ] Real data provenance and quality are independently verified.
- [ ] Net-of-cost out-of-sample edge passes preregistered statistical and economic tests.
- [ ] LIVE remains locked regardless of DEMO or backtest results until a separate explicit authorization and promotion process exists.

## External methodology references

- Moskowitz, Ooi & Pedersen (2012), *Time Series Momentum*, Journal of Financial Economics: https://doi.org/10.1016/j.jfineco.2011.11.003
- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality*: https://doi.org/10.3905/jpm.2014.40.5.094
- Bailey et al., *The Probability of Backtest Overfitting*: https://escholarship.org/uc/item/4w1110bb

These papers support the validation methodology and the general strategy family; they do not prove that QTS's current XAUUSD strategy is profitable.
