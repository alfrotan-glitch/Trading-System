# Changelog

All notable changes to QTS are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use semantic
versioning. **No release changes the safety posture:** `LIVE` is locked,
`REAL_CAPITAL_EXPOSURE` is `0`, and `NO_VALIDATED_EDGE` stands unless a future
release says otherwise with evidence.

## [Unreleased]

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
