# FO-R1 — current observation-boundary status

**Status:** current for the repository branch `arena/01a0b574-trading-system`.
This page is the canonical statement of what the observe-only boundary can and
cannot do **today**. The historical hardening commit identifiers retained in the
blocker table are implementation lineage from the original observation change;
they are not the current branch identifier. This page deliberately does NOT
rewrite the historical design/baseline documents:
`docs/forward_observation_research_plan.md` remains the FO-R1 design of record and its
"acquisition prerequisites" table is a snapshot of the baseline it inspected
(`5607962`) — several rows of that table are now closed in code, which is
recorded here rather than edited into history.

Nothing here claims research results. No edge, no profitability, no LIVE
qualification. `DEMO_EXECUTION` is authorized for the DEMO account but gated per
order (currently `NO_TRADE`) and `LIVE` remains locked; the observation runtime
has no order path at all.

## 1. Blockers closed (with the commit that closed them)

| Blocker | Closed by | Evidence |
|---|---|---|
| A recovered transient error was persisted as the session's terminal `error`, so a normal operator stop exported `ENDED` + `error` and the hardened verifier correctly refused it as contradictory. | `7829160` | `ObservationCollector._finish()` derives the terminal error only for an automatic failure. Regression: transient error → recovery → manual stop exports `ENDED` with no terminal error and verifies `CONSISTENT`. |
| A storage/manifest exception escaped the poll body, killed the worker thread and left the session advertising `OBSERVING` with `0` failures recorded and the row stuck `ACTIVE`. | `cd7948b` | Poll body fail-closes over retrieval AND persistence; `_finish()` cannot raise and always flips state; the terminal session write is bounded-retried and `stop()` retries a failed persist. |
| Record identity was 6 hex characters (24-bit) — ~50 % birthday-collision probability near 4.8k records. | `cd7948b` | `ObservationTick.id` is now full 128-bit hex. Session IDs keep the canonical `FS-<6 hex>` form the v1 verifier requires. |
| No durable record of acquisition attempts, skips, rejections or missed slots; only in-memory counters. | this change | Additive `observation_attempts` table in the SAME canonical store + `record_attempt`/`attempt_reconciliation`/`clock_history`/`stale_active_sessions`. |
| Record identity collisions were undetectable at the store level (writes used `INSERT OR REPLACE`). | `901ef91` (strict `INSERT`), verified by this change | A duplicate identity now raises `IntegrityError`; the ledger records the failed persistence as `STORAGE_ERROR`, and the original record is preserved. |
| Periodic manifest publication re-scanned the whole session (O(N) per publication, O(N²) per session). | this change | The default publication path is O(1) via an incremental aggregate; the authoritative full regeneration remains available explicitly (`from_store=True`). |

## 2. What the three evidence layers each prove

| Layer | Contract | Proves | Does NOT prove |
|---|---|---|---|
| **v1 audit artifact** | `qts.session_evidence.v1` (`session_export.py`, unchanged) | Internal consistency + contract conformance of a *projection* of one session: counters recomputed from the store, per-row sha256 digest chain, allowlisted metadata with credential redaction, order-freedom and lifecycle assertions. | Not a dataset: prices and most raw stamp pairs are not hash-bound; only ten default sample payloads travel; no acquisition ledger. |
| **Research snapshot** | `qts.research_snapshot.v1` (`research_snapshot.py`, new, separate) | The COMPLETE accepted dataset of one session (every full payload, hash-bound), the complete acquisition ledger, session/run/clock identity, schema + code identity, and independent integrity checks. Refuses missing rows, count mismatches, ledger/store disagreement, payload/hash disagreement, session mismatch, provenance mismatch, identity conflicts and malformed metadata. | Terminal reality, Desktop origin, exporter authenticity. |
| **Acquisition ledger** | `observation_attempts` in the canonical store | Every acquisition attempt has exactly one classified outcome, reconcilable against accepted rows in both directions. | That an attempt produced a valid market observation — a `DUPLICATE`, `VALIDATION_REJECTED`, `RETRIEVAL_ERROR` or `STORAGE_ERROR` attempt never enters accepted data. |

Neither artifact is promotion- or LIVE-grade evidence. Both say so in their own
output (`verification_limits`).

## 3. Durable acquisition accounting

One row per acquisition attempt, in the canonical observation store:

`SESSION_START | STORED | DUPLICATE | VALIDATION_REJECTED | RETRIEVAL_ERROR | STORAGE_ERROR | UNRESOLVED`

Invariant, checked by `attempt_reconciliation()`:

```
stored + duplicate_skip + validation_reject + retrieval_error + storage_error + unresolved == attempts
```

plus, in both directions, `accepted rows == STORED ledger entries`
(`missing_record_ids` / `orphan_store_ids` must both be empty), gapless
per-session `seq`, nominal-slot coverage (`expected_slots`, `serviced_slots`,
`missed_slots`, explicit missed ranges), and a ledger heartbeat
(`last_attempt_age_s`) that flags an `ACTIVE` session gone quiet
(`stale_active`) — the durable detector for a worker that died without writing
a terminal state.

Honesty rules: a missed slot or an `UNRESOLVED` attempt is **never** market
activity (it carries no price); a rejected observation never enters accepted
tick data; ledger persistence failures are carried as `deferred` rows and, if
the bounded backlog overflows, collapse into ONE explicit `UNRESOLVED` marker
rather than disappearing.

`MarketDataError.kind` distinguishes an unobtainable tick (`unavailable` →
`RETRIEVAL_ERROR`) from a rejected quote (`validation` → `VALIDATION_REJECTED`)
without parsing message text. Neither is ever persisted.

## 4. Run / clock / source metadata

Stored once per session in the session meta as `qts.run_metadata.v1`:

* code identity (package version + resolved git SHA);
* configuration identity — sampling policy (interval, failure tolerance,
  manifest cadence, duplicate policy) and validation thresholds (max tick age,
  max spread, future guard), with a reproducible `config.hash`;
* canonical + broker symbol, privacy-preserving broker identity (masked login,
  server, terminal build);
* hashed symbol-specification snapshot (no `raw` block, no machine path);
* clock block: the broker offset measurement, plus an explicit
  `measurement_time: UNAVAILABLE` marker (the adapter exposes the offset and
  its basis, not the measurement timestamp) and an explicit
  `host_clock: UNAVAILABLE` marker (no host clock-sync probe exists in this
  architecture);
* privacy declaration: no credentials, no absolute paths, login masked.

Per-attempt offset/basis is recorded in the ledger, so `clock_history()`
reports the measured-offset history for a session (distinct offsets, first/last
seen, basis, and whether the offset changed mid-session).

Absent facts are recorded as explicit `UNAVAILABLE` markers with a reason.
Nothing is invented, and nothing unavailable is reported as zero.

## 5. Long sessions

* Accepted-record persistence is unaffected by session length (one append per
  accepted observation, plus one append per attempt for the ledger).
* Derived manifest publication is O(1): it reads the incremental aggregate, not
  the session. Query footprint is asserted to be independent of session size,
  and the bounded manifest is asserted to agree with the authoritative
  `from_store=True` regeneration.
* The authoritative full regeneration from canonical storage remains available
  for audits and is never on the periodic path.

## 6. Still open (not closed by this work)

1. **Complete broker tick coverage is impossible on this path by design.** The
   collector samples the latest quote at a requested 1.0 s cadence; it is not a
   tick stream. Quote-arrival intensity, true tick OHLC, order flow and
   sub-second microstructure remain out of scope.
2. **Censored sample.** The unchanged guards (stale > 5 s, spread > 100 bps,
   future > 1 s, integrity, symbol identity) reject data by construction, so
   accepted quotes are a censored sample; the ledger makes the rejection
   *visible*, it does not remove the censoring.
3. **Host clock health is UNAVAILABLE.** No OS clock-synchronization probe
   exists, so host-clock uncertainty cannot be stated.
4. **Broker offset measurement time is UNAVAILABLE** (only offset, basis and
   cache stamp are exposed).
5. **No campaign calendar/event sidecar.** Trading-date mapping, holiday/DST
   calendars and scheduled-event context required by the FO-R1 sampling strata
   are not implemented.
6. **Real-environment evidence is not established here.** All verification in
   this repository is structural/behavioral against controlled doubles. A real
   Windows/MT5 demo terminal run is an operator step.
7. **Long-session behavior under a real multi-million-row store is not
   benchmarked** — the bounded-path property is asserted structurally and by
   query-footprint, not by a soak on real hardware.
8. **`FS-aeb881` remains as stored.** Its session row was written by the
   pre-`7829160` code and still exports `REFUSED`; this work neither repaired
   nor backfilled it and added no repair mechanism. A fresh session is the
   correct path forward.

## 7. Operational use

```bash
# on the desktop that observed (canonical store required)
python -m qts evidence export-session  <FS-id> --db <store>   # v1 audit artifact
python -m qts evidence verify          <artifact.json>
python -m qts evidence export-research <FS-id> --db <store>   # complete research snapshot
python -m qts evidence verify-research <snapshot.json>
```

Transfer only the exported artifacts. `*.session_evidence.json` and
`*.research_snapshot.json` are git-ignored: raw observation data must not enter
project history.

## 8. Verification status of the hardening snapshot

The verification table below is the historical hardening snapshot from the
original observation change (`2050541`), retained for its evidence lineage. It
is not a current test count for the `arena/01a0b574-trading-system` branch. The
current branch's code is the authority for present behavior; no real Windows/MT5
operator session is implied by these controlled-environment checks.

The repo's CI definition (`docs/ci/ci.yml`) is executed manually — there is no
`.github/workflows` in this repository.

| Step | Result |
|---|---|
| `pytest tests -q --cov=qts --cov-fail-under=60` | coverage 68.32 % ≥ 60 % (pass) |
| `pytest tests` | 785 passed, 21 skipped, 2 warnings |
| `pytest tests/integration -q --run-integration` | 18 passed |
| new tests (`test_observation_attempt_journal.py`, `test_research_snapshot.py`, `test_observe_manifest_scaling.py`) | 54 passed |
| focused observation/evidence/adversarial batch | 329 passed |
| pre-fix proof (sources reverted, new tests kept) | 28 failed, 3 passed, 23 errors |
| `ruff check src tests` | clean |
| `mypy src/qts --ignore-missing-imports` | clean (one pre-existing error at `cd7948b` fixed) |
| `python -m compileall -q src tests` | clean |
| `bandit -r src -q` | **pre-existing failure**: 2 LOW `B311` in `research/null_control.py` and `research/placebo.py` (unchanged by this work; CI's `bandit` step therefore fails on this repo before and after) |
| `ruff format --check src tests` | **pre-existing failure**: drift in 14 files; this change removes `demo_collector.py` from that list and adds none |
| `node --test tests/ui/js/*.test.mjs` | 50 pass, 6 fail — all 6 are the same `tests/ui/js/shell.test.mjs` timeouts ("timeout waiting for mode fact") present identically at `cd7948b`, i.e. pre-existing and environmental |

No store, artifact or manifest produced by a real observation session is
committed; `data/evidence/*.research_snapshot.json` and
`*.session_evidence.json` are git-ignored.
