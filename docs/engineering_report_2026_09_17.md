# QTS Engineering Report — Authority Architecture, Fabrication Removal & Safety Hardening

**Branch:** `arena/01a0af7d-trading-system` · **Base:** `1b7fbed` · **Head:** `b802510`
**Date:** 2026-09-17 · **Environment:** Linux 3.11 sandbox (development — no MT5 terminal, no broker access)

---

## 1. Architecture — what was redesigned and why

The audit's root cause was **authority duplication**: demo permission, risk
limits, environment/mode, observation data, and metric semantics were each
defined or derived independently in several places, so components could
disagree silently. Five canonical authorities now own these questions
(`docs/canonical_authorities.md`):

| Authority | Module | Replaces |
|---|---|---|
| **ExecutionMode** | `qts.domain.modes` | scattered `QTS_ENV`/`QTS_MODE`/YAML/UI derivations |
| **DEMO execution permission** | `qts.lifecycle.demo_authority` | the cosmetic `/api/demo/enable` response string |
| **Risk limits** | `qts.risk.authority` | `RiskLimits` + `RiskConfig` + `DemoForwardLimits` + UI text |
| **Observation store** | `qts.observability.forward_observatory` (SQLite, provenance-first) | competing JSON evidence files |
| **Provenance & metric semantics** | `qts.domain.provenance` | implicit "zeros and defaults everywhere" |

Supporting redesigns:

- **Broker metadata resolution** (`mt5_adapter`): explicit alias table, zero
  defaults, contradiction guards, fail-closed on any missing/invalid field.
- **Live-gate proof tiers**: `structural` / `integration` /
  `real_environment` — mock evidence can never satisfy a real-environment
  tier (`live_gate.py`).
- **Evidence quarantine**: `data/evidence/quarantine/` with a README
  documenting every violation of the removed fabricated artifacts.
- **Durability-before-visibility**: the observation collector persists the
  session end (and manifest) BEFORE flipping its state — a state transition
  is always a persistence point.

## 2. Bugs closed (audit findings → resolution)

| # | Finding | Resolution (evidence) |
|---|---------|----------------------|
| A | Demo enable ignores `readiness.passed` | `/api/demo/enable` computes a FRESH 14/14 report in-request; refusal → HTTP 409 + durable DISABLED + audited refusal. Test: `test_demo_authority_gate.py` (13 cases), `test_demo_enable_evaluates_the_same_saved_connection` |
| B | `demo_enabled=true` is cosmetic | Durable SQLite+audit state consumed by `/api/demo/state`, `/api/demo/config`, UI, and the execution boundary; survives restart (test-pinned) |
| C | "Start Observation" stub | Already replaced by the real collector (commit 1b7fbed); now upgraded with canonical session identity (env/broker/symbol/timestamp basis/code version), DEMO provenance stamping, honest `ENDED_ON_ERRORS` terminal status |
| #5 | Competing observation stores | ONE SQLite store; `/api/demo/observations` reads it; manifest is a derived export; the impulse forward-evidence gate consumes `real_observation_count()` (provenance-gated), never a JSON file |
| #6 | Fabricated legacy evidence | `demo_forward_observations.json` (constant 2.5 bps slippage, 120 ms latency, +0.05 fills, wrong symbol, `source=REAL DEMO`) → quarantined with documented violations; regression test forbids its return |
| #7 | Placeholder "reality metrics" | All comparison metrics are MEASURED or UNAVAILABLE with reasons; signal agreement = real event alignment (window-matched bar timestamps, one-to-one); zero-ratio fabrication removed and pinned |
| #8 | Risk authority duplication | One resolver; mode restrictions may only tighten (validated at import+use); loosening rejected without `risk.approved`; snapshot served at `/api/risk` with per-field sources + config hash |
| #9 | Fabricated safety fallbacks | `equity→10000` in risk engine → `ACCOUNT_STATE_UNAVAILABLE` veto; unlabeled dry-run/paper/shadow accounts labeled `*_SIM`/`CLI_SYNTHETIC`; `order_check` price=`2000` fabrication removed; `BrokerAdapter.account()` default fabrication removed (raises) |
| #10 | Defaulted broker metadata | Contract size, volume min/max/step, digits, point, tick size, trade mode, filling mode, execution mode, stops/freeze: all required, fail-closed; contradictory geometry rejected; `trade_allowed` default-True fabrication replaced by authoritative `trade_mode` |
| #11 | Account authority | `leverage`/`currency` = `None` (UNAVAILABLE) when absent — never guessed; `source="BROKER"`; receipt-time limitation documented in `docs/mt5_demo_setup.md`; unknown equity vetoes orders |
| #12 | Timestamp model | Preserved (measured-offset contract + regression tests untouched); collector sessions bind the timestamp basis; provenance travels in every record |
| #13 | One market-data path | Preserved (`MarketDataProvider` validates; collector uses it); no new bypass introduced |
| #14 | Mode authority | Canonical resolution; unknown selection → `ModeResolutionError` (never silent DEVELOPMENT); effective-mode diagnostics in `/api/health` and `/api/env/boundary` |
| #16/#20 | Live-gate quality | `check_mt5_connectivity` rewritten: real terminal required; mock-based pass banned; proof tiers exposed in the report; micro (LIVE-family) fails closed without a real terminal |
| #21/#22 | Weak evidence checks | Paper/shadow gate evidence now requires parseable JSON + mode label + `data_version`/`generated_at`/`code_version` lineage + real records; existence-only acceptance banned (tests pin both the refusal and the pass) |
| #33 | Reality reporting | Comparison + execution-reality endpoints distinguish MEASURED / UNAVAILABLE with reasons; `/api/paper`'s fabricated 1.5 bps slippage removed (PAPER slippage is a model assumption) |
| #36 | UI truthfulness | Dashboard renders UNAVAILABLE metrics honestly (no fake equity/balance/regime/spread); MT5 view shows REAL_TERMINAL or DISCONNECTED with no invented spec; demo-enable button displays refusals verbatim; demo state view shows the authority |
| #15 | Credentials | Wizard store already credential-free with rejection reporting (preserved; no regression) |

## 3. Safety — what can and cannot execute per mode

| Mode | Broker data | Broker orders | Enforced by |
|---|---|---|---|
| DEVELOPMENT | no | never | no adapter in path; mode cannot submit |
| PAPER | simulation | never | `PaperBrokerAdapter` (local matching only) |
| SHADOW | simulation | never | `ShadowBroker` (intents only) |
| DEMO_FORWARD | **yes** | **structurally never** — observe runtime has no order path (AST-pinned + runtime `order_send` sentinel); mode cannot submit (authority refuses) | collector + authority |
| DEMO_EXECUTION | yes | yes — only behind a fresh, durable, audited 14/14 pass; decays after 120 s without re-verification | `DemoExecutionAuthority` |
| LIVE | yes | **LOCKED** — real-environment proof tiers; connectivity passes only with a REAL terminal | live gate |

Kill switch, reconciliation suspension, idempotency, and restart recovery
are unchanged and regression-covered. Risk vetoes on unknown account state
(`ACCOUNT_STATE_UNAVAILABLE`) make UNKNOWN → BLOCK the default.

## 4. Research

The impulse/event research framework (pre-registered, Holm-Bonferroni,
placebo, locked validation, trial ledger, data-adequacy gate) is intact and
now reads forward evidence ONLY from the canonical store with DEMO/REAL
provenance — 10 synthetic ticks and 50 fabricated JSON rows both correctly
fail the forward-evidence gate (test-pinned).

## 5. Scientific validity

Leakage/overfitting controls unchanged (locked test partition, purged CPCV,
walk-forward, perturbation, null/placebo, PSR/DSR, trial ledger). New:
every produced evidence artifact now carries code lineage
(`generated_at`, `code_version`, `data_class`), and the live gate rejects
lineage-less evidence with a regeneration reason instead of accepting any
non-empty file.

## 6. Broker reality (honest scope)

Verified **in this environment**: none against a live terminal — this
sandbox has no MT5/WM Markets access. What IS verified: the contract with
the real environment is preserved and regression-pinned (real-API field
aliases incl. `trade_contract_size`/`trade_exemode`, the WMMarkets
timestamp behavior, the 14-check gate, initialize-in-process requirement,
`XAUUSD@` symbol mapping). The previous session's real-terminal readiness
evidence remains valid: those checks were not weakened — two fabricated
defaults inside them (`trade_allowed→True`, demo-gate metadata defaults)
were replaced with authoritative resolution.

## 7. Evidence

- Canonical stores: `data/sqlite/qts.db` (state/audit),
  `data/sqlite/forward_observatory.db` (observations, provenance-first)
- Derived exports: `data/evidence/*.json` (regenerable, never gate-satisfying)
- Quarantine: `data/evidence/quarantine/` (2 artifacts + README)

## 8. Testing

- **493 passed, 16 skipped** (full suite; was 440 at baseline) — includes
  **64 new adversarial tests**: demo authority (13), authority boundaries
  (18), no-fabrication (21), plus upgraded existing suites
- Static gates: **ruff clean**, **mypy clean** (110 files)
- API smoke: all 22 GET endpoints 200; enable flow 409→DISABLED end-to-end
- Full-suite run twice consecutively green (race fix verified)

## 9. Remaining limitations (genuinely unproven)

1. **No live-terminal validation in this session** — the Windows/MT5/WM
   Markets probe, real DEMO observation, and DEMO execution remain to be
   re-run on the real machine (procedures unchanged; `docs/mt5_demo_setup.md`).
2. **DEMO_EXECUTION path unexercised end-to-end** — the authority gates it
   correctly, but no real demo order lifecycle has been recorded since the
   fabricated artifacts were removed. Execution-reality metrics are
   honestly UNAVAILABLE.
3. **No forward observation sessions yet** under the new canonical store —
   the first real session will be the first DEMO-class evidence.
4. **No validated trading edge** — research status remains
   BLOCK / KEEP NO_TRADE (DSR 0.12, insufficient data depth/diversity).
   This is a correct scientific result, not a defect.
5. Derived-JSON consumers outside the API (impulse report legacy code
   paths reading `data/evidence/*.json` for non-gate purposes) still exist;
   they are read-only analyses, not gates.

## 10. Live status

**LIVE: LOCKED.**

Not `ELIGIBLE_PENDING_GOVERNANCE`. Blocked by: no validated edge, no
real-environment connectivity evidence in this session, no forward
evidence, lineage-less legacy paper/shadow artifacts requiring
regeneration (the gate now says so explicitly), and the structural
requirement of human approval. No backtest, demo result, UI action, or
mock can change this — the gate's evidence tiers and the demo authority's
audit-first state machine make the forbidden transitions structurally
impossible, and 64 adversarial tests pin them.

**The system can now honestly say: it does not know whether it has an
edge — and it is built to find out without being able to lie about it.**
