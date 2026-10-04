# Architecture Closure Report — 2026-10-04

**Verdict: ARCHITECTURE CLOSED.** No unclosed MUST-FIX risk remains. This
audit changed no production code; it is the verification pass that proves the
register is complete.

- **Audited HEAD:** `a7b2b93` (`arena/01a10289-trading-system`), reconciled
  with origin before any work — local == remote, working tree clean. The
  task referenced `7fd7be7` (ARCH-050); `a7b2b93` is its direct child
  (ARCH-051), already committed and CI-green when this audit began.
- **Method:** full re-scan of every production execution path and safety
  authority (grep + AST + the structural guard suite), review of all 51
  change-register rows, §11 forbidden duplications, §14 known limitations,
  and the complete verification battery.

---

## 1. Authority verification — one authority per concept, each pinned

| Concept | The ONE authority | Scan result at `a7b2b93` | Pinned by |
|---|---|---|---|
| Real-venue broker | `qts.adapters.mt5_adapter.MT5Adapter` | only class calling `mt5.order_send` (submit / cancel / close, all through `validate_broker_request`) | `test_mt5_boundary` suite |
| Simulation brokers | `RealisticPaperBroker`, `ShadowBroker` | cannot reach a venue; only other `BrokerAdapter` subclasses | §11.1 + orphan guard |
| Order submission | `ExecutionEngine.submit_intent` → `broker.submit` | exactly ONE `broker.submit` call site (`engine.py:746`); all `session.submit` callers (API, CLI, autopilot) route through the gated `DemoSession` | `test_architecture_boundaries` |
| Risk limits | `qts.risk.authority` (`BASE_LIMITS` → mode restrictions → acknowledged overrides) | zero literal limit numbers outside `risk/authority`, `risk/engine`, `config/settings` (YAML schema); `engine_limits_from` is the one snapshot→engine translation (ARCH-050) | `test_risk` + pretrade gate tests |
| Kill switch | `qts.risk.engine.RiskEngine` over durable `risk_state` in `artifact_path("db")` | all writers are `RiskEngine.kill_switch`/`reset_kill` (CLI, engine `handle_kill`, demo session, `edge.emergency` which raises without a real engine); every reporting surface reads `kill_state()` | kill-switch veto tests + ARCH-050 guard |
| Reconcile suspension | `reconcile_state` row, read ONLY via `load_reconcile_suspension` | every consumer (engine, API `deps`, desktop health, demo session, live gate) delegates to the one reader | §11.2 + recovery tests |
| Execution history | `DemoOrderJournal` (`demo_order_journal`) | the only store that persists execution history | §11.4 |
| Mode vocabulary | `qts.domain.modes.ExecutionMode` | one enum; YAML `Literal` values map deterministically through `_ENV_ALIASES`; no new mode words introduced by ARCH-050/051 | `test_issue5_runtime_consistency` |
| State paths | `qts.config.paths` (`artifact_path`/`resolve_state_path`) | no cwd-relative state IO, including aliased/dotted pathlib forms (ARCH-051) | alias-proof cwd-IO guard |
| Broker-capable engines | canonical safety DB, structurally | every `ExecutionEngine` wired to an MT5-capable broker rides `artifact_path("db")`, never disables `persist_kill`/`persist_reconcile_state`, never mixes with `tempfile` | `test_no_production_execution_path_bypasses_the_canonical_safety_authority` (anti-vacuous: must find both known engines) |

**No alternate broker, risk, kill-switch, reconcile, or execution authority
exists.** Production execution paths are exactly two — the DEMO session
gateway and the micro CLI path — and both consume the identical durable
safety set.

## 2. CLOSED risks

- **Risk #0 — micro execution-path exception (ARCH-050, `7fd7be7`).** The one
  CLI path whose broker can be a real terminal wired RiskEngine/idempotency/
  reconcile state to a `tempfile` DB; an engaged canonical kill switch did not
  block it (measured: exit 0, order submitted). Closed: canonical DB end to
  end, authority-resolved limits, exit-2 refusals before any broker exists.
  Proven by two deterministic adversarial tests + the structural guard, all
  RED pre-fix.
- **Risk #0 follow-on — alias hole in the cwd-IO guard (ARCH-051, `a7b2b93`).**
  `micro.json` escaped `state_root()` through `Path as _Path2`, invisible to
  the name-based guard. Closed: canonical registry key + AST alias resolution
  in the guard, both RED pre-fix.
- **All earlier register risks.** 51/51 rows in the QTS_PROJECT_CONTROL.md
  change register are APPROVED with test evidence; none is PENDING, OPEN, or
  REJECTED. The historical closures (ARCH-001…ARCH-049) stand unchanged and
  their guards all pass at this HEAD.

## 3. ACCEPTED-BY-DESIGN (deliberate, guarded, not defects)

1. **Research isolation runs the other direction.** Backtest uses
   `persist_kill=False` + `persist_reconcile_state=False` + in-memory
   idempotency so research can never CLEAR or write durable production safety
   state. Paper/shadow CLI runs use separate registry-anchored DBs for
   deterministic evidence. None of these can reach a venue — pinned by the
   broker-capability rule in the structural guard.
2. **The six declared NOT-WIRED modules** (`data.provider`, `desktop.state`,
   `edge.emergency`, `edge.null_control`, `edge.placebo`,
   `regime.observatory`): production-unreachable, each exercised by a real
   test proving a property the system relies on (e.g. a detached
   `EmergencyControls` cannot arm an independent kill switch). Declared in
   their docstrings; the declaration is checked in both directions.
3. **`desktop.state` raw SQL reads** of `risk_state`/`reconcile_state`: a
   NOT-WIRED before/after diagnostic, not a second enforcement reader.
4. **Kill-switch self-test on a scratch DB** (`kill_switch_self_test`):
   proving the mechanism without halting every process; it constructs no
   engine and submits nothing.
5. **`configs/` reads are cwd-relative** by design — configuration ships with
   the install; only `data/`/`logs/` state is anchored to `state_root()`.
6. **Gate ordering**: without a real terminal, micro refuses at the
   real-environment MT5 gate before the kill-switch read — a stricter gate
   refusing first is fail-closed, and the kill refusal is proven where the
   terminal gate is satisfied.
7. **§14 known limitations**: MetaTrader5 package requires Windows (mock
   adapters elsewhere); `NO_VALIDATED_EDGE` is a research finding, enforced
   by the live gate and asserted in CI.

## 4. DEFERRED (non-blocking hygiene; no risk attached)

- **Three stale `# nosec` markers** (`demo_journal.py` B608,
  `lineage.py` B607/B603): bandit reports "nosec encountered but no failed
  test" — the underlying findings were fixed, the markers now suppress
  nothing. Cosmetic removal only; bandit exits 0 at all severities with CI
  enforcement either way.

## 5. Remaining architectural exceptions

**None.** The previously documented execution-path exception (micro) was the
last one, closed as ARCH-050/051. Every §11 forbidden duplication holds under
scan and under its structural guard.

## 6. Evidence at this HEAD

| Check | Result |
|---|---|
| HEAD | `a7b2b93`, identical to `origin/arena/01a10289-trading-system`, clean tree |
| Full suite (`-n auto --dist loadscope`) | **1,484 passed / 0 failed / 1 skipped** (playwright-only) |
| mypy | 161 source files, no issues |
| ruff (`src/ tests/ scripts/`) | all checks passed |
| bandit (all severities) | exit 0 |
| Offline static validation | 0 failed |
| CLI smoke | help / dry_run exit 0; micro exit 2 at every gate (enable flag, risk.approved, real-terminal); `qts risk kill`→`reset --confirm yes` round-trip on the canonical DB; paper simulation unaffected; refused runs leave no evidence artifact |
| CI | run `37137595827` (ARCH-050) success; run `37168141098` (ARCH-051) success; closure-audit run recorded in the register row |
