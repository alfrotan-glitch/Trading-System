# Changelog

All notable changes to QTS are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use semantic
versioning. **No release changes the safety posture:** `LIVE` is locked,
`REAL_CAPITAL_EXPOSURE` is `0`, and `NO_VALIDATED_EDGE` stands unless a future
release says otherwise with evidence.

## [Unreleased]

Research harness and the acceptance gate for XAUUSD edge search. No trading
behaviour, gate, risk limit or lock changes; `LIVE` stays locked and
`NO_VALIDATED_EDGE` stands.

### Added

- `qts.research.edgelab.intraday` — session-clock signals (fixed UTC windows,
  overnight reversal, late-New-York momentum, path-dependent opening-range
  breakout) with an explicit no-look-ahead contract.
- `qts.research.edgelab.fred_drivers` — mirror-backed `DGS10`, `DFII10` and
  `DTWEXBGS` through 2026-10, with provenance validation against an independent
  copy and `align_to_index`, which fixes the mixed-timezone forward-fill that
  could silently flatten a driver column to a constant.
- `qts.research.edgelab.hac_alpha` — Newey-West alpha and t-statistic, because the
  plain OLS error overstates significance for anything that trades often.
- `qts.research.edgelab.reporting` — one shared period-evaluation path, so the
  frozen scorecard and the holdout script cannot drift apart.
- `scripts/edgelab_intraday_run.py` — round 7 session screen with cost, gap and
  negative-control decomposition.
- `scripts/edgelab_xl001_holdout.py` — round 8 post-sample holdout, including the
  dollar-index substitution checks and the feed-completeness report.
- `qts.research.edgelab.realyield` — rolling-OLS residual of gold against the
  10-year TIPS yield, with the residual scale taken from each window's own fit.
- `scripts/edgelab_realyield_run.py` — round 9 screen; deliberately does not read
  the 2024-2026 window when nothing clears DEV.

- `qts.research.edgelab` — a vectorised, cost-charged research harness with an
  explicit execution convention, alpha-vs-beta attribution, deflated Sharpe and a
  pre-registered acceptance gate (`gate.py`).
- `scripts/edgelab_prepare_data.py`, `scripts/edgelab_screen.py`,
  `scripts/edgelab_report.py` — data build, alpha-ranked screen, and the only
  script permitted to declare an edge.
- `qts.research.edgelab.macro` — FRED `DFII10` real-yield conditioning, lagged one
  business day, with a provenance manifest and hard-failing quality checks.
- `qts.research.edgelab.power` — detection floors (`min_detectable_sr`,
  `years_needed`, `detection_summary`), so a `NO_VALIDATED_EDGE` verdict is
  reported alongside the smallest effect the sample could have detected.
- `qts.research.edgelab.forward` + `qts.research.edgelab.candidates` — the first
  gate-passing candidate (`XL-001`, easing financial conditions) with a frozen,
  hash-verified definition, an append-only forward ledger, and honest scoring. New
  CLI group `qts forward {candidates,register,log,score}` and
  `GET /api/research/edgelab-forward`. No candidate is reported validated without
  forward evidence.
- `scripts/edgelab_candidate_run.py` — reproduces the candidate across five cost
  models and three periods; machine verdict `CANDIDATE`.
- `qts.research.edgelab.longgold` + `scripts/edgelab_prepare_longgold.py` — a
  51-year daily gold store (LBMA AM fix 1969-2019) with a release-lagged real-yield
  proxy, plus 16 economically-reasoned hypotheses. Cuts the detection floor from
  Sharpe 0.59 to **0.35**.
- `qts.research.edgelab.metals` + `scripts/edgelab_gsr_run.py` — gold/silver ratio
  relative value (1968-2024) with both directions declared in advance.
- `qts.research.edgelab.macro_daily` + `scripts/edgelab_macro_daily_run.py` —
  daily DXY (1971+) and 10-year yield (1962+) drivers. Two configurations are
  positive across all four windows but each misses a different gate criterion, and
  the 2020-2024 holdout is spent, so neither is promoted.
- `docs/research/experiment_register.md` — persistent register of every tested
  hypothesis and every attempted-but-unavailable input feed.
- `docs/research/longhistory_51y_2026-10-20.md` — the 51-year study. `tsmom_1m`
  reached alpha t=2.91 over 51 years and positive in 6/6 decades, then returned
  −2.1% on the untouched holdout; roughly half its apparent edge was an artifact of
  using 10:30 London fixings rather than tradable closes.
- `qts.research.edgelab.crosssection` + `scripts/edgelab_cross_section.py` —
  replication of gold findings on an independent broker feed and across 12
  instruments. Confirms the signals are not vendor artefacts, and that
  volatility-managed exposure is *reliably* alpha-negative (2/12 instruments).
- `docs/research/xauusd_replication_and_cross_section_2026-10-20.md` — the
  replication study: `tsmom_d5` is positive on 6/12 instruments (a coin flip) and
  `volman_15_d60` earns its whole apparent alpha in 2004-2011 only.
- `docs/research/xauusd_edge_lab_verdict_2026-10-20.md` — the first gated run:
  0 of 45 D1 and 0 of 52 H1 strategies survive, across 12 families spanning
  price-derived and macro inputs. Holdout untouched.

### Changed

- Candidate evaluation logic moved out of `scripts/edgelab_candidate_run.py` into
  `qts.research.edgelab.reporting.evaluate_period`. The numbers are unchanged and
  verified identical (DEV alpha_t 2.70, TEST alpha_t 2.94), so the frozen
  scorecard and the holdout script now measure the same way by construction.
- Deflated Sharpe for the session family uses the **cumulative** trial count
  (52 prior round-1 configurations plus 9 in round 7) rather than the count of the
  current run alone.

### Fixed

- `qts.research.edgelab.fred_drivers.align_to_index` — forward-filling a
  naive-index driver frame onto a tz-aware bar index produced a **constant
  column**, and therefore a strategy that never took a position while reporting a
  flat line with no error. Timezones are now normalised and the index sorted and
  de-duplicated before filling; two tests pin the behaviour.
- The FRED loader rejected `DFII10` for containing non-positive values. Real
  yields were negative for most of 2011-2021, so the positivity check — right for
  a price level — rejected the actual history; it is now opt-in per series.
- Long-only real-yield sizing clipped only the lower bound, so a `|z| > 1` signal
  requested leverage a spot product cannot take. Both bounds are now clipped.
- `CostModel`'s docstring claimed **4.0 bps/side** while `per_side_bps()` computed
  **0.40** — a factor-of-ten gap that made every reported cost assumption 10x
  stricter than what was actually charged. The formula is authoritative; the
  docstring now states the computed value, a test pins the two together, and
  `realistic_ecn()` (0.925 bps/side) was added because 0.40 bps is optimistic for
  retail gold.
- `deflated_sharpe` returned 1.0 for every input, for two independent reasons:
  `norm.ppf(1 - 1/1)` is `-inf`, and an **annualised** Sharpe was fed to a per-bar
  formula, inflating the t-statistic by `sqrt(252) ≈ 15.9x`. Corrected, `tsmom_d5`
  scores DSR 0.741 rather than 1.000 and fails the gate on this criterion too. The
  function now takes `bars_per_year` explicitly and delegates to the tested
  `qts.validation.metrics.deflated_sharpe_ratio` instead of duplicating it.
- `realized_vol` annualised with `sqrt(bars_per_day)`, returning *daily* sigma on
  daily bars. Every volatility-scaled strategy was silently clipped to full size
  and had never actually been vol-targeted.

## [1.0.1] — 2026-10-20

Operational hardening found by auditing the 1.0.0 release. No trading behaviour,
gate, risk limit or lock changes.

### Security

- `qts serve` now refuses `--workers > 1` unless `QTS_ALLOW_MULTIWORKER=1`, and warns
  explicitly when it is enabled. The observe collector, DEMO authority and submission
  lock are process-local; a status request routed to another worker reported `STOPPED`
  while a collector was running. The previous documentation called this "supported for
  read-heavy use", which understated a misreporting hazard.

### Added

- `qts audit stats` — rows, age, byte size and per-type counts for both audit sinks,
  with the retention policy and a `--json-out` for monitoring.
- `qts audit prune` — age out high-volume market events (dry run by default, `--confirm`
  to apply, `--vacuum` to compact). Safety evidence (kill switch, risk veto, order
  intent/event, fill, reconcile, lifecycle, data-quality) is excluded in SQL at any age
  and cannot be removed by any flag. Each prune records itself with real counts.
- `qts audit prune --rotate-jsonl` — archive the live JSONL sink to a timestamped file
  instead of deleting history.
- `qts --version` (`-V`) reporting the release and the safety posture.

### Fixed

- `SqliteAuditLog` defaulted to the cwd-relative literals `data/sqlite/qts.db` and
  `logs/audit.jsonl`, so `qts audit` read a different database depending on where it was
  invoked. Both now resolve through the anchored state root; `jsonl_path=""` still
  disables the derived sink.
- `symbol_terms.json`, written by `POST /api/demo/measure-symbol-terms`, was a bare file
  at the state root that no inventory listed. It is now a declared artefact
  (`qts demo paths`).

### Legal

- Added `LICENSE` (proprietary; no trading permission granted, no warranty) and shipped
  it in the wheel via `license-files`. `pyproject.toml` already declared
  `LicenseRef-Proprietary` while no licence text shipped with the product.

## [1.0.0] — 2026-10-20

First production release: a verifiable research workstation with a hardened local
operator API, reproducible dependencies, and deployable packaging. This release
integrates the fixes recorded as ARCH-077 and ARCH-078 in
[`QTS_PROJECT_CONTROL.md`](QTS_PROJECT_CONTROL.md) and verifies them with the full
suite rather than compile checks alone.

### Security

- Mutating requests now require a trusted `Origin`/`Referer` **and** a local (or
  explicitly listed) `Host`; the literal `null` origin and implicit `*.e2b.app`
  trust were removed. Remote preview hosts are opt-in via `QTS_ALLOWED_ORIGINS`.
- Added response hardening: CSP (`default-src 'self'`, `object-src 'none'`,
  configurable `frame-ancestors`), `X-Frame-Options: DENY` by default,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, COOP/CORP,
  a permissions policy, and no `Server` banner.
- Mutating request bodies are capped (`QTS_MAX_BODY_BYTES`, default 1 MiB) and
  rejected with `413` before routing.
- `POST /api/demo/order` and `/api/demo/close` parse lots, stop-loss, take-profit
  and volume strictly: non-finite, negative, boolean or implausible values return
  `400` before any broker/session work.
- Pre-trade gate: non-finite `bid`/`ask`/`tick_age_s`/`spread` are `UNKNOWN`;
  a zero or locked spread is `FAIL` (invalid cost data is not free execution);
  `assert_demo_limits` rejects non-finite and negative inputs.
- Removed unreproducible swap figures from the broker cost file and relabelled it
  `ASSUMED`, `claim_eligible: false`, `applies_to_configured_broker: false`.
  Account identity is redacted from readiness evidence; fresh snapshots are
  git-ignored.

### Added

- `qts serve` — the supported production entry point (loopback default,
  graceful shutdown, no server banner, `QTS_ALLOW_REMOTE=1` required for a
  non-loopback bind, explicit warning when no public origin is configured).
- `GET /api/health/live` (cheap liveness, no broker/SQLite access) and
  `GET /api/version` (version, code revision, Python/platform, uptime, locked
  live state). `GET /api/health` remains the deep readiness probe.
- Deployment assets: `Dockerfile` (non-root, read-only, tini, lockfile install,
  healthcheck), `docker/entrypoint.sh`, `docker-compose.yml`,
  `packaging/qts.service` (systemd hardening), and
  `packaging/nginx-qts.conf.example` (TLS + basic auth + HSTS).
- `scripts/verify_release.sh` — one fail-fast gate (ruff, mypy, bandit, fast and
  extended pytest suites, JS syntax, `npm test`, wheel/sdist build, packaged-wheel
  import and UI-content assertion).
- `.github/workflows/release.yml` — on `v*` tags: wheel/sdist, Windows
  PyInstaller build, GHCR image, GitHub release.
- CI package and container jobs; `requirements-prod.lock` (21 packages, verified
  from a clean install).
- `docs/12-production-deployment.md`, `SECURITY.md`, `.env.example` (expanded).
- Tests: production response contract, liveness/version, body ceiling, framing
  opt-in, serve guards, NaN/Infinity and zero-spread gate behaviour, cost-label
  and identity-redaction guards.

### Changed

- Candidate evaluation logic moved out of `scripts/edgelab_candidate_run.py` into
  `qts.research.edgelab.reporting.evaluate_period`. Numbers are unchanged and
  verified identical (DEV alpha_t 2.70, TEST alpha_t 2.94).
- Deflated Sharpe for the session family now uses the **cumulative** trial count
  (52 prior round-1 configurations + 9 in round 7) instead of the current run only.


- Version is `1.0.0` in `pyproject.toml` and `qts.__version__`; the API reports
  it instead of a hardcoded string.
- Runtime dependencies gained upper bounds (`pandas<4`, `numpy<3`, `pydantic<3`,
  `fastapi<1`, …) so a new major is a compatibility event, not a surprise patch.
- `qts data bootstrap` is wired into the container entrypoint and the systemd
  `ExecStartPre`, matching the documented first-launch requirement.
- README and documentation index now describe the production path.

### Fixed

- `tests/test_cli_data_mt5_bars.py` assumed nanosecond `DatetimeIndex` resolution;
  pandas 3 defaults to microseconds. The fixture now uses `as_unit("s")`, so the
  test is resolution-independent on pandas 2 and 3.
- Two dead `Decimal` imports in the demo routes (ruff F401).
- The packaged desktop launcher ignored `--version`/`--help` and started the
  server instead, so a release smoke test would hang. It now answers both and
  exits even when a windowed build has no stdout; the Windows release job uses
  `--version`, and the bootstrap fixture is bundled into the frozen build.
- The release workflow pushed an invalid GHCR tag because `github.repository`
  preserves the uppercase repository name. The image name is lowercased now.
- In-process DEMO submissions are serialized per session (RLock). Cross-process
  exclusivity remains the journal's atomic claim; the lock removes a
  thread-safety race across the shared engine/idempotency objects that made the
  "exactly one broker order" invariant timing-dependent in CI.

### Verification

Recorded at release time in [`QTS_PROJECT_CONTROL.md`](QTS_PROJECT_CONTROL.md)
(ARCH-079):

- ruff, mypy (201 files), bandit: clean
- fast Python suite: **1,638 passed, 6 skipped, 0 failed** (1,644 collected)
- integration + research suites: **344 passed, 0 failed**
- UI suite: **48/48**
- wheel: **237 files**, including `qts/desktop/ui`, packaged fixture and configs
- clean-venv wheel install: `qts data bootstrap` (SYNTHETIC, labeled),
  `qts serve` → `/api/health/live`, `/api/version`, UI, security headers verified

The six fast-suite skips are declared, environment-dependent skips (Chromium
unavailable, long-history raw inputs not in this checkout, no events for one
impulse family); none hides a failure.

### Safety (unchanged)

`LIVE LOCKED`; `REAL_CAPITAL_EXPOSURE = 0`; `NO_VALIDATED_EDGE`; demo P&L is a
measurement, not proof of edge; no order path was loosened.

## [0.1.0] — 2026-09-16

Initial internal research build: domain model, backtest engine, validation
pipeline, DEMO lifecycle, risk engine, desktop UI, CLI, and evidence framework.
Never released as a production version.
