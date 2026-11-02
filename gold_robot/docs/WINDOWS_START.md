# QTS Gold | Windows Operator Guide

Canonical repository: alfrotan-glitch/Trading-System (`main`).
Canonical MT5 Expert Advisor: `gold_robot/mt5_robot/QTS_Gold_Robot.mq5`.
Supported target: WMMarkets MetaTrader 5, `XAUUSD@`.

**Safety status: LIVE LOCKED. No independently validated after-cost profitable edge.**
All native Strategy Tester orders are simulated. Connecting a DEMO account does
not itself authorize forward trading. Real-money orders remain forbidden.

## One-click automatic research testing

Double-click **`START_HERE.bat`** in the repository root. This is the supported
daily Windows entry point; the other root `QTS_*.bat` launchers are maintained
as technical/research compatibility tools, not separate production robots.

| Menu | Action |
| --- | --- |
| 1 | Retest vs Sweep/Reclaim: native MT5 real-tick tests of Styles 1 and 3 |
| 2 | Full native tests of ten independent styles: 0-8 on M15, Style 9 on M1 |
| 3 | Install/update the single canonical MT5 Expert Advisor |
| 4 | Open the most recent saved native tester HTML summary |
| 5 | Generate a local broker/installation readiness report |
| 6 | Advanced tools: presets, V4 decision diagnosis, post-stop data, saved-report comparison, research desktop |
| 8 | **Owner Verdict:** immediate offline review of saved historical results; no new MT5 session or broker orders |
| 7 | Exit |

**First-time install:** Install the broker's Windows MT5 terminal, sign in to
a WMMarkets DEMO account and close MT5 before running installation or unattended
native Strategy Tester jobs. Choose menu 3, verify zero MetaEditor compilation
errors, and use menu 5 to inspect readiness and broker restrictions.

**Run comparison:** Choose menu 1. Historical positive results for Style 1
(Retest) and Style 3 (Sweep/Reclaim) are research candidates, not approved
winners. The same installed canonical EA, broker, real-tick model and configured
date window are used for both. Missing trades, zero fills, incomplete quotes
or non-reconciled broker fees must be treated as incomplete evidence.

**Run all styles:** Choose menu 2. The native runner handles the fixed styles,
adaptive router and SMC on M15 plus the separately configured M1 scalp style.
The sample period defaults to the last six completed calendar months.
This is a research screen; previously examined months are NOT an untouched
holdout. A fresh out-of-sample/forward period is required before selecting
the strongest strategy.

## Immediate owner verdict — no waiting, no trading

From `START_HERE.bat` choose **8**, or double-click
`QTS_OWNER_VERDICT.bat`. It produces:

- `gold_robot/reports_local/owner_decision/QTS_OWNER_VERDICT.html`
- `gold_robot/reports_local/owner_decision/QTS_OWNER_VERDICT.json`

This is **immediate and offline**: no MT5 connection, historical tick download,
Strategy Tester, continuous laptop uptime, broker login, cloud agents, or
orders. It reconciles the *documented* eight-style April–October 2026
native report (938 completed positions in eight **separate simulations**)
with seven existing 365-day research summary verdicts and the canonical
release status. It displays previously positive Retest (Style 1) and
Sweep/Reclaim (Style 3) as **exploratory only**, never approved winners.
Older source reports lack verified all-in broker costs and an independently
unseen current-build native holdout. A fail-closed source inconsistency
creates NO-GO rather than inventing a new performance result.

This dashboard deliberately does **not** interpret private, unverified
`reports_local` broker HTML/CSV as proved outcomes: it counts their available
files and leaves independent reconciliation outstanding. A generated page
is a summary of already saved research, **not a new backtest** and not a
promise of profitable live trading. It does not replace future legitimate
out-of-sample MT5 testing; it does remove the pointless requirement to wait
days for a new signal just to read existing findings.

## Native tester evidence and interpretation

Every automatic run creates its own unique directory at
`gold_robot/reports_local/auto_runs/<timestamp>/` with `OPEN_RESULTS.html`,
`OPEN_RESULTS.json`, simulator reports and, when valid, native broker-deal CSVs.
Evidence ZIP packaging is pinned to that exact run. Failed or incomplete
runs do NOT borrow files from a previous run. `QTS_SHARE_RESULTS.bat` can be
used separately to package existing research, with its own source disclosure.

The MT5 tester uses **Every tick based on real ticks** for `XAUUSD@` and a
research-only simulated USD 3,000 initial balance. This balance does not
establish the broker's minimum real deposit. The usual research presets
limit per-trade risk to 0.50%. Tester-only flags may intentionally bypass
daily equity stops for an opportunity census; never interpret that as an
operationally safe/live configuration. Re-run any candidate with ordinary
risk stops enabled and broker costs reconciled.

Treat every positive backtest as exploratory until real bid/ask history,
execution fees, commissions, swap, slippage, drawdown, minimum tradable
volume, sufficient sample size and independent holdout have been examined.
An SL followed later by the original TP is NOT proof that widening the
original SL would have been profitable. Unknown quote windows remain UNKNOWN.

## Automatically audit SAVED historical Retest/Sweep runs (READ ONLY)

Do **not** repeat the Strategy Tester and do **not** paste any ZIP paths.
Open the existing WMMarkets **DEMO** terminal and double-click
`START_HERE.bat`. Select **6 (Advanced) > B (Auto-review saved runs)**.

QTS automatically discovers `QTS_SHARE_RESULTS.zip` inside the existing
`gold_robot/reports_local/auto_runs/*/` folders and any
`QTS_HOLDOUT_REVIEW.zip` inside `reports_local/holdout_*/`.
Only native **baseline** `XAUUSD@`/M15 real-tick Style **1 and 3** runs
with matching broker evidence are studied. It does not run another MT5 test,
change the EA, write broker orders, or upload private account information.

The output opens automatically in Notepad:

`gold_robot/reports_local/context_auto/QTS_CONTEXT_AUTO_SUMMARY.json`

Each unique archived run also has its own `QTS_CONTEXT_<hash>.json` report
in the same folder with individual entry-time closed H1 EMA trend,
closed M15 ATR, and historical Bid/Ask spread. The original ZIPs are untouched.

A second report is generated automatically from the **same saved run data**:

`gold_robot/reports_local/context_auto/QTS_SHADOW_FILTER_REVIEW.json`

It compares the unchanged Style 3 baseline to two **POST-HOC, read-only**
counterfactual subsets: (1) retain only entries with M15 ATR at or below
its trailing median; (2) omit BUY entries when ATR is above its median.
It includes per-period retained position counts, wins, native profit,
hypothetical extra costs of $10/$20 per lot, excluded positions, and
monthly descriptive P/L. Original EA orders, risks and .set files are
never modified; the program does not send signals or broker orders.

**Important:** These rules were suggested AFTER inspecting the historical
data. Retaining only historical fills is *not* a replacement Strategy
Tester replay, and changes to capital, ordering or overlapping positions
are unmeasured. A positive hypothetical filtered P/L does not verify
future profitability. The report's `approval` is always
`NOT_APPROVED_POST_HOC`, `validated_edge` is false, and `LIVE` stays
`LOCKED`. A future prospective DEMO evaluation would need separate,
unchanged preregistered rules and broker-cost evidence.

**Fail-closed behavior:** missing broker data, incomplete/open positions,
mixed or expert exits with missing evidence, and multiple conflicting
ledgers for the same historical period are marked **NO-GO**. Duplicate
identical archives are never counted twice. No eligible ZIP is also NO-GO.
Incomplete-position gains are not silently counted as verified P/L.

Reports remain **historical descriptive research only**, even if a
subgroup appears profitable. Independent future DEMO trading and verified
broker execution costs are required before any profitability claim.
Current live permission remains **LOCKED**.

## Automatic Forward Shadow | one chart, both styles, never orders

**Operator workflow: one initial double-click on QTS_AUTO_FORWARD.bat.**
For an already-running older QTS reporting loop, use the dedicated
`QTS_REFRESH_FORWARD.bat` update entrypoint. It identifies the exact older
`StartAutoForwardShadow.ps1` PowerShell command, stops **only that QTS
research process** (not terminal64.exe or any other EA), fast-forwards main,
and requests the new supervisor. It reports
`REFRESH_REQUESTED_NOT_YET_VERIFIED` until the NEW supervisor independently
checks its native DEMO heartbeat and analysis results. Ambiguous processes,
local Git conflicts or missing installation fail closed with local reports.

The refreshed supervisor no longer loops indefinitely over a failed report:
a hard NO-GO gets at most **three** analysis cycles and then stops the
research process, leaving MT5 untouched. Windows logon auto-start is
registered **only after BOTH analysis tools complete without NO-GO**; a
native heartbeat alone is not sufficient evidence of operational readiness.

No manual chart setup, Python commands, ZIP selection, tester reruns, or broker
login prompts. Main menu **6 > C** starts the same automatic supervisor.

The unattended supervisor does the following, in order:
1. Detect exactly one eligible MT5 installation. A previously installed QTS
   robot identifies the correct terminal only when unambiguous.
2. Compile/install the canonical EA using that terminal's native MetaEditor.
   An absent, stale or invalid EX5 is always **NO-GO**.
3. Generate the built-in MT5 Startup configuration and safe preset with
   AllowLiveTrading=0, AllowDllImport=0, EnableDemoOrders=false and
   EnableDemoForwardOrders=false. The terminal opens **one** XAUUSD@ M15 chart,
   running the canonical EA in **dual-observation mode** for both Retest
   (Style 1) and Sweep/Reclaim (Style 3) on each newly completed M15 candle.
4. Verify a native health beacon emitted every 10 seconds, including periods
   without signals. Missing or stale health is not interpreted as a valid
   signal-free observation session.
5. Freeze research rules and continuously create read-only signal and
   post-signal 60-minute Bid/Ask excursion reports. Once verified, register
   per-user Windows logon auto-start for the supervisor.

The special input ForwardShadowObserveBothStyles is FALSE by default and
will initialize only on a verified connected WMMarkets USD DEMO account,
XAUUSD@ M15 chart, both order toggles OFF, and Style 1. The separate
observer branch never enters ConsiderNewEntry, broker order submission,
position modification or pending-order management. The launcher does not
request or change broker account credentials.

**Fail-closed automation:** if MT5 is already running without a fresh
unarmed Shadow heartbeat, the supervisor does NOT forcibly restart it.
Any ambiguous terminal, blocked compilation, absent DEMO account or
unavailable quotes is recorded as NO-GO, never guessed away. This is a
safety boundary, not a request for the user to manage broker accounts.

All generated diagnostics are under:
gold_robot/reports_local/forward_shadow/

- QTS_FORWARD_AUTO_STATUS.json: current automatic supervisor health or NO-GO
- QTS_FORWARD_SHADOW_V2_FROZEN.json: immutable registration date/policy
- QTS_FORWARD_SHADOW_V2_REPORT.json: genuine native signals and beacon checks
- QTS_FORWARD_SHADOW_V2_QUOTE_PATHS.json: descriptive 60-minute quote excursions

The supervisor now treats both child report exit codes and the JSON status as
authoritative: an analyst NO-GO is `FORWARD_ANALYSIS_BLOCKED_NO_GO`, not a
successful report cycle. The saved status includes both analyst errors/reasons
and return codes. If there are no mature native signals, the quote-path tool
does **not** initialize a separate MT5 API session just to report "waiting".

When canonical EA source changes after a prior frozen study, the original
study and root reports are archived under `legacy_epochs/<old-source-sha>/`.
A fresh versioned prospective cohort is created under
`epochs/<new-source-sha>/`; the active top-level reports state which cohort
they represent. The old UTC freeze and its observations are never silently
reused as future observations. A corrupted original freeze remains NO-GO.
The supervisor also checks the installed EA source hash against the current
canonical source; a previously running stale binary cannot be silently
reclassified as current evidence.

For mature 60-minute price windows, the Python MT5 quote connection is **pinned
to the exact discovered terminal64.exe and MQL5 data folder**. Matching the
WMMarkets DEMO server name alone is insufficient. A mismatch between the
connected MT5 terminal installation/data paths and those verified by the
supervisor is NO-GO, not a silent switch to a different account.


Only post-registration signals count. The native ATR uses the mean of 14
true ranges and median of 48 prior readings, consistent with the historical
forensics; V1 and V2 CSV files are not mixed. At most the latest 64 events
are inspected per quote-path review; omissions make overall coverage NO-GO.

**Not trading validation:** a signal is NOT a filled LIMIT order. The
collector cannot establish actual SL/TP hits, lots, fees, slippage, realized
profit, win rate, or a profitable trading edge. Native files are not
cryptographically signed. LIVE remains LOCKED.

## Safety and installation troubleshooting

- Only the repository `main` is the active development branch.
- Never attach the EA to a real-money account or disable real-account gates.
- The EA defaults to disabled connected DEMO orders; any forward DEMO test
  requires separate explicit authorization and the correct broker identity.
- If MetaEditor compilation, binary/source checksum verification, terminal
  selection or quote history fails, treat the operation as NO-GO.
- If native MT5 exports are incomplete, inspect the relevant
  `OPEN_RESULTS.json` and broker history rather than reusing an older report.
- An untracked local file may exist without being part of Git; examine
  `git status --short` before stashing, moving or deleting it.

Advanced background: [Gold EA overview](../README.md),
[Connected DEMO operations](DEMO_FORWARD_OPERATIONS.md),
[Post-stop investigations](OWNER_PLAN_STOPLOSS_ROOTCAUSE_2026-10-26.md).
