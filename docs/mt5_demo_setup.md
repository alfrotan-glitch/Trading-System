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

## Troubleshooting
- *MT5 not installed* → install terminal, `pip install MetaTrader5` in `.venv`.
- *Terminal not running* → launch MT5 terminal before QTS.
- *LIVE account supplied to DEMO* → QTS blocks — create demo account.
- *Symbol not available* → in MT5 Market Watch right-click → Show All → check XAUUSD naming (some brokers use GOLD).
- *Spread too wide* → wait for London/NY session.
