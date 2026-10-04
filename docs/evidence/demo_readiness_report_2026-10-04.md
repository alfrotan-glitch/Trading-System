# Demo Readiness Report — 2026-10-04

**Audit ID:** DEMO-READY-01
**Audited from:** HEAD `0c6d8e8` (ARCHITECTURE CLOSED), working tree reconciled with `origin/arena/01a10289-trading-system`, clean before work began.
**Delivered at:** commit `eaa49ab` (one targeted product fix + regression test; no architectural change).
**Rules observed:** architecture frozen — no refactoring, no reopened audit items; backend remains the sole authority; every safety gate preserved; only demonstrably broken/confusing surface elements touched.

---

## Verdict

### SOFTWARE: READY — with one defect found and fixed (DEMO-READY-01)
### DEMO EXECUTION ON THIS MACHINE: BLOCKED — exact blockers listed below, all environmental, none software

This split is the honest one and it is not negotiable in either direction:

- Every station of the demo workflow that can be truthfully verified **without a real MT5 terminal** was exercised against the **running product** (live FastAPI server + served UI, real HTTP, real durable SQLite state) and against the **contract-accurate fake-MT5 lifecycle suite** (148 integration tests covering submit → broker ack → position → manage → close → reconcile, plus failure modes, suspension recovery, cold start, idempotency, concurrency).
- The stations that **require a real terminal** (real broker handshake, real demo-account identity pinning, real tick freshness, real order round-trip on the broker's server) **cannot be verified from this machine**: the `MetaTrader5` package is Windows-only (documented limitation, QTS_PROJECT_CONTROL.md §14) and this audit ran on Linux. The product itself states this at every surface, which is exactly what it should do.

**No claim in this report is based on a mock pretending to be a broker.** Where the product could not know something, it said UNAVAILABLE — and after this audit, that is now true of *every* surface (see the finding).

---

## 1. Method

1. Server started from the frozen HEAD: `uvicorn qts.api.server:app` on `0.0.0.0:8000`, UI served at `/`, live preview exercised.
2. Every workflow station probed over real HTTP — reads *and* mutations (mutations pass the local-operator boundary; the audit confirmed GETs are unrestricted while POSTs are origin-gated).
3. A **genuine durable failure state** was present in the machine-local DB (`data/sqlite/qts.db`: reconcile suspension, reason "broker disconnect: MetaTrader5 package not installed…", written 2026-10-04T01:38:35 by a prior test run executed from the repo root — see §6 hygiene note). Rather than deleting it, the audit **used it** as a real failure for step-4 verification, including the recovery path.
4. The fake-MT5 integration suite was run as the contract-accurate lifecycle proof (same gate, policy, journal, and reconcile code paths as a real terminal; only the transport is injected).
5. The UI was statically audited: every JS→API path resolved against the live server; every nav target checked against exported renderers; every module parse-checked; every asset reference verified.
6. Full regression bar re-run after the fix; pushed; CI verified.

## 2. Workflow tour — station by station (live product, real HTTP)

| # | Station | Probe | Observed | Honest? |
|---|---------|-------|----------|---------|
| 1 | Startup | `GET /` | 200, UI shell served, no-store cache headers | ✔ |
| 2 | Health | `GET /api/health` | mt5 `UNAVAILABLE: MetaTrader5 package not installed … no connectivity claim is possible (mock-based connectivity evidence is not valid)`; kill switch ARMED, `source=durable:risk_state`; live BLOCKED with reasons list | ✔ |
| 3 | Connection | `GET /api/mt5` | `connected: false`; account/spec `UNAVAILABLE — no broker metadata is invented` | ✔ |
| 4 | Risk state | `GET /api/risk` | full limit table with per-limit provenance (`canonical_base` / `config_override`); `status_text: TRADING BLOCKED` with reasons | ✔ |
| 5 | Authority | `GET /api/demo/state` | `DISABLED BY POLICY`, `execution_permitted: false`, mode-gate reason verbatim, reverify TTL 120 s | ✔ |
| 6 | Gate map | `GET /api/demo/guide` | every gate with plain-language detail; suspension block names each blocker with `recoverable_by` (e.g. reconcile suspension → "a fresh broker-authoritative reconciliation reporting no drift") | ✔ |
| 7 | Readiness | `GET /api/demo/readiness` | `passed: false`, 12 blocked reasons, each check with its measured detail | ✔ |
| 8 | Preflight | `GET /api/demo/preflight` | `passed: false` with the full named-check refusal list | ✔ |
| 9 | Stage | `GET /api/demo/stage` | `HALTED`, `orders_permitted: false`, policy kill reason, actor, decided_at | ✔ |
| 10 | Safety map | `GET /api/demo/safety` | mode boundary table (DEMO_FORWARD = observation ONLY; DEMO_EXECUTION = authorized artifact + staged arming + pinned identity + fail-closed gate) | ✔ |
| 11 | Order (no intent) | `POST /api/demo/order` `{confirm:true}` | **400** — requires explicit `confirmed=true` *and* `risk_ack=true`; a wrong field name is not accepted as intent | ✔ |
| 12 | Order (full intent) | `POST /api/demo/order` `{confirmed, risk_ack}` | **409**, `allowed:false`, `state:NO_TRADE`, client_order_id issued, **every** failing gate named with its reason (authorization, mode, stage, broker order_check, stop-loss, reconciliation, trading hours, unresolved checks fail closed) | ✔ |
| 13 | Positions | `GET /api/demo/positions` | **FOUND DEFECT** (below). After fix: **503** `broker positions UNAVAILABLE — MetaTrader5 package not installed…` — never a fabricated empty list | ✔ (after fix) |
| 14 | Close | `POST /api/demo/close` | **400** `ticket is required` — no blind close path | ✔ |
| 15 | Kill engage | `POST /api/demo/kill` (reason, confirmed) | 200; durable kill with the operator's reason; stage → HALTED, `orders_permitted:false` | ✔ |
| 16 | Kill authority | next `POST /api/demo/order` | policy **re-asserted its own kill reason** over the operator label — backend, not the caller, owns the narrative | ✔ |
| 17 | Resume (recovery) | `POST /api/demo/guide/resume` | **409**, `recovered:false`; durable before/after snapshots; `recovery_checks` with per-predicate satisfied/detail; `failed_predicates:["reconciliation_verified_clean"]`; nothing cleared; blockers restated with `recoverable_by` | ✔ |
| 18 | Enable | `POST /api/demo/enable` | **409**-class refusal: authority stays `DISABLED`, mode-gate reason, full readiness echo | ✔ |
| 19 | Market data | `GET /api/observe/status`, `POST /api/observe/start` | `STOPPED` honestly; start → `BLOCKED` (no terminal); zero fabricated ticks | ✔ |

**Failure-state clarity (step 4):** every refusal above is machine-readable *and* human-actionable — each one names the failing check, the measured reason, and (in guide/resume) the exact recovery predicate. The genuine durable reconcile suspension behaved exactly as designed across process restarts: survived, blocked orders, blocked resume, and stated precisely what would clear it.

## 3. Finding DEMO-READY-01 (fixed in `eaa49ab`)

**A broker read failure was reported as a flat book.**

- `DemoSession.positions()` contained `except Exception: return []`. With the broker unreadable, `GET /api/demo/positions` answered `200 {"positions": [], "count": 0}`.
- The Trading page therefore rendered *"The broker reports no open demo positions right now"* — a fabricated certainty — while its honest branch (*"Positions unavailable … QTS could not read positions from the terminal"*) was **unreachable dead code in the exact scenario it was written for**.
- The CLI (`qts demo positions`) printed the equally false *"no open positions on DEMO venue"*.
- Consequence in a real demo session: terminal link drops with a position open → operator is told they are flat. This is precisely the UNKNOWN→GUESS fabrication class the product's provenance model exists to prevent, and it sat on the position-state station of the demo workflow.

**Fix (minimal, backend-as-authority, no new mechanism):**
1. `DemoSession.positions()` raises `RuntimeError("broker positions UNAVAILABLE: …")` instead of silently returning `[]`.
2. `GET /api/demo/positions` answers **503** with the broker reason — which *revives the UI's existing honest banner* with zero UI logic changes.
3. CLI prints `broker positions UNAVAILABLE — … (this is NOT 'no positions')` and exits 1.
4. Trading page disconnected placeholder no longer claims "No open positions"; it now reads "Positions unknown — not connected".
5. Regression test `test_positions_endpoint_fails_closed_when_broker_unreadable` pins both the session contract (raises) and the API contract (503, reason preserved). The truthful-empty case (working adapter, genuinely flat) is unchanged and still covered by the existing lifecycle tests.

## 4. Lifecycle proof (contract-accurate fake terminal)

`tests/integration/` — **148 passed, 0 failed**, including:
- `test_demo_autopilot_loop.py` — autonomous submit → ack → manage → close → reconcile loop;
- `test_demo_lifecycle_audit.py` — position inspection, manual close, deal sync, journal evidence, real-terminal defect regressions (symbol binding, TTL refresh, SL derivation);
- `test_demo_failure_modes.py` — idempotency, cold start, concurrency, kill switch, failure-closed;
- `test_suspension_recovery_lifecycle.py`, `test_reconciliation.py` — drift → suspend → recover-only-when-clean.

These run the same gate/policy/journal/reconcile code as a real terminal; only the MT5 transport is injected. They are the strongest order-path evidence obtainable without Windows.

## 5. UI audit (step 5)

- **Wiring:** all 28 UI-referenced GET endpoints resolve on the live server (0 broken); every referenced POST exists in the routers.
- **Navigation:** all 24 registered views map to existing exported renderers; no dead nav entries.
- **Integrity:** all 21 ES modules parse clean (node --check); all asset references in `index.html` exist.
- **Removals:** none beyond §3 item 4 — nothing else was *demonstrably* confusing, redundant, or broken, so per the audit rule nothing else was touched.

## 6. Hygiene note (documented, deliberately not "fixed" under freeze)

Running tests or validation scripts **from the repository root** writes machine-local state under `data/sqlite/` (`qts.db` durable suspension + audit events, `execution_reality.db`, `forward_observatory.db`, `demo_killswitch_selftest.db`). These files are gitignored and never shipped; the behavior is fail-closed (worst case: the local product instance is *more* locked, never less). It is test hygiene, not a safety defect, and changing test plumbing is out of scope under the architecture freeze. Flagged here so a future (post-freeze) item can isolate test DB paths.

## 7. Regression evidence at `eaa49ab`

| Check | Result |
|---|---|
| Full suite (`pytest -n auto --dist loadscope`) | **1484 passed / 0 failed / 1 skipped** |
| ruff (src + tests) | clean |
| mypy | 161 source files, no issues |
| bandit (CI invocation: `-c pyproject.toml -r src/qts`) | exit 0 |
| `scripts/demo_static_validation.py` | offline checks failed: 0 |
| CI on push of `eaa49ab` | see PR #6 checks (run on push; verified green before this report was accepted) |

## 8. Exact blockers for READY-to-trade (all environmental)

To run the real DEMO session, on a **Windows host** with the MT5 terminal:

1. **Install** MetaTrader 5 terminal + `pip install MetaTrader5`; log the configured DEMO account into the terminal.
2. **Mode:** start QTS with `QTS_MODE=demo_execution` (the product never switches itself).
3. **Connection:** `/api/mt5` must show the real broker/server/login; readiness checks `mt5_installed … spread_acceptable` must all pass.
4. **Identity:** record + confirm the account identity (`/api/demo/guide/record-identity`, `confirm-identity`) — pinned, DEMO-only.
5. **Reconciliation:** a fresh broker-authoritative reconciliation reporting no drift (this is also the only thing that clears a reconcile suspension — verified in §2.17).
6. **Arming:** staged arming to `STAGE_2_MIN_SIZE_ORDER` via the guide's prepare flow; kill switch cleared through the recovery path, never by editing state.
7. **Order round-trip:** minimum-size order **with stop-loss** inside declared trading hours; verify broker ack (`broker_order_id`/`position_id` captured), position visible at §2.13, safe close at §2.14, journal CLOSED row, post-close reconcile clean.

Every one of these is enforced by the product itself — the audit verified each refusal fires today, in order, with the exact reason. When the environment satisfies them, the same gates that blocked this machine are what will permit that one.

---

*Prepared under DEMO-READY-01. Architecture remains CLOSED and untouched; the single product fix is surface-honesty only and is pinned by a regression test.*
