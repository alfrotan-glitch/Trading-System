# MT5 historical tick / bid-ask capability probe

**Disposition after the operator probe: `CAPABILITY_VERIFIED_LIMITED_HISTORY`; acquisition status `PARTIAL`; quality status `NOT_ASSESSED`.**

The operator reported a real read-only WM Markets DEMO response from MetaTrader5 `5.0.6180` for exact symbol `XAUUSD@`: 1-day, 7-day, and 30-day `copy_ticks_range` requests returned bid, ask, time, and time_msc fields; the 365-day request returned `(-1, 'Terminal: Call failed')`. This verifies a limited historical tick/bid/ask capability, not the maximum retention boundary or research eligibility. The current Linux checkout still has no canonical `data/sqlite/forward_observatory.db`; **raw/canonical tick-level evidence is not present in the repository.** The safe operator report is recorded in `data/evidence/mt5_history_capability_report.json` without raw rows.

## What must be established on the actual terminal

The operator must run the probe against the current WM Markets DEMO terminal and save the raw response/export outside public Git. The probe must answer each question separately:

1. Does the terminal expose `copy_ticks_range` or an equivalent broker-history query for the exact broker symbol, such as `XAUUSD@`?
2. Does that query return individual records with raw MT5 `time`/`time_msc` and both bid and ask, rather than only OHLC bars?
3. What is the earliest and latest returned record, and are the records broker-specific or a generic/vendor series?
4. Does the requested range contain gaps, weekend/holiday closures, duplicate stamps, or only the currently cached terminal range?
5. Can the terminal's History Center export preserve the same tick fields, timestamps, and symbol identity?
6. Does the terminal provide execution history independently of quote history: submission, acknowledgement, fill, requested price, fill price, slippage, reject code, and order/deal identifiers?

A successful candle query does **not** answer questions 1 or 2. OHLC bars must not be promoted to tick, bid, ask, or spread evidence.

## Safe probe protocol

The repository includes a minimal read-only capability probe at
`scripts/probe_mt5_history.py`. It uses the already-running terminal session,
queries only `symbol_info`, `symbol_select`, account/terminal diagnostics, and
`copy_ticks_range`, and emits bounded metadata, response counts, schema fields,
and timestamp-only first/last coverage. It does **not** hash or audit rows.
It never calls `order_send` or any execution endpoint.

When raw history is required, use `scripts/acquire_mt5_history.py` instead.
That command writes every returned MT5 field and row to a private Parquet
chunk directory. Run `scripts/analyze_mt5_history.py` later against the
completed local dataset for hashing, duplicate analysis, spread checks, and
quality evidence; acquisition never waits for those operations.

The probe is read-only and must not call `order_send` or any execution endpoint.

From PowerShell, with the already-connected WM Markets DEMO terminal open, the single operator action is:

```powershell
python scripts\probe_mt5_history.py --output "$env:TEMP\qts_mt5_history_probe.json"
```

This does not request credentials, submit orders, alter permissions, or write
inside the repository. Return the generated JSON report in the next step; do
not commit it yet. If `QTS_MT5_SYMBOL` is unset, the probe starts with
`XAUUSD` and reports broker-symbol candidates rather than guessing a symbol.

The probe records:

```text
product_mode       = DEMO_FORWARD
observation_mode   = OBSERVE_ONLY
environment        = DEMO_FORWARD
execution_policy   = DEMO_EXECUTION = DISABLED BY POLICY; LIVE = LOCKED
symbol             = requested symbol plus exact terminal symbol/candidates
query              = bounded 1d, 7d, 30d, and 365d windows
fields required    = time, time_msc, bid, ask, flags/volume when available
recorded alongside = terminal build, broker server, symbol specification,
                     query range, request timestamp, response count, timestamp-only coverage

The raw-row SHA-256 belongs to the completed Parquet acquisition sidecar, not
this capability probe.
```

For each response, record a dataset-specific outcome using the matrix vocabulary:

- `FOUND` is not enough: acquisition, quality, provenance, licensing, and research eligibility are separate decisions.
- `ACQUIRED` requires the raw response/export and a checksum outside the public repository.
- `QUALITY_PASSED` requires measured coverage, timestamp, duplicate, field-completeness, and gap results.
- `RESEARCH_ELIGIBLE` requires the declared research scope, licensing permission, and chronological-cost rules.
- If no tick response is returned, record `NOT_AVAILABLE` or `NOT_YET_ACQUIRED`; do not infer from candles.

## Current evidence boundary

`data/evidence/forward_observation_manifest.json` is a derived manifest contract. It cannot substitute for the absent private SQLite store or prove physical MT5 origin. A future terminal run must export the canonical session through the versioned session/research evidence contracts, preserve raw/private SQLite outside public Git, and independently verify the SHA-256 artifact and audit manifest.

The observe-only collector can preserve accepted forward quotes and acquisition-attempt outcomes when run on the terminal. It does not create execution evidence, and it does not enable broker orders. Missing quote-age-at-decision, quote-age-at-submission, fill, slippage, submission/acknowledgement, and broker-response fields remain explicit gaps until separately captured.
