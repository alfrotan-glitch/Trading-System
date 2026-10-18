# Windows DEMO runbook

**Audience:** an operator on the authorized Windows workstation with MetaTrader 5.
**Boundary:** DEMO only; LIVE stays locked; this runbook does not authorize an order.
**Reviewed:** 2026-10-18.

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

Slippage is measured from actual DEMO fill records. Without such fills it is unavailable; do not substitute zero. Once the read-only artifacts and any existing deal evidence are available, assemble the component-wise model and re-evaluate the frozen monthly champions without retuning:

```bat
qts demo measured-model --spread-profile "%LOCALAPPDATA%\QTS\cost-audit\spread_overlap.json" --symbol-terms "%LOCALAPPDATA%\QTS\cost-audit\symbol_terms.json" --direction long --json-out "%LOCALAPPDATA%\QTS\cost-audit\measured_cost_model.json"
qts demo evaluate-champions --spread-profile "%LOCALAPPDATA%\QTS\cost-audit\spread_overlap.json" --symbol-terms "%LOCALAPPDATA%\QTS\cost-audit\symbol_terms.json" --direction long --json-out "%LOCALAPPDATA%\QTS\cost-audit\champion_cost_evaluation.json"
```

Each component has its own basis. Unless the result says **`claim_eligible: true`** with every cost component measured, it is sensitivity analysis only. Missing commission, slippage or financing cannot be filled with historical averages or zeros.

## 4. Research status and cost limitations

The current research verdict is **`NO_VALIDATED_EDGE`** (`N_TRIALS = 355`). The monthly `ts9_lo` and `veto9` candidates remain in research; the separate DEMO EMA policy is not one of those monthly candidates.

For context only, the saved 2000-01–2026-09 monthly evaluation reports `ts9_lo` net about `+$70,989` (16 round turns, max drawdown `−30.98%`, exposure `71.65%`) and `veto9` about `+$49,897` (26 round turns, max drawdown `−35.97%`, exposure `93.46%`) under an **ASSUMED** base cost model. The research report's required gates fail and passive buy-and-hold outperformed the active candidates. A separate stdlib/NumPy calculation agrees with the saved accounting; it reuses the same input lineage and does not provide independent market-data validation.

Financing is a material unknown: a post-hoc symmetric financing sensitivity (assumed bps per calendar day, not broker swap) reduces `ts9_lo` / `veto9` to about `+$59,931` / `+$39,392` at 0.25 bps/day, and `+$3,822` / `−$4,129` at 3 bps/day. The broker's actual directional XAUUSD swaps were not measured. Do not interpret these assumed scenarios as a WM Markets quote or a promise of future performance.

The older Dukascopy-derived M15 snapshot has a recorded completeness result of **6.42% unexpected missing active-span intervals**, above the unchanged 2% quality threshold; its quality gate is `FAIL`, upstream licensing is not cleared, and the planned OOS evaluation was not executed. The old acquisition instructions that expected `Ready for claims: YES` are obsolete. Do not rerun or use that data for claims unless new source, licensing and completeness evidence resolves the blockers. See `data/evidence/xauusd_completeness_disposition.json` and `data/evidence/xauusd_dukascopy_new_quality.json`.

Historical WM tick-archive spread measurements documented in the 2026-10-11 audit are not current broker quotes, account-specific fees or a reproducible raw sample from this checkout. Treat them as historical context only. Current XAUUSD spread, commission, swap, slippage, contract details and account eligibility remain unverified until measured/confirmed on an authorized account.

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
