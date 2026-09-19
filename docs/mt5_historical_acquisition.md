# MT5 historical acquisition: acquire first, analyze second

## Boundary

The historical workflow is deliberately split into four layers:

1. `scripts/acquire_mt5_history.py` queries the connected WM Markets DEMO MT5
   terminal in bounded time windows and persists every response as Parquet.
2. The local Parquet directory is the immutable source copy. One returned MT5
   response is one Parquet chunk. No row is de-duplicated, normalized,
   resampled, summarized, or dropped.
3. `scripts/analyze_mt5_history.py` reads only the local Parquet directory and
   performs the expensive quality analysis. It does not import or contact
   MetaTrader5.
4. The JSON report is derived evidence and is not execution evidence.

The acquisition path does not JSON-serialize or SHA-256 hash every row. It
writes the Arrow columns directly, updates a row count and schema inventory,
and hashes the completed Parquet files once after persistence. Raw `time` and
`time_msc` remain raw MT5 values; the current observation offset is never
applied to historical rows.

The dataset is a directory ending in `.parquet`, with one file per bounded
query. A final directory is renamed into place only after all chunks succeed.
Interrupted or failed runs leave a private `partial-*` directory and metadata
with an incomplete status; they can never be mistaken for a completed dataset.
A new run has a new acquisition id and does not reuse a partial artifact.

## Windows / boundary discovery

Start with small windows and preserve each successful result separately. Do
not launch a 365-day request first:

```powershell
python scripts\acquire_mt5_history.py `
  --symbol XAUUSD@ --days 1 --chunk-hours 24 `
  --output "$env:LOCALAPPDATA\QTS\mt5\XAUUSD_at_1d.parquet"

python scripts\acquire_mt5_history.py `
  --symbol XAUUSD@ --days 7 --chunk-hours 24 `
  --output "$env:LOCALAPPDATA\QTS\mt5\XAUUSD_at_7d.parquet"
```

Continue with `30`, then `45`, `60`, `90`, and `180` days only after the
smaller run has completed and the operator has confirmed disk capacity. If a
window fails, the report records `MT5_QUERY_ERROR`; it does not turn the error
into a retention-limit claim. A returned zero-row chunk is recorded as
`NO_DATA`. If an earlier chunk succeeded and a later one fails, the complete
result is `PARTIAL` and only the private partial chunks remain.

The old capability-only probe remains useful for a quick bounded shape check:

```powershell
python scripts\probe_mt5_history.py `
  --symbol XAUUSD@ --windows-days 1,7,30,45,60,90,180 `
  --output "$env:TEMP\qts_mt5_capability.json"
```

It now records response counts and fields only. It does not run row audits.
Use the acquisition command when the rows need to be preserved.

## Deferred analysis

After a `COMPLETE` acquisition:

```powershell
python scripts\analyze_mt5_history.py `
  "$env:LOCALAPPDATA\QTS\mt5\XAUUSD_at_7d.parquet" `
  --metadata "$env:LOCALAPPDATA\QTS\mt5\XAUUSD_at_7d.parquet.metadata.json" `
  --output "$env:LOCALAPPDATA\QTS\mt5\XAUUSD_at_7d.analysis.json"
```

The analyzer runs from local files and reports row count, raw first/last and
min/max `time_msc`, ordering, exact full-row repeats, same-timestamp groups,
distinct same-timestamp quote payloads, standing quote candidates, invalid
bid/ask values, spread statistics, raw timestamp gaps, price-change
Diagnostics, schema variants, Parquet digest, and provenance validation.
Median and p95 spread/price-change values are deterministic reservoir-sample
statistics; counts, min/max, mean, and standard deviation are exact streaming
statistics. No quality result changes the raw dataset.

## Provenance and safety

The acquisition sidecar records the requested symbol, actual symbol when
available, broker/server, environment, observation mode, requested bounds,
raw returned schema, chunk boundaries, returned row count, first/last raw time
fields, start/end times, failure details, dataset path, file size, and a
SHA-256 digest over persisted Parquet relative paths and bytes. It explicitly
records `timestamp_basis = UNVERIFIED` until an independent historical basis
check is completed.

The workflow calls only MT5 diagnostics, symbol selection, and
`copy_ticks_range`. It never calls `order_send`, an order-check endpoint, or a
position mutation endpoint. `DEMO_EXECUTION = DISABLED BY POLICY`, `LIVE =
LOCKED`, and `NO_TRADE` are unchanged.

Raw datasets, partial directories, and sidecars are machine-local and
excluded by `.gitignore`. Only code, tests, and non-private derived summaries
belong in Git. The frozen REAL/Dukascopy research dataset is not modified and
R5 remains unsolved: quote history cannot establish fills, slippage, latency,
or realized transaction costs.
