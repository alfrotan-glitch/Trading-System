# QTS Gold Robot — Windows operator guide

QTS already contains the MT5 DEMO trading engine, broker reconciliation,
a controlled autonomous DEMO strategy runner, and durable risk limits.
There is **no confirmed profitable gold strategy yet**. A running robot
does not prove profitability; LIVE orders stay locked.

## One simple launcher

1. Open **MetaTrader 5** on Windows and sign in to your **DEMO** account.
2. Double-click **`ROBOT.bat`** in `Trading-System`.
3. Choose **1** (default): the existing `scripts/run_qts.bat` desktop.
   Review account connection, risk, symbol and setup steps on Home and Demo.
4. Choose **2** only if you explicitly want an autonomous **DEMO**
   experiment that can place real orders **in the virtual demo account**.
   Type `DEMO` at the confirmation question. The launcher first runs
   `python -m qts demo verify`; it refuses to run if any required backend
   authority, registration, identity, risk, reconciliation or stage check fails.
   Only if verification passes does it call
   `python -m qts demo run --confirm --risk-ack --poll-interval 5`.
   To stop the console runner, use `Ctrl+C`. **Then check the
   open DEMO positions in MetaTrader 5:** stopping the software loop does
   not automatically guarantee positions were closed. Broker-side stops
   and manual position management remain important.

Simply double-clicking the launcher cannot submit broker orders; the
explicit second option and the backend's separate authorization are mandatory.
No research candidate is silently registered. The pre-existing approved
DEMO diagnostic policy—not a profitable strategy claim—is what drives an
authorized DEMO order. Nothing ever unlocks LIVE.

## If Python fails to start on Windows

The earlier `init_import_site: MemoryError` is an interpreter startup
failure before strategy execution. Restart Windows, close memory-heavy
programs and inspect free RAM and the Windows-managed pagefile. The
launcher catches failed Python startup and does not remove or rewrite the
private `data/raw/mt5_ticks` directory.

## Actual final product criteria

For a real-money gold bot, QTS still requires a genuinely validated
after-cost edge on previously unseen evidence, tested real broker
transaction costs and realistic latency, a bounded-risk forward DEMO
track record, and explicit owner approval. Existing negative results do
not meet these requirements. The installed workstation and the
scientific trading edge are separate deliverables.

`LIVE = LOCKED`. No guaranteed income or profit.
