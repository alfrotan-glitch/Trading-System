# Trial-count audit for 2026-10-19 long-history screens

**Initial audit:** completed before the cross-metal candidate/comparator screen was measured. This note documents the inherited denominator and subsequent separately preregistered configuration increments; it does not change any frozen protocol or gate.

## Long-history denominator used by this screen

The preregistration inherits the long-history programme's `N_TRIALS = 355` and counts its single new configuration as trial 356. The protocol-module chain through VOLM is executable and checked by `tests/unit/test_longhistory_trial_ledger.py`: 26 → 40 → 47 → 50 → 72 → 149 → 193 → 237 → 262 → 285. The five subsequent exploratory waves are separately recorded in the expert handbook and QTS project-control history:

| Addition after VOLM | Recorded configurations | Cumulative N |
|---|---:|---:|
| Wave 6 | 22 | 307 |
| Wave 7 | 20 | 327 |
| Wave 8 | 10 | 337 |
| Wave 9 | 6 | 343 |
| Wave 10 | 12 | 355 |

The counts and scope are recorded in `docs/research/expert_handbook_2026-10-17.md` §4, `QTS_PROJECT_CONTROL.md` ARCH-069–073, and (for Wave 10) `data/evidence/longhistory/wave10_treasury_real_rate.json`. The 2026-10-17 audit records that the 26→285 protocol chain and committed DSR denominators were recomputed; it also notes that Waves 6–8 are supported by the ARCH prose ledger and discovery records, not by protocol modules. Therefore 355 is the frozen **long-history search-lineage count**, not a claim that every exploratory-wave increment has its own checked-in protocol module.

## Preregistered 2026-10-19 increments

| Cycle | Configuration increment | DSR denominator | Result |
|---|---:|---:|---|
| `LH-XAUUSD-CMR-2026-10-19` | 1 | 356 | REJECTED; `docs/research/crossmetal_relative_results_2026-10-19.md` |
| `LH-XAUUSD-BRENT-GATE-2026-10-19` | 1 | 357 | REJECTED; `docs/research/brent_gate_results_2026-10-19.md` |
| `LH-XAUUSD-FX-DISPERSION-GATE-2026-10-19` | 1 | 358 | INCONCLUSIVE for intended hypothesis (runner `REJECTED`; quote-convention conflict); `docs/research/fx_dispersion_gate_results_2026-10-19.md` |
| `LH-XAUUSD-COMMODITY-BREADTH-GATE-2026-10-19` | 1 | 359 | REJECTED; `docs/research/commodity_breadth_gate_results_2026-10-19.md` |
| `LH-XAUUSD-CPI-ACCELERATION-GATE-2026-10-19` | 0 evaluated (1 registered attempt) | 359 (unchanged) | INCONCLUSIVE before CPI features/outcomes (pinned CSV schema mismatch); full-repo review found prior Wave-9 CPI inflation gates, so do not retry this family; `docs/research/cpi_acceleration_gate_results_2026-10-19.md` |

The Brent-gate protocol was frozen at `N=356` before any Brent candidate values were read. Its one configuration was tested once, moving the denominator to `N=357`. The distinct FX-dispersion protocol was frozen at `N=357` before computing or inspecting its feature values; its one configuration was then tested once, moving the denominator to `N=358`. After that run, repository code review found that the protocol's README-based quote inversions conflict with the pre-existing monthly-builder quote contract. Preserve its `REJECTED` runner output, but treat the intended FX-dispersion hypothesis as `INCONCLUSIVE`; do not rerun or change the denominator. The separate raw-price commodity-breadth protocol was frozen at `N=358` before feature calculation and tested once, moving the current denominator to `N=359`; its screen was `REJECTED`. A CPI-acceleration protocol was then registered at `N=359`; its single runner invocation failed closed on a pinned CSV/schema mismatch before numerical CPI features or candidate outcomes were calculated. A subsequent whole-repository review also found that the prior Wave-9 CPI YoY-level and six-month momentum gates had already falsified the same inflation-regime conditioning family (expert handbook §7; ARCH-071). Record this as an inconclusive, non-novel registered attempt, not an evaluated configuration; the denominator remains `N=359`. Do not repair the source/loader or rerun this candidate/family. No CMR parameter or basket variant was tested, and none of the candidates was promoted.

## Why the separate `304` is not substituted or added

`docs/experiment_ledger.md` reports 304 for the `qts edge` SQLite `ExperimentStore`. The long-history reversal results had already recorded that the SQLite ledger and long-history protocol chain are different registries (`docs/research/reversal_results_2026-10-14.md` §7); the independent audit also treated the long-history chain separately. The current checkout has no `data/sqlite/qts.db` snapshot to recount the 304 rows, so the underlying general-store count cannot be independently reconstructed here. It is not evidence that the long-history chain should be reset to 304, and adding 304 to 355 would mix distinct registries and double-count unknown overlap.

## Decision and limitation

Use `N=356` for the CMR screen's **descriptive development-window DSR**, `N=357` for the Brent-gate screen, `N=358` for the frozen FX-dispersion runner output, and `N=359` for the commodity-breadth screen. Each of those protocols evaluated one configuration. The CPI-acceleration attempt failed before candidate outcomes and is not included; the current denominator remains `N=359`. The FX screen's runner outcome is preserved, but the intended hypothesis is inconclusive because of the post-run quote-convention conflict documented in its report. The CPI attempt is inconclusive because the pinned CSV did not satisfy its frozen schema. DSR is not an acceptance gate in any of these discovery/development screens. Do not interpret 359 as the complete number of all QTS experiments across every registry; the separate SQLite `304` remains uncombined. Do not revise any frozen protocol's denominator after outcomes are seen. The initial denominator audit itself calculated no candidate or comparator statistic.
