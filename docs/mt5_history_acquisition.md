# MT5 raw tick history — acquisition / analysis separation

**Disposition:** acquisition architecture **engineered and tested**; live broker acquisition
**pending operator terminal** (sandbox runs record `MT5_PACKAGE_UNAVAILABLE`; no tick data is
present in the repository, and none is fabricated).

Governing principle:

> **ACQUIRE FIRST. ANALYZE SECOND. Never make acquisition depend on heavy analysis.**

The previous probe queried MT5 and audited every row (JSON serialization + SHA-256 per row,
duplicate analysis, spread statistics) in one operation; a multi-hour run was interrupted inside
`_audit_rows()`. That coupling is removed. The workflow is now:

```
MT5 acquisition layer            Local immutable raw dataset          Deferred analysis layer        Evidence/report layer
(src/qts/data/mt5_history_  -->  (data/raw/mt5_ticks/<symbol>/    --> (src/qts/data/mt5_history_  --> (data/evidence/mt5_history_*.json
 acquisition.py +                  <window>d__<anchor>/)                analysis.py)                   — bounded, no raw rows)
 scripts/acquire_mt5_history.py)   parts/*.parquet + manifest.json
```

The acquisition path performs exactly **query → receive → preserve every row → persist →
integrity metadata**. Everything expensive (duplicates, spreads, gaps, jumps, digests) runs
afterwards, from local files only, and can be re-run against the immutable dataset at any time.

## 1. Acquisition layer — lossless, bounded, interrupt-safe

- **Source evidence.** `copy_ticks_range(symbol, start, end, COPY_TICKS_ALL)` returns a numpy
  structured array. The *exact* structured dtype is the contract: every field is preserved
  (verified layout today: `time, bid, ask, last, volume, time_msc, flags, volume_real`). Nothing
  is selected, dropped, renamed, rescaled, deduplicated, resampled, interpolated or
  timezone-normalized. If MT5 returns new fields in the future they are preserved automatically
  (test: `test_future_broker_fields_are_preserved_not_dropped`). The returned field inventory and
  per-field numpy dtype map are recorded in the manifest.
- **Lossless storage.** numpy columns map 1:1 to Arrow columns (int64→int64, uint32→uint32,
  float64→double, uint8→uint8, ...) and are written as one Parquet part per chunk
  (zstd). Every committed part is verified by **reading the written file back and comparing each
  column element-wise** (vectorized, not per-row Python); a failure aborts the chunk and refuses
  to commit (fail-closed). Parquet is the single raw representation — no redundant second
  serialization, because the round-trip check demonstrates losslessness (if a future dtype fails
  the check, that failure is evidence, not something to work around).
- **Bounded chunks.** The requested window is decomposed into half-open `[start, end)` chunks,
  oldest first (default 24h). A chunk that fails or exceeds `max_chunk_rows` is recursively
  halved down to a floor (default 60 min); at the floor the failure is recorded in the manifest
  and the run continues. This directly recovers broker response-span caps (the observed 365-day
  `(-1, 'Terminal: Call failed')` failure mode) instead of losing the whole window. Chunk-request
  boundaries are recorded exactly; the broker's boundary inclusivity is UNVERIFIED, so a tick
  exactly on a boundary may appear in two adjacent parts — such rows are retained by design and
  measured by the analysis (never removed).
- **Interrupt-safe / restart-safe.** Each part is written to a `*.parquet.part-<pid>` temp file,
  fsync'd **via a writable descriptor** (Windows requires a write handle for fsync; a read-only
  `rb` fd fails there with `EBADF`), then atomically renamed, then the parts directory is fsync'd;
  only afterwards is `manifest.json` updated (write-tmp → fsync → rename → dir fsync) with
  `status: IN_PROGRESS`. Chunk ids are the raw bound strings, so a resume re-derives the same
  pending set and skips committed chunks. Orphan temp parts from a crash are discarded on open;
  an uncommitted part that exists only under its final name (a crash between rename and ledger)
  is deterministically overwritten when the same chunk id is re-acquired — only ledger-recorded
  parts are evidence. Only a fully closed dataset reaches `status: COMPLETE` / `EMPTY_COMPLETE`.
  A killed process can never masquerade as a complete acquisition (manifest stays `IN_PROGRESS`;
  integrity validation fails `manifest_status_final`). Resume determinism under interruption is
  pinned by tests, including byte-equality against an uninterrupted run, the Windows EBADF
  emulation, and the exact durability ordering.
- **Fail-closed safety.** Read-only and DEMO-only: the account's `trade_mode` must equal
  `ACCOUNT_TRADE_MODE_DEMO` or acquisition refuses before any tick query. The exact symbol is
  resolved via `symbol_info` (no guessing; candidates are reported). The only MT5 functions this
  layer calls are `last_error, account_info, terminal_info, symbol_info, symbol_select,
  copy_ticks_range` (structurally enforced by an AST test over the module and the driver; the
  driver additionally calls `initialize`/`shutdown`). No order/order-history API is reachable.

## 2. Local immutable raw dataset

```
data/raw/mt5_ticks/XAUUSD_/30d__20260919T120000Z/
    manifest.json                 # fsync'd; final status + full provenance
    parts/part-000000.parquet     # one chunk, atomic
    parts/part-000001.parquet
    ...
```

The entire `data/raw/mt5_ticks/` tree is gitignored (test: `git check-ignore` pins it for
manifest, parts and temp files). Only bounded evidence JSON under `data/evidence/` is
committable; analysis reports contain no raw rows (top-k lists carry raw timestamps and derived
deltas only — never quote payloads — capped at `top_k`).

The manifest records, per the provenance contract: requested/actual symbol, broker/server
identity, environment (`DEMO`) and `OBSERVE_ONLY` mode, requested start/end, actual first/last
returned raw timestamps, row count, returned fields + dtype map, acquisition start/end, status,
the chunk ledger (bounds, rows, part file, SHA-256, lossless-verification flag, mt5 error if
any), the split floor and chunk parameters, per-part SHA-256, the dataset digest (definition
below), total byte size, dataset path, software/probe versions (qts, python, numpy, pyarrow,
MetaTrader5 package, git commit), and `timestamp_interpretation_confirmed: false` with the
explicit statement that **no UTC normalization or offset inference was applied** to any value.

**Dataset digest definition** (anyone holding the raw files can recompute it):
`SHA-256("qts.mt5_raw_tick_dataset.v1\n" + "<part-name> <part-sha256>\n" per part, sorted by
name)`. Per-part SHA-256 is over the file bytes. Timestamp columns are stored as the raw integer
`time` / `time_msc` values exactly as returned.

## 3. Acquisition status vocabulary (never fake completeness)

| Dataset status | Meaning |
|---|---|
| `IN_PROGRESS` | acquisition running or was killed mid-run — never valid evidence of completeness |
| `COMPLETE` | every resolved chunk returned successfully and ≥1 row was preserved |
| `EMPTY_COMPLETE` | every resolved chunk returned successfully with 0 rows (data absence, not failure) |
| `PARTIAL_INTERRUPTED` | operator/time-budget stop; committed chunks are evidence, resumable |
| `PARTIAL_QUERY_ERROR` | ≥1 chunk failed at the split floor, or the failure-storm abort fired; recorded per chunk |
| `FAILED_SHUTDOWN` | MT5 connection lost mid-run (terminal liveness probe) |

The driver adds window-level: `REUSED_EXISTING_COMPLETE` (a prior COMPLETE dataset is kept, no
re-query), `SKIPPED_BUDGET` (never attempted), `REFUSED_FAIL_CLOSED`,
`MT5_PACKAGE_UNAVAILABLE` (this environment cannot run MT5 at all).

A failed or partial window **does not** establish a retention boundary by itself. The boundary
report distinguishes: successful complete response, empty-complete (no data), query failure,
terminal/server span limitation (recovered by splitting — recorded per chunk), interruption, and
`UNKNOWN_BOUNDARY`. Largest COMPLETE window and earliest non-empty raw timestamp are reported as
facts; deeper availability is `UNKNOWN_BOUNDARY` until evidence exists.

## 4. Deferred analysis layer (offline, no MT5)

`qts.data.mt5_history_analysis.analyze_dataset(dir)` reads only the local dataset. It never
imports MetaTrader5, opens no connection (structural test). Streaming per part with O(1) carry
state plus the float64 spread series (8 B/row, documented, for exact quantiles). It reports:

- row count; first/last raw `time`/`time_msc` (and provisional `*_if_utc` renderings, always
  flagged provisional);
- timestamp ordering: non-monotonic count, max backward step, duplicate-scope statement
  (`COMPLETE` when monotone, `ADJACENT_RUNS_ONLY` otherwise);
- same-`time_msc` collisions: groups, excess rows, rows with distinct payloads, exact full-row
  repeats (retained by acquisition, measured here);
- consecutive identical quote states (standing-quote candidates — not duplicates);
- invalid bid/ask (≤0), `ask < bid`, zero/negative spread; exact spread-bps distribution
  (count/min/mean/median/p95/max, method recorded);
- gaps: threshold counts and top-k largest (raw start/end ms + provisional weekend-overlap hint;
  gaps are spacing observations, `NOT a classification` — no fixed tick schedule exists);
- price-jump diagnostics: consecutive-row mid-price bps changes — count/mean/std/min/max,
  threshold buckets, top-k (diagnostics; no ex-ante threshold declared);
- timestamp-basis forensics: `time == time_msc // 1000` rows, second-aligned share, sub-second
  resolution presence; basis stated as UNVERIFIED raw;
- provisional coverage: distinct days with rows, rows/day min/median/max;
- schema integrity: fields/order vs manifest, physical Arrow types, future-field inventory;
- provenance validation: manifest keys/status/read-only flags, per-part SHA-256 recompute,
  dataset digest recompute, ledger-vs-disk reconciliation (no unrecorded files, all ledgered
  parts present, row arithmetic) → overall `PASS`/`FAIL`.

## 5. Operator runbook (Windows + connected WM Markets DEMO terminal)

```powershell
# 0. from a clean repo checkout on the operator machine
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ".[dev]"

# 1. (optional, seconds) lightweight capability check — no per-row audit
python scripts\probe_mt5_history.py --symbol XAUUSD@ --output "$env:TEMP\qts_mt5_probe.json"

# 2. incremental boundary-discovery ladder (ascending; stops safely on budget)
python scripts\acquire_mt5_history.py --symbol XAUUSD@ --windows-days 7,30,45,60,90,120,180,270,365 `
    --max-runtime-minutes 240 --max-window-runtime-minutes 60 --chunk-hours 24

# 3. analysis of any dataset, any time later, broker NOT required
python scripts\acquire_mt5_history.py --analyze-only "data\raw\mt5_ticks\XAUUSD_\30d__<anchor>"
```

Outputs: raw datasets under `data/raw/mt5_ticks/` (gitignored, private), run evidence
`data/evidence/mt5_history_acquisition.json`, per-window analysis
`data/evidence/mt5_history_analysis/XAUUSD__<days>d.json` (bounded, committable — commit those
two classes of files plus dataset digests; **never** the raw tree). An interrupted run is
resumed by re-running the same command (or `--force` to rebuild). A returned empty old chunk
with populated recent chunks is the broker retention floor — a fact; a *failed* old chunk is a
query failure — a different fact; both are recorded distinctly.

## 6. Controlled-environment scalability verification (synthetic fixture)

Against a deterministic fixture emitting the real MT5 tick dtype at the operator-reported 30-day
volume (4,373,160 rows, 30×24h chunks): acquisition COMPLETE in **~11 s** (~35 MB, peak RSS
~306 MB); full deferred analysis (incl. full hash recompute) in **~4 s** (peak RSS ~312 MB).
Fixture, not broker data — it verifies the architecture's cost profile and correctness (the
analysis independently found every injected duplicate/collision), not broker behavior. The old
coupled design died inside its per-row audit at this scale.

## 7. What this establishes — and what it does not (research boundary)

Extracted quote history is **broker-specific quote evidence**, not execution evidence.

| Prerequisite | Status from this workflow | Why |
|---|---|---|
| Historical bid/ask coverage | **Measurable** per acquired window (fields include bid/ask) after quality + basis review of the stored dataset | quotes preserved losslessly; coverage/quality are analysis outputs, not assumptions |
| Timestamp basis (UTC) | **UNVERIFIED** | raw fields preserved; no offset inference applied; provisional renderings are flagged |
| Spread quality (historical, broker-specific) | **Measurable** from stored quotes | distribution + invalid-quote counters from the analysis layer |
| Gaps/closures | **Observable, not classifiable** | gaps are spacing observations; weekend overlap is provisional-basis only |
| Execution/fill evidence | **BLOCKED** | no orders are ever submitted; fills do not exist |
| Slippage / latency / realized transaction costs | **BLOCKED** | require order events; this workflow is order-free by construction |
| R5 (historical execution-cost evidence) | **NOT SOLVED** | quote history ≠ execution-cost evidence; R5 remains FAIL/non-blocking |
| Frozen impulse research | **UNTOUCHED** | no rerun, no modification, no relabeling of the frozen dataset |

Historical quotes must never be represented as execution evidence. A COMPLETE window is a fact
about what the terminal served; it is not "complete history". R5 remains a separate milestone
(docs/current_state.md §C).
