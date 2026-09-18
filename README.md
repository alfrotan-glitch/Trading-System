# QTS — Quant Trading System

> **Safe by default. Science first. Capital preservation over profit.**

QTS is a desktop research and trading platform for XAUUSD (gold) on MetaTrader 5 — built so a non-technical user can **clone, install, double-click, connect a DEMO account, and observe markets** without accidentally risking real money. It never claims a profitable edge and never hides failed experiments.

---

## What is QTS?

A modular desktop app with a local FastAPI backend + native window (pywebview) that lets you:

- Manage market data with provenance (where every bar/tick came from)
- Run bounded research campaigns (every trial logged, no hidden trials)
- Validate strategies with strict scientific gates (DSR, PBO, PSR, costs, regime, perturbation, null/placebo)
- Paper-trade (simulated), shadow-trade (would-be), and **demo-forward trade** (real MT5 demo) — all compared automatically
- See everything in a clean desktop UI with audit, risk, reconciliation, and live-lock
- Work inside a coherent 8-area interface (Overview · Research · Market · Trading · Risk · Evidence · System · Governance) with a command palette (`Ctrl+K`), a guided setup journey, and honest states everywhere — `UNAVAILABLE` is never shown as `0`, and LIVE is always visibly LOCKED. See `docs/ui_design_system.md`

## What does it do?

1. **Data Observatory** — what data you have, what’s missing, which external source can fill it, historical depth needed, execution realism.
2. **Research Lab** — generate falsifiable hypotheses, run 11-step autonomous campaigns, track failures, prevent rediscovery. Includes the pre-registered **impulse-continuation event study** (`qts research impulse` — research-only, fail-closed data-adequacy gate, Holm/DSR multiple-testing penalties, locked test never touched; see `docs/research/impulse_continuation_report.md`).
3. **Validation** — walk-forward, purged CPCV, costs 1.0/1.5/2.0×, slippage, regime, null/placebo, expectancy — only survivors become candidates.
4. **Forward Observation** — runs live market data without capital, recording quotes/spreads/signals/NO_TRADE/hypothetical fills.
5. **Execution & Risk** — order lifecycle INTENT→RISK→SUBMISSION→ACCEPTED→FILLED/REJECTED, hard limits, kill switch, reconciliation.
6. **Evidence** — every decision in `data/evidence/*.json` + SQLite + audit log, PROMOTION is one-way, no skip.

## Does it automatically trade?

**No.** Default is `BLOCK — KEEP NO_TRADE`. Live trading is **LOCKED** until *all* of DSR, PBO, PSR, cost, regime, perturbation, null/placebo, forward evidence, reconciliation, risk, and human approval pass. Even then you must explicitly `--confirm live`.

## What is Paper? Shadow? Demo Forward? Live?

| Mode | Broker? | Real Money? | Label | Purpose |
|------|---------|-------------|-------|---------|
| **Paper** | No — next-bar-open simulation | No | PAPER | Estimate fills with conservative spread/slippage |
| **Shadow** | No — would-be intents | No | SHADOW | Check what *would* have been sent, measure risk/spread vetoes |
| **Demo Forward** | **Yes — real MT5 terminal + demo account + market data; observation only** | No | **DEMO** | Measure ticks/provenance and hypothetical divergence; zero orders |
| **Live** | Yes — real account | **Yes** | LIVE | **LOCKED** — requires everything to pass |

`DEMO` results are **never** automatically promoted to `LIVE`.

## Why is Live locked?

System defaults to `BLOCK — KEEP NO_TRADE`. The current repository fixture is explicitly `SYNTHETIC`, claim-ineligible, and only supports labelled mechanism validation. Dataset-specific DSR/PBO/PSR/cost values are shown only when their trial-bound evidence is present; missing controls, cost decomposition, forward divergence, reconciliation, or risk evidence remain `UNAVAILABLE`/`INSUFFICIENT_EVIDENCE` and block promotion. See `data/evidence/edge_validation.json` and `docs/release_readiness_report.md` for current blockers.

## How do I install on Windows? (Clean Clone)

**Prerequisites:** Windows 10/11, Python **3.11/3.12/3.13** (3.14 not yet verified — see `pyproject.toml` and `docs/desktop_installation_windows.md`), git

```powershell
git clone <repository-url>   # your fork
cd Trading-System
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1
# or double-click: scripts/setup_windows.bat
```

This creates `.venv`, installs `qts`, runs **`qts data bootstrap`** (deterministic, fail-closed, idempotent — establishes a usable dataset from the tracked fixture, labeled `SYNTHETIC`; never fabricates data), validates the CLI + health, and runs quick tests. If Python/git is missing, or no usable dataset can be established, setup fails clearly with a non-zero exit code.

See `docs/desktop_installation_windows.md`.

## How do I launch?

**One-click:** double-click `QTS.exe` after building, or run:

```bat
scripts/run_qts.bat          # launches desktop (development/MOCK)
scripts/run_tests.bat        # pytest
scripts/build_windows.bat    # builds dist/QTS.exe
```

PyInstaller build: `pyinstaller packaging/qts.spec --clean --noconfirm` → `dist/QTS.exe` (standalone, no repo path needed). See `docs/desktop_installation_windows.md`.

Desktop shows: Home (System Status, Environment, MT5, Account Type, Market Data, Risk, Reconciliation, Strategy, Current Decision, Live Lock) → Dashboard → Research → Forward → Execution → Risk → MT5 → Audit → Live (LOCKED).

## How do I connect MT5 Demo?

1. Install MT5 terminal, open a **DEMO** account (never live for demo_forward).
2. Launch QTS → **Setup Wizard** → set MT5 terminal path `C:\Program Files\MetaTrader 5\terminal64.exe` and symbol `XAUUSD`.
3. Set credentials via Windows Credential Manager or `.env` (never plain repo): `QTS_MT5_LOGIN`, `QTS_MT5_PASSWORD`, `QTS_MT5_SERVER`. See `docs/mt5_demo_setup.md`.
4. **MT5 Demo Connection Checker** (Setup Wizard → Test MT5 Connection or Demo Forward view) runs 14 checks: MT5 installed, terminal running, account connected, account is DEMO, broker, symbol available/tradable/spec valid, market data fresh, bid/ask valid, spread acceptable, account state, risk config, reconciliation. Only after all pass may DEMO_FORWARD observation start; this never enables DEMO_EXECUTION.

## How do I start observation?

- **Observe Only** (safe, no orders): Demo Forward → *Start Observation*. Requires all 14 readiness checks to pass; then records real MT5 demo-account observations as provenance class `DEMO` with full provenance into the **canonical observation store** (`data/sqlite/forward_observatory.db`) bound to an audited session (environment, broker, symbol, timestamp basis, code version). `data/evidence/forward_observation_manifest.json` is a derived, regenerable export and is never `REAL`-money evidence.
- Observation is physically order-free: the observe runtime has no order path at all (structurally pinned by tests).
- **DEMO execution is disabled by product policy.** A readiness pass never creates order permission; `/api/demo/enable` returns a durable 409 refusal after optional diagnostic probing and does not write an enabled state. Direct authority calls are refused too. The only broker-facing product path is DEMO_FORWARD observation with zero orders.
- Fabricated legacy "demo observations" were quarantined to `data/evidence/quarantine/` with documented violations; they satisfy no gate and no claim.

## Why is demo execution disabled?

This workstation intentionally stops at `DEMO_FORWARD/OBSERVE_ONLY`: a fresh readiness report can authorize recording real MT5 demo-account observations, but it cannot authorize an order path. `/api/demo/enable` is a durable 409 refusal, and `LIVE` remains separately locked. See `docs/demo_forward_protocol.md` for the observation contract.

## How do I stop it?

- Close desktop window → clean shutdown (audit persists, pending orders reconciled on restart).
- Or kill switch in Risk view → `TRADING SUSPENDED`.

## Where are logs & evidence?

- Logs: `logs/audit.jsonl` (redacted) + `data/sqlite/qts.db` audit_events
- **Canonical observation store**: `data/sqlite/forward_observatory.db` (provenance-first; sessions carry environment/broker/symbol/timestamp-basis/code-version identity)
- Derived exports: `data/evidence/*.json` — always regenerable from canonical stores, never gate-satisfying by existing
- Quarantine: `data/evidence/quarantine/` — fabricated/mismatched legacy records, excluded from all claims (see its README)
- Config: `configs/dev.yaml`, `configs/paper.yaml`, `configs/demo_forward.yaml`; `configs/live.yaml` **never committed** (use `.example`)

## Canonical authorities (read this before touching limits/modes/gates)

- **Mode**: `qts.domain.modes` — DEVELOPMENT / PAPER / SHADOW / DEMO_FORWARD / DEMO_EXECUTION / LIVE; unknown selections fail closed
- **DEMO execution policy**: `qts.lifecycle.demo_authority` — `DEMO_EXECUTION = DISABLED BY POLICY` today; one durable refusal/history boundary is retained for future explicit authorization; direct enablement and API/UI/execution order permission are unreachable
- **Risk limits**: `qts.risk.authority` — one canonical set; mode restrictions may only tighten; every snapshot carries a config hash
- **Broker metadata**: `qts.adapters.mt5_adapter` — alias-resolved, zero defaults, fail-closed
- **Metrics**: `qts.domain.provenance.MetricValue` — MEASURED or UNAVAILABLE/INSUFFICIENT_EVIDENCE, never a placeholder zero
- See `docs/canonical_authorities.md` for the full contract.

## What should never be changed manually?

- `data/sqlite/qts.db` promotion / kill switch (use UI/CLI)
- `data/evidence/*.json` while QTS running (evidence is audit trail)
- `N` trial count — never reset (DSR depends on it)
- `LIVE` gates — no DB edit, no config override without `env=live --confirm live`
- Secrets in repo — use OS env / credential store

---

## For Developers: Technical Quickstart

```bash
python -m venv .venv && source .venv/bin/activate  # or scripts/setup_windows.ps1
pip install -e ".[dev]"
python -m qts data bootstrap   # deterministic, fail-closed, idempotent; labels the fixture SYNTHETIC
python -m qts data synthetic --rows 10000 --out data/raw/synthetic_XAUUSD_1m.csv
python -m qts data ingest --source csv --path data/raw/synthetic_XAUUSD_1m.csv --instrument XAUUSD --timeframe 1m
python -m qts backtest --strategy sma_breakout --data-version <version> --seed 42 --determinism-check
python -m qts validate --strategy sma_breakout --data-version <version>
pytest -q
python -m qts.health
```

Docs start `docs/00-overview.md` → `docs/13-adrs.md`. Build exe: `scripts/build_windows.bat`.

## Current Status

`BLOCK — KEEP NO_TRADE`, Live LOCKED. Test and static-check counts are run-dependent and are not treated as research evidence. LIVE gate evidence is tiered (structural / integration / real-environment); MT5 connectivity passes only with a REAL terminal — mock-based connectivity evidence is banned. `data/curated/` and `data/manifests/` are deliberately **not tracked** — a clean clone establishes its dataset via `qts data bootstrap` (truthful provenance, `SYNTHETIC` label). Remaining limitations in `docs/release_readiness_report.md` K.

Never treat BACKTEST/PAPER/SHADOW/DEMO as LIVE. No profitability claimed.
