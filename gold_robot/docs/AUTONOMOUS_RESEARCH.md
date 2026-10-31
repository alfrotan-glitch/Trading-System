# QTS Gold Autonomous Research — Operational Contract

**Status:** Research automation only. `LIVE LOCKED`. No automatic modification of Expert Advisor source, stop loss, position sizing or order permissions.

## What changed

- `QTS_AUTONOMOUS_RESEARCH.bat` is the **one-time Windows entry point**. It registers a local Windows Scheduled Task at **04:00 local computer time**, running only while the user's Windows account is signed in. It then scans existing evidence once.
- `QTS_AUTONOMOUS_RESEARCH.ps1` uses an exclusive local mutex. It does not start another Strategy Tester when `terminal64.exe` is running. It never uses remote or cloud testing agents.
- `gold_robot/research/autonomous_learning.py` scans local `QTS_V2_ABLATION_EVIDENCE.zip` archives, validates native deals and matched test settings using the existing four-arm parser, rejects damaged/contradictory evidence, and records content-addressed immutable receipts. Reports with the same SHA-256 are imported once.
- `QTS_V2_ABLATION.ps1` can now test complete monthly windows from November 2026 onward. The original October interval is kept only for reproducing the already-inspected exploratory result.

## Why this is not an uncontrolled self-modifying trader

Historical outcomes can be overfit or cherry-picked. The agent therefore **automates the scientific loop**, not live execution: discover evidence → reconcile actual deals → retain lessons → flag unstable styles and non-additive interactions → schedule one genuinely new completed monthly comparison → record result. No result alone can grant trade permission.

A 16-arm ablation comprises four strategies times four configuration arms, **not 16 independent opportunities**. One calendar month counts once. Duplicate versions for the same month are quarantined as a reproducibility conflict. New windows are evaluated after the month has finished and cannot become unseen holdouts after they have been analyzed.

Only two research attempts per calendar month are allowed to prevent an unattended failed installation from running indefinitely. A failed month is surfaced, not silently marked successful. Broker commission, slippage and execution conditions remain unverified when exports show zero fees. Candidate settings are research proposals, not promoted configurations.

## Local outputs

- `gold_robot/reports_local/autonomous_learning/QTS_AUTONOMOUS_STATUS.json`: evidence counts, rejected ZIPs, competing period reports, each strategy's historical per-arm outcomes, learned flags, next monthly test.
- `gold_robot/reports_local/autonomous_learning/evidence/<SHA-256>.json`: immutable summary receipt for each validated ZIP.
- `gold_robot/reports_local/autonomous_learning/attempts.json`: bounded native testing attempts.
- `gold_robot/reports_local/revised_comparison/autopilot_*/QTS_V2_ABLATION_EVIDENCE.zip`: new original native monthly proof; never discard the original ZIPs.

## Deployment limits

The GitHub repository cannot itself install a scheduled task on the owner's PC. After pulling `main`, the user must **double-click `QTS_AUTONOMOUS_RESEARCH.bat` once** on the Windows machine. Python 3, working local WMMarkets MT5 Strategy Tester, sufficient history and storage, and a signed-in Windows session are prerequisites. Windows may reject Task Scheduler registration under local policy; if so, automatic execution is not active. Scheduled runs are local only; no uploads to external systems.

**The next uninspected complete calendar month is November 2026, which cannot be fully backtested until December 1, 2026.** Existing October ZIPs are imported immediately if still present under the revised-comparison reports folder. If no new month exists, the cycle reviews evidence without needlessly rerunning old backtests.

Production promotion still requires genuine out-of-sample replication across independent months, measured broker costs, risk constraints (particularly legal lot sizing at USD 100–200), native Windows compile and controlled authorization. A positive monthly return or `CI green` is not sufficient.
