# QTS Gold Autonomous Research — Operational Contract

**Status:** Research automation only. `LIVE LOCKED`. No automatic modification of Expert Advisor source, stop loss, position sizing or order permissions.

## What changed

- `QTS_AUTONOMOUS_RESEARCH.bat` is the **one-time Windows entry point**. It registers a local Windows Scheduled Task at **04:00 local computer time**, running only while the user's Windows account is signed in. It then scans existing evidence once.
- `QTS_AUTONOMOUS_RESEARCH.ps1` uses an exclusive local mutex. It does not start another Strategy Tester when `terminal64.exe` is running. It never uses remote or cloud testing agents.
- `gold_robot/research/autonomous_learning.py` scans **all** local `QTS_V2_ABLATION_EVIDENCE.zip` archives, reconciles each original MT5 HTML report against its SHA-256 and extracted figures, rejects damaged or contradictory evidence, and records content-addressed receipts backed by independent copies of the original ZIPs. Stored receipts are rederived and checked on every cycle. Reports with the same SHA-256 are imported once.
- `QTS_V2_ABLATION.ps1` can now test complete monthly windows from November 2026 onward. The original October interval is kept only for reproducing the already-inspected exploratory result.

## Why this is not an uncontrolled self-modifying trader

Historical outcomes can be overfit or cherry-picked. The agent therefore **automates the scientific loop**, not live execution: discover evidence → reconcile actual deals → retain lessons → flag unstable styles and non-additive interactions → schedule one genuinely new completed monthly comparison → record result. No result alone can grant trade permission.

A 16-arm ablation comprises four strategies times four configuration arms, **not 16 independent opportunities**. One calendar month counts once. Duplicate versions for the same month are quarantined as a reproducibility conflict. New windows are evaluated after the month has finished and cannot become unseen holdouts after they have been analyzed.

The first missing completed month is attempted before later months; being offline does not silently skip historical windows. Only two research attempts per calendar month are allowed to prevent an unattended failed installation from running indefinitely. A failed month is surfaced, not silently marked successful. Broker commission, slippage and execution conditions remain unverified when exports show zero fees. Candidate settings are research proposals, not promoted configurations.

## Local outputs

- `gold_robot/reports_local/autonomous_learning/QTS_AUTONOMOUS_STATUS.json`: evidence counts, rejected ZIPs, competing period reports, each strategy's historical per-arm outcomes, learned flags, next monthly test.
- `gold_robot/reports_local/autonomous_learning/evidence/<SHA-256>.json`: validated summary receipt, regenerated and cross-checked against the original ZIP every cycle.
- `gold_robot/reports_local/autonomous_learning/archives/<SHA-256>.zip`: preserved original evidence archive used to validate those receipts.
- `gold_robot/reports_local/autonomous_learning/attempts.json`: bounded native testing attempts.
- `gold_robot/reports_local/revised_comparison/autopilot_*/QTS_V2_ABLATION_EVIDENCE.zip`: new original native monthly proof; never discard the original ZIPs.

## Deployment limits

The GitHub repository cannot itself install a scheduled task on the owner's PC. After pulling `main`, the user must **double-click `QTS_AUTONOMOUS_RESEARCH.bat` once** on the Windows machine. Python 3, working local WMMarkets MT5 Strategy Tester, sufficient history and storage, and a signed-in Windows session are prerequisites. Windows may reject Task Scheduler registration under local policy; if so, automatic execution is not active. Scheduled runs are local only; no uploads to external systems.

**The next uninspected complete calendar month is November 2026, which cannot be fully backtested until December 1, 2026.** Existing October ZIPs are imported immediately if still present under the revised-comparison reports folder. If no new month exists, the cycle reviews evidence without needlessly rerunning old backtests.

Production promotion still requires genuine out-of-sample replication across independent months, measured broker costs, risk constraints (particularly legal lot sizing at USD 100–200), native Windows compile and controlled authorization. A positive monthly return or `CI green` is not sufficient.


## Evidence compatibility and integrity recovery

The new verifier **requires the original native `QTS_1.htm`, `QTS_3.htm`, `QTS_7.htm` and `QTS_8.htm` report for each of the four ablation arms**, plus the original deal CSVs and JSON records. Older ZIPs that did not preserve these HTML reports are rejected instead of being represented as fully verified evidence. Preserve the old ZIPs; do not overwrite or relabel them as new out-of-sample data. Recreate missing original reports with a fresh explicitly exploratory native run when appropriate.

Old journal receipt JSON files without independently preserved original ZIPs, as well as edited receipts or damaged ZIP copies, are reported under `rejected_evidence` and excluded from learned results. A journal integrity problem sets `JOURNAL_INTEGRITY_BLOCKED`, clears `next_monthly_test`, and stops unattended Strategy Tester launches. Restore the unaltered original report ZIP and regenerate the journal in an **isolated recovery folder**; never silently delete or overwrite suspect records.

The copied original ZIPs consume additional local disk space. They live under `reports_local` and are not part of the tracked GitHub source release.
