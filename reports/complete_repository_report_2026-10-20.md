# Whole-repository assessment — 2026-10-20

## Follow-up: operator isolation, evidence labels, and verification (2026-10-20)

This follow-up supersedes the earlier snapshot where stated.

> **Archive boundary:** the remaining detailed analysis below preserves prior audit snapshots, not current account-cost evidence or fresh performance claims. Do not use archived figures as current results; the current status is summarized in this follow-up and `QTS_PROJECT_CONTROL.md`.

The ordinary API/CLI research path no longer automatically loads archived market history or publishes historical performance as current output. Its explicit offline-evaluation path requires both an explicit input and opt-in, and only sets `evaluation_status="EXPLICIT_INPUT_EVALUATED"` after constructing the evaluation payload. The benchmark CLI is status-only. The long-history API summary is schema v2, marks the frozen candidates research-only/non-claim-eligible, and scopes independent verification to arithmetic reproduction rather than economic validation.

Broker specifications are now labeled `DOCUMENTED_REFERENCE_ONLY`; the old `measured_broker_costs.json` filename contains a supersession notice. Actual account spread, commission, slippage, and financing remain `UNMEASURED`. Historical reports are retained with archive notices; the current operator runbook no longer repeats their performance aggregates.

Current decision remains `NO_VALIDATED_EDGE`, cumulative `N=362`, `LIVE_LOCKED`, and zero real-capital exposure. This update did not rerun an edge screen, change parameters, submit an order, use post-1999 prices, or access the locked holdout. Remote CI and actual-account cost evidence remain unavailable here. The sandbox is Linux, with no `MetaTrader5` package or terminal executable; only simulated/integration DEMO tests ran.

Verification on the current working tree: Ruff passed; mypy passed on 201 source files; the Python fast suite passed 1,622 with 6 skips; integration plus research passed 379; the UI suite passed 48; targeted correction tests passed 38; JavaScript syntax checks passed. Bandit exited 0 but emitted pre-existing warnings. These are local test results, not remote CI or DEMO verification.

Repository reconciliation: the requested `c169c8a` and previously cited `e6a4193` commits are absent from the available object graph. The fixed Arena branch was fast-forwarded from `f468b0c` to remote Arena head `b6e56ae`; work remains on `arena/0c685e3b-trading-system`, not `main`.

**Audited revision:** `e6a41938a87f23d8ca0eb74646e8bb0e6eedaae7` (`e6a4193`)
**Audited branch:** `arena/0c685e3b-trading-system`
**Assessment type:** repository, product-state, safety-boundary, documentation, and local verification review. This is not a trading authorization, strategy validation, broker certification, or claim of profitability.

## Executive assessment

QTS is a substantial XAUUSD/MetaTrader 5 research and DEMO-execution workstation. It has a defined product architecture, a broad operator surface, persistent risk and order controls, a large research/evidence record, and meaningful automated test coverage. It is **not** presently an approved trading system: the canonical project register says `NO_VALIDATED_EDGE`, the research candidates remain paper-only, real execution costs are not established, and `LIVE` remains locked. The repository declares zero real-capital exposure and zero submitted orders; those are repository status statements, not a fresh broker/account inspection.

The strongest positive finding is that execution permission is intentionally separated from research and readiness: LIVE has a conjunctive evidence/governance gate, and DEMO pre-trade checks treat unknown or missing facts as blockers. The principal readiness gaps are:

1. no validated, cost-supported strategy;
2. no tracked raw market-history dataset in this checkout, limiting independent clean-checkout reproduction;
3. three current `mypy` errors in two research modules, which would fail the workflow's static-check step;
4. historical status/authorization documents that have drifted from the current register and source; and
5. no current Windows MT5, broker-cost, or account-eligibility verification in this assessment.

**Recommendation:** retain the safety lock, do not promote or tune rejected candidates, fix the static typing failures, reconcile the operator documents, and continue only with a distinct preregistered hypothesis using rights-cleared, eligible data and authorized partitions. Do not use this report as an edge claim.

## Scope and method

The review used the current checkout at the revision above; inspected repository organization, product/configuration files, CI definition, documentation and status records, source-module and route/command inventories, and selected lifecycle, risk, API, CLI, and execution code. It included a path-only inventory of tracked data files. It did not connect to MT5 or a broker, inspect account state, place an order, recompute a strategy result, access the locked 730-day holdout, or use post-1999 price values. The `data/evidence/mt5_history_analysis/` 730-day artifacts were identified by path only; their contents were not opened. No new hypothesis or research trial was added.

The counts below describe tracked files at `e6a4193`, before this report is added. Existing pre-2000 screen outcomes are summarized from their recorded research evidence. No post-1999 performance figure is used as new evidence here.

## Product purpose and current state

The project describes QTS as an autonomous quantitative-research, risk-governed validation, and forward-execution platform for **XAUUSD** through **MetaTrader 5**. The package is `qts` version `0.1.0`, supports Python `>=3.11,<3.15`, and exposes the `qts` command-line entry point. The product has distinct development and DEMO workflows; the canonical governance record keeps LIVE locked.

The current register, `QTS_PROJECT_CONTROL.md` (latest record ARCH-093, 2026-10-20), declares:

- research verdict: **`NO_VALIDATED_EDGE`**;
- long-history multiple-testing denominator: **N=362**;
- strategy promotion: **none**;
- LIVE: **locked**;
- submitted orders and real-capital exposure: **zero**;
- forward champions `ts9_lo` and `veto9`: paper-only, not validated or promoted.

A separate `qts edge` SQLite registry count of **304** is explicitly a different ledger and is not combined with N=362. Its stored count is not a substitute for the governed long-history denominator.

The registered DEMO measurement policy is `DEMO-XAUUSD-TREND-TSMOM-V1`: completed-bar XAUUSD M15 EMA(12/48), 0.01 registered lots, a USD 3.00/oz quote-price-distance stop (not a fixed-dollar loss cap), and a four-hour maximum hold. It is a diagnostic/measurement workflow, not an economic claim. The canonical register records that no real terminal was connected and no real order submitted during the relevant pass. This assessment likewise did not verify a terminal, account, live authorization, or current DEMO readiness.

## Repository organization

At the audited revision, the repository contained **821 tracked files**:

| Area | Tracked files | Role |
|---|---:|---|
| `src/` | 228 | Product and research implementation |
| `tests/` | 156 | Python and UI tests across unit, integration, research, and product areas |
| `docs/` | 186 | Operating guides, architecture, research protocols, and dated records |
| `data/` | 112 | Evidence records and a synthetic fixture |
| `scripts/` | 71 | Data, research, audit, and operator utilities |
| `reports/` | 54 | Dated assessments and generated reports |
| Other root/configuration files | 14 | Packaging, CI, UI-test setup, and repository metadata |

The tracked `data/` tree consists of **111 evidence paths and one fixture** (`data/fixtures/XAUUSD_1H_500.csv`). There is no tracked `data/raw/` or `data/processed/` market-history tree in this checkout. Consequently, code and evidence records may describe source-pinned historical studies without the corresponding raw source snapshots being available for a clean local reproduction. Several older register entries refer to raw/processed assets; those references should be read as historical records, not proof that the assets are present at this revision.

The Python package and UI tests are separated from scripts, documentation, and retained research artifacts. `package-lock.json` is tracked for the JavaScript test dependencies. No top-level LICENSE/COPYING/NOTICE file was found; `pyproject.toml` labels the package “Proprietary — internal research use.” External data rights remain source-specific and should not be inferred from the software package metadata.

## Architecture and major components

The documented design is a modular monolith with an inward dependency flow:

1. **Domain** — entities, value objects, modes, and events (`src/qts/domain/`).
2. **Lifecycle/governance** — DEMO authorization and readiness, LIVE readiness, promotion/evidence checks (`src/qts/lifecycle/`).
3. **Risk and execution** — persistent risk/kill-switch state, pre-trade validation, order lifecycle, journaling, idempotency, and reconciliation (`src/qts/risk/`, `src/qts/execution/`).
4. **Adapters** — MT5, paper, and shadow broker/data boundaries (`src/qts/adapters/`).
5. **Application surfaces** — FastAPI routes, Click CLI commands, and the desktop workstation (`src/qts/api/`, `src/qts/cli/`, `src/qts/desktop/`).
6. **Research/validation** — hypothesis registration, data-quality and provenance checks, causal signal builders, cost models, statistical validation, trial accounting, and evidence writers (`src/qts/research/`, `src/qts/validation/`).

The canonical design names `RiskEngine` as the SQLite-persisted risk and kill-switch authority; execution uses a durable order journal and reconciliation. The path authority anchors machine-local state rather than treating the Git checkout as a broker-state store. Market data can enter through MT5 or stored files; this review did not verify those live or historical feeds.

Selected safety-source review found that LIVE readiness is conjunctive and includes real MT5 connectivity and validated-edge evidence. The validated-edge check requires survival and promotion evidence; a research result or a passing readiness subset is not itself permission. DEMO pre-trade checks distinguish pass from missing/unknown facts and fail closed. These are source-review findings, not proof of a live broker workflow or an end-to-end production deployment.

## Research results, evidence, and provenance

### Current research disposition

The current governed result remains **`NO_VALIDATED_EDGE`**. Frozen monthly trend candidates `ts9_lo` and `veto9` remain research/forward-observation candidates only. Recent registered screens recorded by the project register are:

| Research family | Recorded disposition | Important boundary |
|---|---|---|
| Cross-metal relative momentum (CMR) | Rejected | Do not substitute another basket or tune/rerun on reused partitions. |
| Brent-gated trend | Rejected | No rescue or parameter change. |
| Commodity-breadth gate | Rejected | No rescue or parameter change. |
| FX-dispersion gate | Runner rejected; intended hypothesis inconclusive | The README-derived quote inversions conflict with the established monthly-builder convention; no correction/rerun. |
| US yield-curve inversion gate | Rejected | Frozen screen only; DFF rights/vintage remain unresolved for production use. |
| Fixed calendar-seasonality gate | Rejected | Do not change the mask or rerun. |
| Sahm/U-3 gate | **Rejected at N=362** | One frozen run; no tuning or rerun; revised U-3 snapshot lacks point-in-time vintages. |
| CPI-acceleration attempt | Inconclusive before outcome calculation | Frozen schema check failed; the related inflation-gating family is already closed, so do not repair/rerun this candidate. |
| COT/source discovery | No qualifying source admitted | Metadata-only scans found no rights-, coverage-, and provenance-qualified historical Gold archive. |

These are distinct statuses: an implementation/schema stop is not a negative performance result, and an intended hypothesis marked inconclusive must not be represented as tested successfully. Earlier daily, M15, weekly, seasonal, reversal, and hybrid studies remain historical research records with no promotion; their existence does not change the current verdict. The repository also has a frozen paper-only forward-observation protocol for `ts9_lo`/`veto9`; it is a monitoring plan, not a validated edge or permission to execute.

### Sahm/U-3 result (pre-2000 partitions only)

The single preregistered candidate, `sahm_u3_ts9_longflat`, used a two-month-lagged U-3 feature: the three-month average at least 0.50 percentage points above the minimum of the prior twelve three-month averages, gating the frozen nine-month long-or-flat Gold trend. It was evaluated once on selection (1973–1983), confirmation (1984–1989), and development (1990–1999); no final stage or holdout was used.

| Partition | Candidate net per independent $10,000 | Sharpe | Round turns | Positive years |
|---|---:|---:|---:|---:|
| Selection, 1973–1983 | −$512.28 | −0.1185 | 5 | 3/11 |
| Confirmation, 1984–1989 | $0.00 | 0.0000 | 0 | 0/6 |
| Development, 1990–1999 | −$52.81 | −0.4661 | 2 | 0/10 |

In development, `ts9_lo` recorded −$1,171.24 / −0.2579 Sharpe and `veto9` +$1,827.96 / +0.2678; the candidate lost to `veto9`. Paired 95% bounds were negative and the recorded Holm-adjusted p-values were 0.3334 and 0.7897. The result is **REJECTED**, not evidence of a usable edge. The corrected U-3 source commit is `23d5e7795325ce1a69d02bd52e20ad075983082a`; the recorded Git blob SHA-1 is unchanged. The source correction was metadata-only and did not trigger a rerun or recomputation.

### Data and evidence limitations

The recent long-history screens used governed pre-2000 partitions. This assessment did not inspect raw market-data rows or use any post-1999 price values. The recorded source audits found:

- no admitted COT Gold archive meeting the required coverage, release-time/vintage, licensing, and provenance gates;
- FRED-backed repositories that call the FRED API are not bundled historical datasets, consistent with the project owner’s correction;
- bundled M2 coverage begins too recently for the specified monthly screen;
- the annual employment mirror is not suitable for the monthly Sahm screen;
- the pinned revised U-3 snapshot is not a real-time vintage; and
- rights/vintage questions remain for some compiled macro series, including DFF.

A source commit or file hash establishes identity, not data rights, point-in-time availability, or economic validity. Do not substitute the commodity panel’s precomputed features for causal features: any future authorized use must use raw `price_nominal_usd` from eligible pre-2000 rows and compute features causally. Do not open the locked 730-day holdout or use post-1999 price values.

## Execution, risk, and safety boundaries

The system’s principal safety boundary is the separation between **research**, **DEMO measurement**, and **LIVE permission**:

- `LIVE` remains **LOCKED**; no validated-edge promotion is recorded.
- LIVE readiness requires all required checks, including real-terminal connectivity and explicit validated-edge evidence. This assessment did not connect a terminal.
- DEMO pre-trade checks fail closed on unknown/missing authorization, broker identity, market-data freshness, risk, or reconciliation facts. The registered DEMO policy is not an approved strategy.
- Risk controls include persistent kill-switch/risk state, explicit order journaling, idempotency, and broker-position reconciliation. A safety-control implementation is not proof that a real terminal/account passed those controls today.
- The runbook records all-in broker costs and regional/account eligibility as unresolved. It cautions against bypassing regional restrictions and against placing a new order merely to obtain cost evidence. Prefer read-only symbol probes or evidence from already-existing authorized DEMO deals.

The desktop API is local-operator oriented: the launcher defaults to `127.0.0.1`, and state-changing browser requests are subject to trusted-origin checks. The server also supports an explicit `QTS_CORS_WILDCARD=1` configuration. Treat this API as local/trusted-network software, not as a hardened multi-user public service; do not expose it publicly or enable permissive CORS as a deployment shortcut.

## UI, API, CLI, and operator workflows

The FastAPI application composes system, market, trading, risk, research, and DEMO route groups. The desktop product presents Home, Market, Trading, and Reports as primary views, with engineering tools under Advanced. The JavaScript client is a small ES-module/CSS workstation rather than a separate server-rendered frontend.

The `qts` Click CLI provides data/bootstrap, DEMO, edge, research, risk, audit, evidence, and desktop workflows. The Windows runbook covers setup, MT5 connectivity, identity binding, readiness, DEMO measurement, and blockers. Development/bootstrap mode can exercise the product with synthetic data; that data is useful for plumbing and mechanism tests only and is not a substitute for claim-quality market history. The real MT5 Python package and terminal are Windows-bound, so Linux CI and this sandbox cannot establish live broker interoperability.

## Tests, static checks, and CI

The configured GitHub workflow has a fast Ubuntu job using Python 3.11 and Node 20 (Ruff, mypy, Bandit, Python tests excluding `tests/integration` and `tests/research`, then UI tests), plus an extended integration/research job with explicit opt-in flags. No remote GitHub check for this unpushed Arena-branch revision was run or verified.

Local verification for this report:

| Check | Result |
|---|---|
| `ruff check src/ tests/` | Passed. |
| `mypy src` | **Failed: 3 errors in 2 files.** `yield_curve_gate.py:263–264` reports missing `to_period`/`to_timestamp` attributes on an inferred `Index[Any]`; `sahm_u3_gate.py:121` reports an incompatible `Index.difference` argument type. |
| `bandit -q -r src` | Exit code 0. It emitted warning noise for comment/test-name parsing and `nosec` markers; this is not a security certification. |
| Fast Python suite | **1,620 passed, 6 skipped, 12 warnings** in 162.93 seconds with four workers; `tests/integration` and `tests/research` were excluded. |
| JavaScript UI suite (`npm test`) | **48 passed, 0 failed.** `npm ci` reported zero dependency vulnerabilities. |
| Previously run focused research/UI subset | **160 passed, 37 skipped, 9 warnings.** This is not an extended-suite result. |

The `mypy` failure is the most immediate CI issue: the workflow’s static-check step will stop at these observed errors. The integration and research suites were not run for this assessment, and no holdout-related test or raw-data evaluation was authorized. A serial fast-suite attempt was stopped at the time limit; the four-worker run above completed successfully. Do not describe the fast-suite result as full-suite or CI verification.

## Documentation and repository-quality findings

1. **One authoritative status source, several stale records.** `QTS_PROJECT_CONTROL.md` is the current project register (latest entry ARCH-093). `docs/evidence/current_state.md` is dated September and explicitly defers to it. `reports/FINAL_REPORT.md` is dated October 18 and describes a historical branch/push state; it is not current branch status. The register calls `main` canonical, while this report audits the assigned Arena branch; it does not imply that this revision is merged to or present on `main`.
2. **DEMO authorization documentation needs reconciliation.** The September 23 DEMO authorization/safety note contains an older invalid-artifact/key claim. Later register entries say `max_drawdown_pct` was implemented and applied, and the current authorization source allows that key. Treat the old note as historical, not as a current runtime verdict. Confirm authorization and readiness in the operator’s actual environment before any DEMO workflow.
3. **Research planning docs need a current ledger cross-check.** `docs/11-edge-discovery-v2.md` is an earlier campaign plan; several related families have since been screened and closed. Do not start from that plan without checking the current register, frozen protocols, and do-not-rerun dispositions.
4. **Evidence files are not raw data.** Historic entries may describe source snapshots and analyses that are not present in the current tracked `data/` tree. Keep “the report says a source existed” distinct from “this checkout contains it and can reproduce it.”
5. **Licensing and reproducibility need a clearer release boundary.** The project is marked proprietary/internal, has no top-level license notice, and uses sources with differing terms. Maintain a source-by-source rights/vintage manifest before redistributing datasets or results. Python dependency ranges are minimum-version constraints rather than a Python lockfile; the UI test dependencies do have `package-lock.json`.
6. **Platform verification is narrower than the product surface.** CI is Linux-only and does not prove Windows MT5 installation, terminal identity, account eligibility, broker fills, or measured costs. Those need a separate documented operator acceptance run, without weakening the trading gates.

## Prioritized next steps

### P0 — Keep the safety posture

- Keep LIVE locked and DEMO as a measurement-only, explicitly authorized workflow. Do not infer permission from a passing subset of readiness checks.
- Preserve every rejected/inconclusive disposition. Do not tune, rescue, or rerun a screened candidate on reused partitions; do not open the holdout or use post-1999 price values.

### P1 — Restore current verification and clarity

- Resolve the three `mypy` errors with explicit index typing/casts or clearer construction, then rerun Ruff, mypy, Bandit, the fast suite, and UI tests.
- Reconcile the stale DEMO authorization and status documents against `QTS_PROJECT_CONTROL.md` and current source; label historical records clearly and surface the actual operational blockers.
- Add a lawful, provenance-complete raw-data acquisition path or use an authorized local source. Pin source version, hash, units, timestamp basis, coverage, license, and vintage; do not commit large/raw datasets unless the repository’s storage policy permits it.

### P2 — Continue research without post-hoc selection

- Preregister a **distinct** hypothesis before examining its feature values; use only authorized partitions and the existing multiple-testing ledger. Stop on failed provenance/schema gates rather than substituting a source or parameter after seeing results.
- If using a commodity panel, read only raw `price_nominal_usd` values on eligible pre-2000 rows and compute features causally. Do not admit precomputed features or unverified point-in-time macro series.
- Continue paper forward observation of the frozen candidates without changing their definitions. Measure execution costs only from authorized read-only probes or already-existing DEMO executions; no order should be placed solely to produce a cost sample.

### P3 — Complete operational acceptance before any permission change

- On the authorized Windows host, separately verify MT5 installation, broker identity, current account eligibility, market-data freshness, risk ceiling, kill switch, and reconciliation. Record blockers and evidence; do not bypass regional restrictions.
- Run the extended integration/research suite only against approved fixtures/partitions and document exactly what it reads. Obtain independent CI and operator review before changing any promotion or execution status.

## Final conclusion

At `e6a4193`, QTS has a well-developed research/execution architecture and substantive fail-closed controls, but the repository evidence does **not** establish a validated net-profitable edge or readiness for LIVE trading. The most recent governed screens remain rejected or inconclusive, raw research inputs are not present in the tracked checkout, broker costs and account eligibility are unresolved, and the current type-check step fails. The correct operating conclusion is **research-only, no validated edge, no promotion, LIVE locked**. Continue the search only under the preregistration, data-rights, partition, and safety constraints above.
