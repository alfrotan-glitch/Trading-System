# Windows DEMO runbook

**Audience:** an operator on the authorized Windows workstation with MetaTrader 5.
**Boundary:** DEMO only; LIVE stays locked; this runbook does not authorize an order.
**Reviewed:** 2026-10-20.

The order-capable DEMO path exists, but a checklist, a passing readiness probe, a strategy snapshot or a simulated test is not permission to trade. This guide separates read-only inspection from actions that persist identity, grant permission or can submit an order. Nothing in this audit connected to MT5 or sent an order.

## 0. Current status and stop conditions

- The registered provider is **`DEMO-XAUUSD-TREND-TSMOM-V1`**: completed-bar XAUUSD M15 EMA(12/48), 0.01 registered lots, a USD 3.00/oz XAUUSD quote-price-distance protective stop (not a dollar-loss cap) and a four-hour maximum hold. It is a frozen DEMO diagnostic (`validated_edge: false`), not a validated or profitable strategy.
- The Trading page's history snapshot is read-only. A crossover found in the last seeded bar is historical information, not a live signal. Only a future completed-bar crossover observed by the provider can generate an autopilot signal.
- The UI's manual ticket is **not** strategy-generated. It is an operator-selected diagnostic request; the page runs no-order preflight first and asks for explicit confirmation. The backend repeats the gates before submission.
- Monthly `ts9_lo` / `veto9` are separate paper research. They are not registered in the DEMO order path.
- Public WM Markets pages returned a regional-restrictions notice in this session on 2026-10-18. The pages did not establish account eligibility or current, account-specific XAUUSD terms. Confirm eligibility directly with the broker before connecting. Do not attempt to bypass a restriction.
- Linux in this audit had no MT5 terminal/package and no broker/account was queried. No real-terminal verification or order is claimed.

**Stop here** if broker eligibility is not confirmed, the account is not explicitly DEMO, a required field is unavailable, readiness fails, an order outcome is ambiguous, or QTS and broker state do not reconcile. Unknown cost fields remain unknown; never replace them with zero.

## 1. Environment and first read-only checks

On the Windows workstation, open MT5 and sign in only to an eligible DEMO account. Do not put passwords in command history, repository files or reports.

```bat
cd C:\path\to\Trading-System
python -c "import MetaTrader5; print(MetaTrader5.__version__)"
qts demo verify
mkdir "%LOCALAPPDATA%\QTS\cost-audit"
qts demo connectivity --json-out "%LOCALAPPDATA%\QTS\cost-audit\connectivity.json"
```

`qts demo verify` and `qts demo connectivity` without `--pin` are probes; they submit no order. `verify` reports blockers and one next action. A failed command/exit code is not a reason to bypass a gate.

**Not read-only:** `connectivity --pin` writes an identity pin; `--confirm-pin` records owner confirmation; `qts mode declare`, `qts demo arm`, `qts demo reverify`, and evidence `--record` change local state. They require a deliberate operator decision and are not part of the inspection sequence below.

## 2. Read-only strategy, size, risk and readiness review

Open the **Trading** page. Review:

- registered DEMO policy and explicit `no validated edge` status;
- latest completed M15 indicator state and bar timestamp, if MT5 history is available;
- last-bar cross as a **snapshot only** (it cannot produce an order);
- registered default size, broker volume-bound check and the broker-contract stop-distance estimate, if the required facts are readable;
- current quote freshness/spread and the ordered readiness blockers.

The estimated stop-distance loss is not a maximum-loss guarantee. It excludes spread, commission, slippage, financing, gaps and differences in stop execution. Without contract size, profit currency, registered size or stop distance, the amount remains `UNAVAILABLE`; without readable account equity in the same currency, only the percentage-of-equity field remains unavailable. The indicator snapshot is independently unavailable until completed M15 history is readable.

### Optional read-only broker history-depth check

On the controlled Windows workstation with the eligible DEMO terminal open, the broker-history depth probe answers how many M15 bars the terminal currently exposes and whether small tick-history windows return rows:

```bat
qts data mt5-depth --json-out "%LOCALAPPDATA%\QTS\cost-audit\mt5_depth_probe.json"
```

It performs bounded read-only queries, writes counts/timestamps (not raw bars or ticks), downloads no dataset and submits no orders. Keep its report local. It measures terminal depth only; it does **not** establish data completeness, licensing, independent source quality or readiness of the committed research series. The saved M15 completeness gate remains failed at 6.42% unexpected missing intervals. This audit did not run the broker probe.

Optional no-order walk-through of the autopilot loop:

```bat
qts demo run --strategy DEMO-XAUUSD-TREND-TSMOM-V1 --dry-run --max-iterations 1
```

`--dry-run` never submits an order. Its output is not a fill, live-signal record, broker verification or profitability evidence.

## 3. Broker cost capture — no order required

Keep evidence under a machine-local directory such as `%LOCALAPPDATA%\QTS\cost-audit`; reports can expose account, broker and server identifiers. Do not commit raw account reports, deal records or private cost artifacts. Export only a sanitized summary if sharing is necessary.

### 3.1 Symbol terms, including directional swap

```bat
qts demo symbol-terms --json-out "%LOCALAPPDATA%\QTS\cost-audit\symbol_terms.json"
```

This read-only probe reports broker symbol geometry, current spread and directional `swap_long` / `swap_short` terms where the terminal exposes them. It requires a DEMO account and never submits an order. Record the account type, server and measurement time locally; broker terms may change. The broker's generic material describes triple rollover, but the applicable instrument/account schedule must be checked in MT5.

### 3.2 Spread distribution

Run samples at more than one session, including a quiet period, active overlap and broker-server rollover. Confirm server time from MT5; do not guess it from UTC.

```bat
qts demo spread-profile --samples 60 --interval-sec 5 --json-out "%LOCALAPPDATA%\QTS\cost-audit\spread_overlap.json"
qts demo spread-profile --samples 60 --interval-sec 5 --json-out "%LOCALAPPDATA%\QTS\cost-audit\spread_quiet.json"
qts demo spread-profile --samples 60 --interval-sec 5 --json-out "%LOCALAPPDATA%\QTS\cost-audit\spread_rollover.json"
```

Use p95/p99 as stress context; a single median or one quiet session is not the spread cost of every future order.

### 3.3 Commission, swap and fee from existing DEMO deals

```bat
qts demo cost-check --json-out "%LOCALAPPDATA%\QTS\cost-audit\cost_check.json"
```

The check reports whether the terminal is DEMO, account currency is known, server-to-UTC offset is measured, the evidence chain is valid/writable and recent deals expose commission/swap/fee fields. `READY_FOR_COST_CAPTURE: True` is necessary for recording, not a trade authorization.

If the account already has suitable DEMO deals, the optional flag records those existing rows locally—no order is needed:

```bat
qts demo cost-check --record --json-out "%LOCALAPPDATA%\QTS\cost-audit\cost_check_recorded.json"
```

`--record` changes the local evidence store. It is opt-in, records backfill provenance and must not be run if the operator does not want local deal-level evidence persisted. If no existing DEMO deal exposes a field, that cost stays `UNKNOWN`; do not place an order solely to measure it.

### 3.4 Slippage and offline cost evaluation

Slippage is measured from actual DEMO fill records. Without such fills it is unavailable; do not substitute zero. `qts demo measured-model` assembles component-wise cost evidence and labels each component separately:

```bat
qts demo measured-model --spread-profile "%LOCALAPPDATA%\QTS\cost-audit\spread_overlap.json" --symbol-terms "%LOCALAPPDATA%\QTS\cost-audit\symbol_terms.json" --direction long --json-out "%LOCALAPPDATA%\QTS\cost-audit\measured_cost_model.json"
```

The operator API/CLI does not automatically re-evaluate strategies or load the repository's historical market dataset. `qts demo evaluate-champions` is cost-status only and reports a blocked or `NOT_RUN` evaluation status; the operator CLI has no offline-evaluation input option. Any future offline evaluation requires separate review and an approved input, and it is not an operator workflow. Any future offline evaluation requires separate review and an approved dataset. Do not use post-1999 prices or the locked holdout. A measured cost component is not a measured net edge; missing commission, slippage, or financing cannot be filled with documentation, historical averages, or zero.

## 4. Research status and cost limitations

The governed result is **`NO_VALIDATED_EDGE`** (`N_TRIALS = 362`). No strategy is promoted; `LIVE` stays locked. `ts9_lo` and `veto9` are frozen research/forward-observation candidates, not validated DEMO or LIVE strategies. The CMR, Brent, commodity-breadth, yield-curve, calendar-seasonality, and Sahm/U-3 screens were rejected; FX-dispersion is inconclusive; the CPI attempt stopped before outcome calculation. Preserve each disposition and do not tune, substitute, or rerun a rejected family on reused partitions.

The one-run Sahm/U-3 candidate was rejected on the authorized pre-2000 partitions. Its pinned revised U-3 snapshot lacks point-in-time vintages. Do not treat it as a real-time signal or repair/rerun it. No post-1999 Gold price values or locked 730-day holdout rows are to be accessed for this workflow.

Historical post-1999 performance summaries and historical tick-archive summaries are archived records, not current account measurements or current validation. This operator runbook does not repeat or recalculate those figures. The M15 source record is also historical: its data-quality gate failed and licensing remains unresolved, so it is not claim-eligible.

`data/evidence/broker_cost_reference_documented_2026-10-20.json` contains public specification examples only. The legacy `measured_broker_costs.json` path is a superseded-name notice. Neither represents this account. Current account-specific spread, commission, slippage, and swap remain **UNMEASURED** until verified from the authorized terminal and, where applicable, existing DEMO deals. Do not place an order solely to obtain a cost sample.

## 5. DEMO state changes and orders — separately authorized only

Identity pinning, confirmation, mode declaration, arming and re-verification write state or enable the order path. Do not perform them during a read-only audit. A non-dry-run autopilot can submit an order after a future provider signal; it requires an explicit separate operator decision and both flags:

```bat
qts demo run --strategy DEMO-XAUUSD-TREND-TSMOM-V1 --confirm --risk-ack
```

For an individual manual diagnostic order, `qts demo order` also requires `--confirm --risk-ack`, and must be preceded by `qts demo preflight` / a no-order preview. Example format only—not authorization to run:

```bat
qts demo preflight --side BUY --lots 0.01
qts demo order --side BUY --lots 0.01 --strategy DEMO-XAUUSD-TREND-TSMOM-V1 --confirm --risk-ack --rationale "authorized DEMO diagnostic"
```

Use a current, broker-valid stop; the registered policy requires protection. A command-line invocation with the flags is an explicit operator act, but it does not bypass identity, authorization, readiness, staged permission, risk, spread, broker order-check or reconciliation gates. Never use a manual order as evidence that the strategy generated a signal.

No order was sent in this audit. The external regional notice, unmeasured all-in costs and `NO_VALIDATED_EDGE` remain blockers to any economic claim. **LIVE must remain locked.**
