# MT5 historical tick / bid-ask capability probe

**Disposition as of 2026-09-19: `CAPABILITY_UNVERIFIED`; acquisition status `NOT_AVAILABLE_IN_CHECKOUT`.**

This is a capability finding, not a claim that the WM Markets MT5 terminal can or cannot provide a particular history. The current Linux checkout has no Windows MT5 terminal, no broker login session, and no canonical `data/sqlite/forward_observatory.db`. Therefore the repository cannot report a successful historical broker query. **Raw/canonical tick-level evidence is not present in the repository.**

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

The probe is read-only and must not call `order_send` or any execution endpoint.

```text
product_mode       = DEMO_FORWARD
observation_mode   = OBSERVE_ONLY
environment        = DEMO_FORWARD
execution_policy   = DEMO_EXECUTION = DISABLED BY POLICY; LIVE = LOCKED
symbol             = exact broker symbol returned by the terminal
query              = bounded historical range, then a second bounded range
fields required    = time, time_msc, bid, ask, flags/volume when available
recorded alongside = terminal build, broker server, symbol specification,
                     query range, request timestamp, response count, raw response hash
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
