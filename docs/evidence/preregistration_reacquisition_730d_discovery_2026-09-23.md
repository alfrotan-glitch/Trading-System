# Preregistration Amendment — Certified Discovery-only Reacquisition for H-DIR-01

**Schema:** `qts.xauusd_reacquisition_preregistration.v1`
**Registered:** 2026-09-23T12:20:00Z — **before** any reacquisition
**Parent hypothesis:** H-DIR-01 in `docs/xauusd_directional_next_step_2026-09-23.md` — **unchanged**
**Status of H-DIR-01:** `PREREGISTERED, NOT RUN` — this amendment does not modify its prediction, thresholds, horizons, cost filter, delay, or stopping rules
**Execution venue:** Windows operator machine with running WM Markets DEMO terminal + `MetaTrader5` Python package (Linux sandbox cannot execute — `MT5_PACKAGE_UNAVAILABLE`)
**No orders:** `DEMO_EXECUTION=DISABLED BY POLICY`, `LIVE=LOCKED`, `NO_TRADE`; only `copy_ticks_range` family reachable (structurally enforced)

---

## 1. Why this exists

The canonical archive `dataset-xauusd-730d-20260919` (`XAUUSD_730d_20260919T114013Z.zip`, SHA-256 `975b68637be3597aeccd9055c09b98a398cf799fc04a1530164ae6acf108f723`, manifest digest `26aee827802066266fc5ef2f4ef30f874b0a7139666caf46f3bcfbec840e3789`, rows 139,930,971, `time_msc` 1726746013452→1789775939790, cutoff `1764563969254` / 70,834,426 discovery rows) is **complete** but its **60% time split falls inside** `part-000441.parquet` (global `[70,783,710, 70,916,415)` — 50,716 Discovery + 81,989 held-out rows in one ZIP-compressed member). No per-part timestamp, row-group, or Discovery-prefix digest exists in the acquisition ledger. `reports/xauusd_discovery_boundary_audit.json` (Actions `35856015114`) and `reports/xauusd_discovery_only_source_search_2026-09-23.md` prove no independently authenticated Discovery-only view is available. Opening that member violates the held-out prohibition. `preflight_view()` correctly refuses, so H-DIR-01 remains `NOT_RUN_ACCESS_BLOCKED`.

This amendment defines the **only** admissible path to make H-DIR-01 falsifiable without leaking held-out: a **separate physical Discovery-only dataset** reacquired with the cutoff as an explicit **chunk boundary**, manifested and digested independently, pinned via `docs/xauusd_directional_view_authority.json`, and presented to a runner that holds **only** that view. It does **not** rewrite, re-cut, or re-digest the canonical ZIP.

## 2. What will be produced (two artifacts, plus one authority file)

| Artifact | Location on operator machine | Content | Digest |
|---|---|---|---|
| Discovery view dataset | `data/raw/mt5_ticks/XAUUSD_730d_DISCOVERY_20260923/` (new directory, **not** `XAUUSD_730d_20260919T114013Z`) | `manifest.json` + `parts/part-*.parquet` covering **exactly** `time_msc` in `[1726746013452, 1764563969254)` in original ledger order | `manifest.json` SHA-256 + per-part SHA-256 + `dataset_sha256 = SHA256("qts.mt5_raw_tick_dataset.v1\n" + "<part> <sha256>\n" sorted)` (same `dataset_digest()` definition as `src/qts/data/mt5_history_acquisition.py`) |

Authority file (published separately, **before** any H-DIR-01 run): `docs/xauusd_directional_view_authority.json` with schema `qts.xauusd_discovery_view_authority.v1`, containing `source_zip_sha256`, `source_dataset_sha256`, `source_manifest_sha256`, `cutoff_time_msc`, `discovery_rows`, `time_msc_min`, `time_msc_max` (Discovery), `view_dir`, and `view_manifest_sha256`. The H-DIR-01 runner must receive this file from a **different** channel than the view itself; a view is not trusted on its own self-label.

## 3. Reacquisition protocol (Discovery time span only)

1. **Prerequisites:** `docs/mt5_history_acquisition.md` §1–3 are followed. Operator confirms `TRADE_MODE_DEMO`, exact symbol `XAUUSD@` via `symbol_info`/`symbol_select`, and `copy_ticks_range` availability on a live DEMO terminal. No `order_send` path is importable.
2. **Requested span:** `[1726746013452, 1764563969254)` as raw `time_msc` boundaries (half-open, integer ms). This is the **already-locked** H-DIR-01 Discovery span — no new cutoff is chosen.
3. **Chunking discipline:** The requested span is decomposed into oldest-first, half-open `[start, end)` chunks **split on the cutoff** — no chunk may cross `1764563969254`. Default 24 h chunks, recursive halving on `Call failed` or `max_chunk_rows` down to 60 min floor; at the floor the chunk is recorded as failed and the run continues (fail-closed, as in the original acquisition). Chunk request boundaries are recorded as `start_utc`/`end_utc`; broker inclusivity is untrusted, so boundary-duplicate rows are retained and measured (never removed). This guarantees no part ever contains both Discovery and held-out rows.
4. **Preservation:** Exact structured array as returned by `copy_ticks_range` — fields `time, bid, ask, last, volume, time_msc, flags, volume_real` (plus any future fields) preserved with dtype-faithful Arrow columns (`int64→int64`, `uint32→uint32`, `float64→double`, `uint8→uint8`, ...), Parquet ZSTD. Each part written to `*.parquet.part-<pid>` → `fsync` via writable descriptor → atomic rename → directory `fsync` → ledger append `manifest.json` (`write-tmp → fsync → rename → dir fsync`, `status: IN_PROGRESS`). Per-part lossless verify by reading back each column element-wise; mismatch aborts the chunk. Kill at any point leaves `IN_PROGRESS` (never masquerades as `COMPLETE`).
5. **Manifest contract:** Same provenance contract as the original manifest: `requested/actual symbol`, broker/server, `environment: DEMO`, `OBSERVE_ONLY`, `requested_start/end`, `actual_first/last_raw`, row count, `returned_fields` + dtype map, acquisition start/end, `status`, chunk ledger (bounds, rows, part file, SHA-256, verify flag, mt5 error), split floor/chunk params, `dataset_sha256`, `total_byte_size`, `dataset_path`, `qts/python/numpy/pyarrow/MetaTrader5/git` versions, `timestamp_interpretation_confirmed: false`, no UTC normalization.
6. **Finalization:** Only when every chunk in the Discovery span succeeds with ≥1 row (or `EMPTY_COMPLETE` with 0 rows) does the manifest reach `status: COMPLETE_DISCOVERY_ONLY` (view schema `qts.xauusd_discovery_view.v1`). Any other status is not research-eligible. No rows are repaired, interpolated, resampled, timezone-shifted, or deduplicated beyond adjacency.

## 4. Authority pinning and separate-runner verification

1. On the operator machine, compute `view_manifest_sha256 = sha256(file_bytes("manifest.json"))`. Independently (e.g., on a second machine or out-of-band), publish `docs/xauusd_directional_view_authority.json` containing the canonical identity triple plus `view_manifest_sha256` — this is the **independent pin**.
2. Transfer **only** the Discovery view directory and the authority file to a **separate verification runner** that holds **no** canonical ZIP, no `XAUUSD_730d_20260919T114013Z` extraction, and no held-out data. That runner runs `src/qts/research/xauusd_directional_view.py::preflight_view()` — which validates authority schema, identity triple, manifest SHA, view provenance, each part's SHA, and **every row-group `time_msc` min/max** (`lo < cutoff`, `hi < cutoff`, `lo ≤ hi`, `null_count==0`, `has_min_max`, monotonic) **before** any `bid/ask` read. A mixed-boundary part is refused on manifest alone before footer read; cross-cutoff `ViewBoundaryViolation` aborts before `bid/ask` read. `h_dir_01_ran` stays false in any audit.
3. Only after `preflight_view()` passes on **every** part/row-group may `scan_attested_view()` → `evaluate()` (the frozen H-DIR-01 protocol) be invoked on that runner. Its report must carry `held_out_span_opened=false`, `held_out_rows_read=0`, and the runner's evidence `runner_proven_unable_to_access_held_out_in_a_real_run=true` (separate artifact attesting the runner's filesystem contains no held-out source).

## 5. Clock-basis confirmation (independent, required before any temporal study, optional for H-DIR-01)

Raw `time_msc` order is sufficient for H-DIR-01 (order, not wall-clock hour). For any future `H-TOD-01` / session study, a separate controlled probe (`scripts/probe_mt5_history.py` pattern) measures `copy_ticks_range` stamps vs UTC reference, documents the measured server-local offset, and sets `timestamp_interpretation_confirmed: true` only after auditable replication. No hour/session test may run until that flag is true.

## 6. What this amendment does not authorize

* No change to `975b686...`, `d9a61ad...`, or `26aee82...` — the canonical archive stays immutable and is not overwritten.
* No change to H-DIR-01's prediction, effect floors (`T1 ≥ $0.05`, `T2 ≥ $0.05` ≈ 5 grid steps + spread+2c + delay), horizons (256 primary / 1024 stability), sampling (`i % (h+18)==0`, non-overlapping within horizon), block-bootstrap (1,024-anchor blocks, 9,999 draws, seed 20260923, tercile-count gated), or stopping rules.
* No inference from a truncated Discovery population (e.g., `70,783,710` rows to `part-000440` boundary) — that would be a different experiment and is not H-DIR-01.
* No substitution of Dukascopy 15m mid, synthetic 1H, or forward-observatory ticks for the gap.
* No `order_send`, no Demo/Live execution, no held-out peeking to "validate" the reacquired bytes against the mixed part (that would leak held-out).

## 7. Success and failure criteria

* **Success (eligible to run H-DIR-01):** Discovery view `status: COMPLETE_DISCOVERY_ONLY`, `discovery_rows=70834426`, `source_rows=139930971`, `cutoff=1764563969254`, `time_msc_min=1726746013452`, every row-group max `< cutoff`, every part SHA matches authority, runner isolated — then a single H-DIR-01 report `docs/xauusd_directional_result_*.md` / `reports/xauusd_directional_result*.json` is produced under the frozen protocol. Its `T1/T2` floors and 99% lower bounds determine the outcome; a p-value alone does not. Even a pass remains Discovery-only until a separately preregistered out-of-sample check opens the held-out span (which this amendment does not do).
* **Failure (remain `NO VALIDATED EDGE`):** Any chunk in the Discovery span fails at the split floor, the view manifest never reaches `COMPLETE_DISCOVERY_ONLY`, the reacquired row count/manifest digest does not equal the published Discovery population, or the runner still holds any held-out source — then H-DIR-01 stays `NOT_RUN_ACCESS_BLOCKED` and the failure is committed as evidence (no silent repair).

## 8. Auditability

Reacquisition logs, `manifest.json`, per-part SHA-256s, `dataset_sha256`, `view_manifest_sha256`, and the authority file are committed as separate, hash-pinned artifacts. The original `XAUUSD_730d_20260919T114013Z` ledger and `reports/xauusd_discovery_boundary_audit.json` (file SHA `f2864545873...`) remain unchanged references. The `MT5_PACKAGE_UNAVAILABLE` absence in this Linux sandbox is the expected state; the real reacquisition has not happened until the operator run is present.

