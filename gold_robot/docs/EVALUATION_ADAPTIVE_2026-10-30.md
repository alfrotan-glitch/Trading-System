# Evaluation — Adaptive Router Hardening, SMC Style 8, M1 Scalp Style 9
Date: 2026-10-30. Branch: `independent/adaptive-robot-20261030`.
Base: main `6c8f786` + fix branch `5fc0929` incorporated (`e07bec7`),
router+SMC (`2c3dd81`), scalp (`6f26506`).

## Verdict: NO-GO for production, for every candidate

No candidate passes all gates, because the gates that require native
evidence have not run. This is not a softened "promising": it is a
NO-GO with the failing gate named for each candidate below. No market
PnL for the hardened router, Style 8, or Style 9 was evaluated on
Linux, and no threshold was tuned on any market return at any point
in this branch.

## What was actually run on Linux (and what it proves)

- `gold_robot/tests`: 184 passed at the final commit (175 after
  router+SMC, 180 after scalp, 184 after the ledger tool).
- Python unknown-strategy + exit-rules tests: 22 passed.
- Manifest: 88 files valid (`SOURCE_CHECKSUMS.json` regenerated after
  every gold_robot change, `--check` passes). [Corrected 2026-10-30
  in the repair branch: the "84" figure below was written before the
  final manifest regeneration; 88 is the verified count at push.]
- `evaluate_ledger.py` synthetic controls (fabricated ledgers, NOT
  market results): a positive synthetic ledger (150 trades, mean
  +$3.00, sd $12, 60 days) screens net +$317.52, PF 1.57, bootstrap
  99% lower +$0.23, yet is correctly REJECTED because provenance is
  SIMULATED; a negative synthetic ledger (mean -$3.00) screens net
  -$633.59, PF 0.44, DSR 0.0. The tool's arithmetic and fail-closed
  behaviour are verified; no strategy is validated by these controls.
- MQL5 syntax review: brace/paren balance checked for all touched
  MQL5 files. This is NOT a compile. MQL5 is UNCOMPILED until Windows
  MetaEditor passes.

## What was NOT run on Linux (and why it was not faked)

- No native MT5 Strategy Tester run: no MT5/MetaEditor/Wine on Linux.
- No unseen-window evaluation: the preregistered window must be a
  fresh period AFTER 2026-10-30, at least 3 months, with >=100 closed
  trades, >=40 active days, >=20 trade days per candidate. That
  window does not exist yet and cannot be backfilled from local data.
- No M15/M1 broker bars: the clone has no `data/raw/`. The only bar
  file is `data/fixtures/XAUUSD_1H_500.csv` (500 H1 bars, 2020-01-01
  to 2020-01-21, synthetic-looking round $2,000 opens). It is the
  wrong timeframe for all three candidates, only 21 days, and not
  broker data. It was NOT used for any PnL, signal-count, or tuning
  claim in this branch.
- No broker-measured costs: WMMarkets commission/swap/spread have not
  been measured from a statement. Every cost in this branch is
  ASSUMED ($10/lot round-turn, $0.10 stop slippage, tester tick
  spread) and labelled as such.
- No DEMO-forward: the tester-only block for Styles 4–9 has not been
  changed, and no DEMO run exists for them.

## Per-candidate gate status

| Candidate | edge_gate | Walk-forward | Placebo | Robustness | Native evidence | DEMO | Verdict |
|---|---|---|---|---|---|---|---|
| Hardened router (Style 7 + persistence/transition/ATR guard) | NOT RUN | NOT RUN | NOT RUN | NOT RUN | MISSING — no native HTML + forensic CSV | NOT RUN | NO-GO: native evidence missing |
| SMC Style 8 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | MISSING — no native HTML + forensic CSV; MQL5 uncompiled | NOT RUN | NO-GO: native evidence missing |
| M1 scalp Style 9 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | MISSING — no native HTML + forensic CSV; MQL5 uncompiled; auto-runner is M15-only, manual M1 run required | NOT RUN | NO-GO: native evidence missing |

All three also fail the preregistered kill criterion "missing
forensic ledger = EVIDENCE_GAPS_NO_GO" until the Windows run exists.
A killed candidate is not retuned on the same window; a fresh unseen
window is required after any change.

## Trial ledger (counted, not minimised)

- This branch's new strategy hypotheses: router hardening (1), SMC (1),
  M1 scalp (1) = 3.
- Existing hypotheses that a Windows run re-tests: Styles 0–7 + router
  baseline = 8, plus SMC + scalp = 10 styles in one Windows run.
- The Windows run must declare trials_tested >= 10, plus every
  robustness perturbation actually run (threshold perturbations,
  cost/spread/slippage stresses are each a trial). This branch's
  edge_gate resolves up to 40 trials; beyond 40, lower=None is
  fail-closed and DSR/Holm over the ledger-counted list must be used.
- Fix incorporation (`e07bec7`) is not a strategy trial; it changed
  the gate (BOOTSTRAPS 2000→20000, cap 40) and the unknown-strategy
  fail-closed behaviour, and is recorded here so it is never counted
  as, or confused with, a strategy result.

## Costs — MEASURED vs ASSUMED

- ASSUMED (all Linux work): $10/lot round-turn, $0.10 stop slippage,
  spread from tester ticks. Label every result ASSUMED until a
  WMMarkets statement is produced.
- MEASURED (required for any claim): commission, swap, and spread
  from a WMMarkets account statement for XAUUSD@, with the statement
  date and the timestamp/price basis confirmed. Until then, the
  maximum status any candidate can reach is
  RESEARCH_POSITIVE_NOT_VALIDATED, never validated.

## Limits that apply to every result in this branch

- Python results are SCREENING ONLY. Python simulators cannot
  faithfully replicate the MQL5 router (different timeframe,
  indicators, regime, TP/SL construction, tick rounding, sizing,
  fills, costs, session clocks, risk caps — see the quant audit).
- Local data has no `data/raw/` and unconfirmed timestamp/price basis.
- MQL5 is UNCOMPILED on Linux. No native MT5 result exists in this
  branch, and none is claimed.
- Live trading stays disabled. The EA's live block and DEMO-only
  posture were not weakened.
