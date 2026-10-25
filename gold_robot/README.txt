QTS Gold Robot - initial development (NOT RELEASED)

Windows / MetaTrader 5 MQL5 Expert Advisor for XAUUSD research.
Canonical EA: mt5_robot/QTS_Gold_Robot.mq5.
Execute INSTALL_ROBOT.bat only in a controlled DEMO/test environment after reviewing the source and broker settings.
The installer does NOT enable trading or enter orders.
New DEMO broker entries are locked by the strategy evidence gate; LIVE is blocked.
No profitable strategy has been independently validated. Do not fund a real account on the basis of this package.

Import notes (2026-10-25):
- Source was exported from a local Windows workspace for review.
- This research revision has NOT been compiled in MetaEditor; the listed Python source-level tests are NOT a substitute.
- Broker login was removed from the native tester runner; supply -DemoLogin <demo-id> locally only when necessary.
- This intraday research revision defaults to 1.0% per-trade risk, allows up to 2.0% as a hard configured limit, and refuses unaffordable minimum-lot or margin requirements. The M5 and near-market retest LIMIT candidate have NOT been tested in native MT5.
- The preceding $10,000 tester results do not represent an adequately validated $100-$200 account.
- Large broker datasets, tester logs, executable binaries, and research evidence are NOT included in this source snapshot.

See docs/ACCEPTANCE_CHECKLIST.md, docs/PERFORMANCE_REPORT.md and docs/IMPORT_AUDIT.md.

Intraday research choices: see docs/INTRADAY_DESIGN.md. M15 / former-stop LIMIT remains the default; M5 / retest LIMIT is an opt-in tester candidate.
