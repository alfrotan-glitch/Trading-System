# MT5 Demo Setup — Real Terminal + Demo Account
Version 2026-09-16

## Goal
Connect **real** MT5 terminal + **real** DEMO account + **real** market data, but **no real money** — for `DEMO_FORWARD` mode (labeled DEMO, never LIVE).

## Install MT5
1. Download from your broker (e.g., ICMarkets, Pepperstone) — choose *Demo* installer.
2. Install to `C:\Program Files\MetaTrader 5\terminal64.exe` (or note your path).
3. Open MT5 → File → Open an Account → pick broker Demo server → create demo login/password.

## Verify Account is DEMO
- In MT5: File → Login → check server name contains `Demo`.
- In QTS Demo Forward → MT5 Demo Connection Checker → check *Account is DEMO* must be ✓. If it shows LIVE, QTS blocks demo_forward.

## Configure QTS (No Secrets in Repo)
Set via Windows Credential Manager or `.env` (gitignored, never commit):

| Variable | Example | Where |
|----------|---------|-------|
| `QTS_ENV` | `demo_forward` | `.env` or `scripts\run_qts.bat` env |
| `QTS_MT5_MODE` | `REAL` for demo_forward (MOCK for paper) | env |
| `MT5_LOGIN` | `1234567` | Credential Manager or `.env` |
| `MT5_PASSWORD` | `***` | Credential Manager or `.env` |
| `MT5_SERVER` | `ICMarkets-Demo` | `.env` |
| `QTS_MT5_PATH` (or `MT5_PATH`) | `C:\Program Files\MetaTrader 5\terminal64.exe` | Setup Wizard (saved via **Save Setup** to `data/setup/mt5_setup.json`, gitignored; sent per-click with **Test MT5 Connection**) or `.env` |
| `QTS_MT5_SYMBOL` | broker's actual symbol, e.g. `XAUUSD@` | Setup Wizard field or `.env` (default `XAUUSD`) |
| `QTS_MT5_SYMBOL_MAP` | `XAUUSD=XAUUSD@` | `.env` — maps requested symbol to broker symbol |

**.env example** (copy from `.env.example`, never commit):
```
QTS_ENV=demo_forward
QTS_MT5_MODE=REAL
MT5_LOGIN=1234567
MT5_PASSWORD=your_demo_password
MT5_SERVER=ICMarkets-Demo
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
QTS_MT5_SYMBOL=XAUUSD@
```

Or use PowerShell to set env for session:
```powershell
$env:QTS_ENV="demo_forward"; $env:MT5_LOGIN="123..."; .\scripts\run_qts.bat
```

**Do NOT** put live passwords in `configs/live.yaml` and commit — it is gitignored. See `docs/10-security-model.md`.

## Connect Wizard (14 Checks)
The readiness gate calls `mt5.initialize(path=...)` itself (path: wizard field →
`QTS_MT5_PATH` → `MT5_PATH` → auto-detect) because MetaTrader5 returns
`None` from `terminal_info`/`account_info`/`symbol_info` until `initialize()`
succeeds **in the same process** — importing the package is not enough.
Initialize failure is fail-closed: it blocks with `last_error()` surfaced, never mocked.
Symbol checks use the broker's actual name (`QTS_MT5_SYMBOL`/`QTS_MT5_SYMBOL_MAP`,
e.g. `XAUUSD@`) and `symbol_select` before querying.

## Canonical timestamp contract (ticks / observations)

MT5 stamps ticks and bars in **trade-server local time** (e.g. WMMarkets-Demo
≈ UTC+3) and the Python API exposes no server-time/offset call. QTS canonical
time is **true UTC**. `MT5Adapter.ticks()` therefore normalizes
`event_time = broker_stamp − measured_server_offset`, where the offset is
**measured, never guessed**: the forming M1 bar gives
`server_now ∈ [bar_time, bar_time+60)`, and since every real-world UTC offset
is a multiple of 15 minutes, that 60-second window contains at most one grid
point — a match recovers the offset exactly (`offset_basis=measured-m1-bar`).
No grid point (market closed/frozen series) → no measurement is invented: the
legacy same-basis fallback (`offset_basis=assumed-utc-fallback`) applies and
`MarketDataProvider`'s unchanged future/stale validation loudly rejects
server-basis stamps. Garbage timestamps fail closed (never fabricated).
Every `Tick` carries `provenance` (raw `mt5_time`/`mt5_time_msc`, offset,
basis, broker symbol, receipt time) and `ObservationTick.from_domain_tick`
persists that basis (`timestamp_basis`, `broker_time_raw`,
`server_utc_offset_s`, `broker_event_time`) so stored observations are
auditable. Offsets are cached per symbol for 300s (they only shift on DST);
during a DST transition the unchanged validation fails closed until the
re-measurement.

Config precedence (readiness AND demo-enablement resolve identically):
request/wizard param → saved wizard file (`QTS_SETUP_FILE`, default
`data/setup/mt5_setup.json`) → `QTS_MT5_PATH`/`QTS_MT5_SYMBOL` env →
`MT5_PATH` env → auto-detect. The wizard store is credential-free:
login/password/server are rejected and never persisted — use
`QTS_MT5_LOGIN`/`QTS_MT5_PASSWORD`/`QTS_MT5_SERVER` (legacy unprefixed
`MT5_*` names still accepted as fallback).

In QTS: **Setup Wizard → Test MT5 Connection** or **Demo Forward → Refresh Checks** runs:

1. MT5 installed? 2. Terminal running? 3. Account connected? 4. Account is DEMO? 5. Broker identified? 6. Symbol available? 7. Symbol tradable? 8. Symbol spec valid? 9. Market data fresh? 10. Bid/ask valid? 11. Spread acceptable? 12. Account state valid? 13. Risk config valid? 14. Reconciliation healthy?

Only after all ✓ is *Demo Execution Enabled* allowed. Blocked reasons shown explicitly.

## Account authority (explicit limitation)

`MT5Adapter.account()` returns broker-authoritative balance/equity/margin with
`source="BROKER"`. Two explicit honesty rules:

* `updated_at` is the LOCAL RECEIPT time. The MT5 Python API exposes no
  server timestamp on `account_info()`, so account freshness is bounded by
  receipt time — it is never presented as broker event time.
* `leverage` and `currency` are `None` (= UNAVAILABLE) when the broker does
  not provide them. They are never substituted with defaults; consumers that
  need them (e.g. margin pre-checks) fail closed with an explicit
  UNAVAILABLE reason instead of computing against a guessed value.

Unknown account equity vetoes orders (`ACCOUNT_STATE_UNAVAILABLE`) — the
`equity → 10000` fallback that once fabricated the leverage-check denominator
was removed.

## DEMO FORWARD vs LIVE

- DEMO_FORWARD promotion requires a **passed** readiness report (14/14) plus a
  successful order-placement dry run; LIVE stays disabled by policy.
- Promotion ladder is one-way: `OBSERVE_ONLY -> DEMO_FORWARD -> LIVE (disabled by policy)`.
- Demo execution order flow: `validate -> plan -> preflight -> gate -> submit -> poll-fill -> reconcile`.
- Kill switch: `qts risk kill` halts new order submission independently of the desktop UI.
- Symbol contract size: QTS `SymbolSpec.contract_size` maps from MT5
  `SymbolInfo.trade_contract_size` (the real MT5 object has **no**
  `contract_size` attribute; pinned by `tests/test_mt5_boundary_contract.py`).

## OBSERVE-ONLY runtime collection (REAL ticks, ZERO orders)

DEMO readiness passing proves the terminal is connected; it does **not** prove
ticks are flowing *now*, and historical `recent_demo` JSON records are never
treated as proof of current observation. The OBSERVE-ONLY runtime closes that
gap:

| Endpoint | Effect |
| --- | --- |
| `POST /api/observe/start` | Runs the 14-check DEMO readiness gate, resolves the symbol from the saved wizard config (`XAUUSD` -> broker `XAUUSD@`), starts ONE `ObservationCollector` polling `MarketDataProvider.get_tick()` at a controlled interval (default 1s, `QTS_OBSERVE_INTERVAL_S`), and persists every accepted tick through `ForwardObservatory.record_tick()` into `data/sqlite/forward_observatory.db`. |
| `GET /api/observe/status` | `OBSERVING` / `STOPPED` / `BLOCKED` / `STOPPED_ON_ERRORS`, tick count, last tick time (UTC), symbol, timestamp basis, last validation error, session id, `orders_submitted: 0`. |
| `POST /api/observe/stop` | Deterministic: signals the poll thread, joins it, persists `end_session`, rewrites the evidence manifest. |

Safety properties (pinned by `tests/test_observe_only_collector.py`):

- **Zero orders.** The collector's only broker touchpoint is `get_tick()`.
  An AST scan of the collector module and the observe endpoints proves no
  `order_send` / order-submission / simulation call exists on any path; the
  test MT5 double additionally raises `AssertionError` from `order_send` as
  a runtime sentinel.
- **Readiness-gated.** `start()` refuses and records state `BLOCKED` unless
  the readiness report says `passed: true` — fail-closed.
- **Idempotent.** A duplicate start returns the existing session; there is
  never more than one collector thread or open session. A restart after a
  completed stop creates a NEW session (never resumes a closed one).
- **Only REAL data.** Every tick flows through the unchanged validation path
  and the canonical timestamp contract (`Tick.provenance` -> `ObservationTick`
  broker fields). The observatory's simulation helper is not referenced by
  this runtime path; fixtures cannot enter it.
- **Fail-closed.** Terminal disconnect (`get_tick` errors), stale quotes,
  conversion failures and symbol loss all count as consecutive failures;
  after `max_consecutive_failures` the collector stops itself
  (`STOPPED_ON_ERRORS`) and persists the session end. Repeated identical
  quotes (unchanged raw MT5 stamp — a dead feed) are recorded once and
  counted as `duplicates_skipped`, never fabricated into new observations.
- **Evidence.** `data/evidence/forward_observation_manifest.json` is
  regenerated from the actually-stored session rows with `class: "REAL"`,
  `orders_submitted: 0`, the audited timestamp bases and spread/event-time
  ranges.

Desktop UI: the **DEMO FORWARD & EXECUTION** card exposes *Start Observation
(No Orders)*, *Stop Observation* and *Refresh Status*, with a live status
panel refreshing every 5s while `OBSERVING`.

## Troubleshooting
- *MT5 not installed* → install terminal, `pip install MetaTrader5` in `.venv`.
- *Terminal not running* → launch MT5 terminal before QTS.
- *LIVE account supplied to DEMO* → QTS blocks — create demo account.
- *Symbol not available* → in MT5 Market Watch right-click → Show All → check XAUUSD naming (some brokers use GOLD).
- *Spread too wide* → wait for London/NY session.
