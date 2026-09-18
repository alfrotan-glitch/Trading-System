# QTS Current State and Research Roadmap

**Status:** canonical current-state summary
**Repository branch:** `arena/01a0b574-trading-system`
**Checked:** 2026-09-18
**Current posture:** research-first, fail-closed, `NO_TRADE`

This is the current-state authority for status and sequencing. Historical design
baselines, generated evidence snapshots, and point-in-time verification reports
remain useful, but they do not override this page or the machine evidence they
identify.

## 1. Verified current state

| Area | Current state | Evidence / authority |
|---|---|---|
| Foundation and architecture | **Complete / strong.** Modular monolith, Python, SQLite + Parquet, canonical authorities, fail-closed boundaries, durable audit and testing foundations are present. | `docs/01-architecture.md`, `docs/canonical_authorities.md`, source/tests |
| Data provenance and quality | **Acquisition/provenance are strong; gap completeness required a P0 audit correction.** The frozen REAL acquisition artifact reported 12/12 under the previous event-count gate, but its inventory records 1,493 unexpected missing 15m intervals (5.42% of active expected span). The hardened gate now fails that population; no research rerun has been performed. | `src/qts/data/quality.py`, `docs/data_quality_protocol.md`, `docs/research_integrity_audit.md`, `data/evidence/research_integrity_audit.json` |
| REAL historical XAUUSD data | **Acquired and registered.** Version `20260918-010+8f120133-1ba57af7`; XAUUSD 15m; 26,038 rows; approximately 407 days; class `REAL`; source `REAL:dukascopy:vudo805@4d6f155:XAUUSD:15m:mid-from-bid-ask-ticks`. | Dataset manifest and `docs/data_provenance_xauusd_dukascopy.md` |
| Historical execution-cost evidence / R5 | **Unresolved.** The canonical bars contain no continuous historical bid/ask, measured spread, fill, latency or slippage history. R5 is **FAIL and non-blocking**. The supplementary 23-window spread study is not continuous and is not an R5 gate input. | `data/evidence/impulse_research_xauusd_dukascopy_15m.json`, `docs/research/impulse_continuation_evidence.md` |
| REAL impulse research | **Frozen evidence exists from the existing preregistered design.** The locked partition was untouched; no candidate was promoted. The audit did not rerun it after correcting the gap gate. | `data/evidence/impulse_research_xauusd_dukascopy_15m.json`, `docs/research_integrity_audit.md` |
| Research conclusion | **`REGIME_DEPENDENT`; `go_block = BLOCK`.** This conclusion is unchanged and is not a promotion signal. | REAL impulse evidence artifact and report |
| Trade outcome transparency | **Implemented.** Existing event-level `net_return_bps` outcomes are reported per family and primary horizon as measured directional event-study outcomes. They are not executed broker trades or fills. | `src/qts/research/impulse/measurement.py`, `analysis.py`, `report.py`, `docs/research/impulse_continuation_report_xauusd_dukascopy_15m.md` |
| FO-R1 observation infrastructure | **Engineered and hardened at the repository boundary.** SQLite canonical storage, durable acquisition accounting, snapshot support, integrity checks, long-session protections and structural order-free enforcement exist. | `docs/forward_observation_status.md`, `src/qts/observability/forward_observatory.py`, `src/qts/observability/research_snapshot.py` |
| Real MT5 observation evidence | **Pending.** No real Windows/MT5 observation session is present in repository evidence. A real operator run is required; all current verification is structural/controlled-environment verification. | `docs/forward_observation_status.md`, canonical observatory state |
| Research breadth | **Incomplete.** The current real result is one XAUUSD/timeframe study. Feature-store maturity, broader regime coverage, independent markets/timeframes and additional preregistered hypothesis families remain future research work. | `docs/timeframe_research.md`, `docs/cross_market_research.md` |
| Validated profitable edge | **Not established.** No result authorizes a profitability claim, candidate promotion or execution. | REAL impulse conclusion, campaign/edge artifacts, release report |
| DEMO execution | **Disabled by policy.** `DEMO_FORWARD` is observation-only and structurally order-free. `DEMO_EXECUTION = DISABLED BY POLICY`. | `qts.lifecycle.demo_authority`, `docs/canonical_authorities.md` |
| LIVE | **Locked.** No research, paper, shadow, observation or readiness result unlocks LIVE. | `qts.lifecycle.live_gate`, `docs/production_boundary_report.md` |

The unchanged synthetic XAUUSD 1H fixture remains useful for mechanism-validation
tests only. It is not a substitute for the REAL 15m dataset and must not be
combined with it as if it were the same evidence population.

## 2. Terminology that must remain separate

| Term | Meaning in this repository | What it does not mean |
|---|---|---|
| REAL historical data | Provenance-qualified historical Dukascopy-derived mid OHLC bars. | MT5 broker history, executable bid/ask, fills, or live-account evidence. |
| DEMO_FORWARD observation | Real MT5 demo-account quote observations collected by the order-free collector. | DEMO execution, a trade, a fill, or LIVE evidence. |
| Event-study outcome | One measured directional return for one family-scoped detected event at one configured horizon. | An order submitted, broker fill, realized P&L, or independent pooled trade population. |
| Paper result | Simulated fill/result generated by the paper path. | Broker execution or market fill evidence. |
| Shadow intent | A would-be action recorded without submission. | An order, fill, or permission to execute. |
| R5 evidence | Continuous, provenance-qualified historical execution-cost observations suitable for the declared research question. | A declared cost assumption or the supplementary event-selected spread windows. |

## 3. Roadmap and sequencing

The following sequence is intentionally staged. Items later in the list are not
immediate tasks and must not be used to justify weakening an earlier gate.

### A. Current mission — documentation/state convergence

**State:** completed by this audit/reconciliation change. It establishes one
status authority, corrects the gap/provenance implementation, and labels older
snapshots rather than rewriting historical evidence.

### B. Next gated milestone — data-quality disposition, then real MT5 observation

The corrected completeness `FAIL` is a blocking data-quality finding. Review it
against the frozen research lineage and either acquire/re-register an adequate
immutable dataset or explicitly document the research limitation before any
claim-bearing milestone. Do not weaken the 2% gate.

After that disposition and the documented readiness checks pass, run the
existing FO-R1 order-free protocol on a real Windows/MT5 demo terminal.
Preserve the canonical SQLite store, acquisition ledger, snapshot/export
lineage and safety assertions. This produces observation evidence only; it does
not produce execution evidence, a profitable edge, or permission to submit
orders.

No real MT5 session is currently present, so this remains an
operator/environment milestone rather than a claim that the repository has
already met it.

### C. Historical execution-realism research milestone — resolve R5 where possible

Acquire or license provenance-qualified continuous bid/ask/tick and, where
available, broker-session/execution-cost history. Register it as a new immutable
dataset or explicitly versioned evidence source. Do not relabel the current mid
bars, and do not promote the supplementary 23-window spread study into R5.

### D. Research milestone — rerun the existing preregistered study on improved evidence

If a valid R5-capable dataset becomes available, rerun the existing preregistered
impulse design with the same hypothesis, definitions, gates, locked-partition
rules, cumulative trial accounting and provenance discipline. Improving evidence
must not become changing the hypothesis to seek a positive result. The current
`REGIME_DEPENDENT / BLOCK` conclusion remains the authoritative result until a
new, separately identified run produces a different conclusion.

### E. Future research breadth

After the evidence base is adequate, separately preregister and test:

- feature-store maturity and leakage-controlled feature research;
- additional causal regime and stability studies;
- longer/multi-year history where licensed and supportable;
- independent timeframe and cross-instrument populations;
- additional hypothesis families with falsification, null/placebo, OOS and
  multiple-testing controls.

Breadth is research work, not a shortcut around R5 or the existing gates.

### F. Future paper/shadow validation

Only after a candidate hypothesis has sufficient research evidence, use paper and
shadow paths to compare simulated/would-be behavior under explicit, immutable
assumptions. Paper fills, shadow intents and comparison metrics remain separate
from DEMO_FORWARD observations and broker execution evidence.

### G. Future candidate lifecycle

A candidate lifecycle review requires the unchanged research gates, provenance,
cost/execution evidence, out-of-sample and forward evidence, risk/reconciliation
health, cumulative ledger accounting and explicit human governance. A candidate
is not created merely because an event-study row has positive expectancy.

### H. Future governed execution

Any future product decision about execution requires a separate human-governed
review of all applicable evidence and safety controls. Until then:

- `DEMO_EXECUTION` remains disabled by policy;
- `LIVE` remains locked;
- `NO_TRADE` remains the safe default;
- no order path is added by this roadmap.

## 4. Current blockers and non-claims

- R5 execution-cost history is still **FAIL / non-blocking**.
- No real MT5 observation session is present in repository evidence.
- No validated profitable edge has been established.
- The REAL impulse result remains `REGIME_DEPENDENT / BLOCK`.
- Event-study outcomes must not be described as broker trades, fills or realized
  P&L.
- Historical `FS-aeb881` evidence remains untouched and is not repaired or
  backfilled by this roadmap.

For the detailed evidence, use the linked machine artifacts and the current REAL
impulse report. For historical design assumptions or point-in-time test counts,
read those documents as labelled snapshots, not as replacements for this page.
