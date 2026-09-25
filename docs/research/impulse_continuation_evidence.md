# Impulse Continuation Research — Evidence Pointer

> Current project status and sequencing: [`docs/evidence/current_state.md`](../evidence/current_state.md).

**Updated:** 2026-09-18
**Frozen REAL artifact:** `data/evidence/impulse_research_xauusd_dukascopy_15m.json`
**Frozen REAL report:** `docs/research/impulse_continuation_report_xauusd_dukascopy_15m.md`
**Historical (synthetic) artifact:** `data/evidence/impulse_research.json`
**Historical (synthetic) report:** `docs/research/impulse_continuation_report.md`

## Frozen REAL run — preserved research evidence

The pre-registered impulse studies were run unchanged against the first
acquired REAL dataset, `20260918-010+8f120133-1ba57af7` (XAUUSD 15m, 26,038
Dukascopy tick-derived mid OHLC bars, 407.00 days, class `REAL`). The frozen
run recorded 12/12 quality checks under the previous event-count-only gap gate;
the preserved legacy inventory records 1,493 unexpected missing 15m intervals
(5.42%), while the current conservative audit finds 1,785 intervals (6.42% of
27,823 active expected intervals). The hardened completeness gate is now FAIL.
This report remains frozen research lineage; no rerun was performed. It executed in
`REAL_CLAIMS` mode and passed the adequacy checks
R1 (provenance), R2 (depth), R3 (span), R4 (freshness) and R6 (event count);
R5 (tick/execution-cost data) remains **FAIL and non-blocking** because the
canonical bars contain no continuous bid/ask or tick history.

Measured result (unchanged conclusion, no promotion):

> `REGIME_DEPENDENT` — `go_block = BLOCK`; the locked partition was not
> touched and no candidate is promoted.

The machine artifact records the full preregistered configuration, families,
partitions, exclusions, trial lineage, cost assumptions, statistics, and safety
state. Treat it as the current impulse evidence; treat R5 as an explicit
limitation, not a hidden assumption.

## Historical run — synthetic fixture

`data/evidence/impulse_research.json` and
`docs/research/impulse_continuation_report.md` remain the
`MECHANISM_VALIDATION` baseline on the **synthetic** fixture
`20260918-010+c83567cb-572728d9` (XAUUSD 1H, 500 bars). It is not real-market
evidence and its adequacy gate is false (provenance `SYNTHETIC`, depth/span
insufficient, execution fields absent).

Do not copy metrics from the mechanism study into the edge scorecard or treat
declared cost assumptions as broker observations. Re-run research only against
a newly registered immutable dataset and preserve the cumulative trial ledger.
