# Impulse Continuation Research — Evidence Pointer

**Updated:** 2026-09-18
**Current (REAL) artifact:** `data/evidence/impulse_research_xauusd_dukascopy_15m.json`
**Current (REAL) report:** `docs/research/impulse_continuation_report_xauusd_dukascopy_15m.md`
**Historical (synthetic) artifact:** `data/evidence/impulse_research.json`
**Historical (synthetic) report:** `docs/research/impulse_continuation_report.md`

## Current run — REAL dataset

The pre-registered impulse studies were re-run unchanged against the first
claim-eligible dataset, `20260918-010+8f120133-1ba57af7` (XAUUSD 15m, 26,038
Dukascopy tick-derived mid OHLC bars, 407.00 days, class `REAL`, 12/12 quality
checks pass). It executed in `REAL_CLAIMS` mode and passed the adequacy checks
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
