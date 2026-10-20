# 12. Production Deployment

> **Scope.** This guide makes the QTS **research workstation + DEMO observatory**
> production-grade to operate: reproducible installs, a hardened local API, health
> probes, backups, upgrades and rollback. It adds **no** live-trading permission.
> `LIVE` remains structurally locked, `REAL_CAPITAL_EXPOSURE` stays `0`, and
> `NO_VALIDATED_EDGE` is unchanged. A demo order is a measurement, not proof of edge.

Read [`QTS_PROJECT_CONTROL.md`](../QTS_PROJECT_CONTROL.md) first. This guide is
operational; it does not authorize a trade.

---

## 1. What ships

| Artifact | Built by | Use |
|---|---|---|
| `qts-1.0.1-py3-none-any.whl` | `python -m build` | Installed product (API, CLI, desktop UI) |
| `qts-1.0.1.tar.gz` | `python -m build` | Source distribution / audit |
| `qts:1.0.1` image | `docker build .` | Containerised workstation |
| `QTS-v1.0.1-windows.zip` | `pyinstaller packaging/qts.spec` | One-click Windows desktop |
| `requirements-prod.lock` | clean `pip freeze` | Exact runtime dependency matrix |

The UI is inside the wheel (`qts/desktop/ui`), together with the SYNTHETIC
bootstrap fixture, the declarable environment YAMLs and `LICENSE`
(`.dist-info/licenses/LICENSE`). If they are missing, the
build is broken — `scripts/verify_release.sh` refuses to pass.

### Release gate (must pass before a tag)

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -e ".[dev,packaging]"
npm ci
scripts/verify_release.sh
```

The gate runs ruff, mypy, bandit, the fast Python suite, the integration and
research suites, JS syntax checks, `npm test`, builds the wheel and sdist, then
imports the **packaged** wheel from a scratch directory and asserts the UI and
version are present. CI runs the same checks (`.github/workflows/ci.yml`); tagging
`v*` runs `.github/workflows/release.yml` and publishes the artifacts.

---

## 2. Supported matrix

| Surface | Supported |
|---|---|
| Python | 3.11, 3.12, 3.13, 3.14 |
| MT5 broker IPC | Windows only (MetaTrader 5 terminal + `MetaTrader5` package) |
| Research, API, desktop UI | Windows, Linux, macOS |
| Containers | Linux, `python:3.12-slim` base, non-root uid 10001 |
| Database | SQLite (single writer) — one QTS process per state root |
| Operator model | One operator, one workstation, one state root |

QTS is not a multi-tenant service. Do not point two API processes at one state
root: the DEMO journal, stage machine and risk engine assume a single writer.

---

## 3. Configuration

All configuration is environment-based; nothing secret belongs in the repository.
Copy [`.env.example`](../.env.example) and keep the copy out of Git.

| Variable | Default | Meaning |
|---|---|---|
| `QTS_ENV` | `development` | Named environment; selects `configs/<env>.yaml` |
| `QTS_MT5_MODE` | `MOCK` | `REAL` probes a terminal; a non-DEMO account still fails closed |
| `QTS_STATE_ROOT` | repo root / `~/.qts` | Absolute root for journals, DBs, identity pin |
| `QTS_DATA_ROOT` | `<QTS_STATE_ROOT>/data` | Curated dataset store (parquet + manifest SQLite) |
| `QTS_API_HOST` / `QTS_API_PORT` | `127.0.0.1` / `8000` | Bind address for `qts serve` / desktop |
| `QTS_ALLOW_REMOTE` | unset | `1` is required to bind a non-loopback address |
| `QTS_ALLOWED_ORIGINS` | empty | Comma-separated exact public origins/hosts allowed to mutate |
| `QTS_FRAME_ANCESTORS` | `'none'` | CSP framing policy; opt in only for a known embedder |
| `QTS_MAX_BODY_BYTES` | `1048576` | Mutating request body ceiling |
| `QTS_LOG_LEVEL` | `info` | `critical`…`trace` |

Resolve the effective paths at any time:

```bash
qts demo paths      # every artefact, its existence and why it resolved there
qts mode show       # effective mode and the source that decided it
```

**Never** rely on the process working directory. State paths are anchored to
`QTS_STATE_ROOT` (or the detected installation root), not to `$PWD`.

---

## 4. Deployment options

### 4.1 Windows desktop (broker-facing)

```bat
scripts\setup_windows.bat
scripts\run_qts.bat
```

The launcher runs startup health, starts the API on `127.0.0.1:8000`, and opens
the workstation. MT5 connectivity, the DEMO identity pin and the readiness gate
remain mandatory for any demo order. A packaged `QTS.exe` follows the same path
and additionally requires Windows SmartScreen approval on first run.

### 4.2 Linux/macOS workstation (research + UI)

```bash
python -m venv /opt/qts/.venv
/opt/qts/.venv/bin/pip install --no-index --find-links /srv/wheels qts==1.0.1
QTS_STATE_ROOT=/var/lib/qts /opt/qts/.venv/bin/qts data bootstrap
QTS_STATE_ROOT=/var/lib/qts /opt/qts/.venv/bin/qts serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. There is no port 8901 and no
`python -m qts.api.server` launch path.

### 4.3 systemd

`packaging/qts.service` is a hardened unit: dedicated user, `ProtectSystem=strict`,
`NoNewPrivileges`, `PrivateTmp`, no capabilities, and write access only to
`/var/lib/qts`. Installation steps are in the unit header. Runtime settings live
in `/etc/qts/qts.env` (mode `0600`).

```bash
sudo systemctl enable --now qts
systemctl status qts
journalctl -u qts -f
```

### 4.4 Container

```bash
docker compose up -d --build
docker compose logs -f qts
```

Defaults: the API is published on `127.0.0.1:8000` only, the root filesystem is
read-only, `/tmp` is a tmpfs, all capabilities are dropped, and the named volume
`qts-state` holds `/data`. The entrypoint seeds committed evidence on first boot
and runs `qts data bootstrap` before starting the server. Set
`QTS_SKIP_BOOTSTRAP=1` only if you manage data versions yourself.

### 4.5 Behind a TLS proxy

QTS has no user accounts. To reach it from another machine, put an
authenticated, TLS-terminating proxy in front — `packaging/nginx-qts.conf.example`
is a working starting point (HTTP basic auth, HSTS, 1 MiB body limit, loopback
health exception). Then set:

```ini
QTS_ALLOW_REMOTE=1
QTS_ALLOWED_ORIGINS=https://qts.example.com
```

`--proxy-headers` is only correct behind that proxy. Because the API rejects
mutations whose `Host` header is not a known operator address, the public
hostname must be listed in `QTS_ALLOWED_ORIGINS`; forwarding `Host $host` is
required.

---

## 5. Security posture

| Control | Behaviour |
|---|---|
| Bind address | Loopback by default; non-loopback refuses without `QTS_ALLOW_REMOTE=1` |
| Origin boundary | Mutations require a trusted `Origin`/`Referer`; `null` and unknown remote hosts are rejected |
| DNS rebinding | Mutations require a local or explicitly listed `Host` |
| Framing | `frame-ancestors 'none'` + `X-Frame-Options: DENY` by default |
| CSP | `default-src 'self'`, no third-party script/connect, `object-src 'none'` |
| MIME sniffing | `X-Content-Type-Options: nosniff` |
| Referrer leakage | `Referrer-Policy: no-referrer` |
| Request size | 1 MiB ceiling on mutations → `413 REQUEST_BODY_TOO_LARGE` |
| Numeric input | Non-finite/negative/implausible ticket numbers → `400` before any gate |
| Non-finite quotes | NaN/Infinity quote or age is `UNKNOWN`, zero/locked spread is `FAIL` |
| Server banner | `Server` header disabled |
| Secrets | None stored by QTS; broker credentials live in the MT5 terminal |
| Credentials in evidence | Account login/name is redacted; readiness snapshots are git-ignored |

The API is unauthenticated **by design** because it is a single-operator local
surface. Authentication belongs at the proxy. Do not port-forward it.

---

## 6. Health, monitoring and logs

| Endpoint | Purpose | Touches broker/SQLite |
|---|---|---|
| `GET /api/health/live` | Liveness; container/systemd probe | No |
| `GET /api/health` | Deep, honest readiness (kill switch, data, MT5, reconciliation) | Yes |
| `GET /api/version` | Version, code revision, Python/platform, uptime | No |

```bash
curl -fsS http://127.0.0.1:8000/api/health/live
curl -fsS http://127.0.0.1:8000/api/version
curl -s  http://127.0.0.1:8000/api/health | python -m json.tool
```

Alerting guidance:

- **Restart** on failed liveness (process is gone), not on deep-health failures.
- **Page** on `system_status` = `Suspended` (kill switch active) or `Blocked`
  (no verified data version) — but do not auto-clear either. Clearing is an
  operator decision with a recorded reason.
- Treat repeated `FORBIDDEN_MUTATION`, `REQUEST_BODY_TOO_LARGE` or DNS-rebinding
  rejections as a security signal.
- The durable audit log is `logs/audit.jsonl`; the DEMO order journal is the
  SQLite database. Both are evidence — back them up, do not edit them.

---

## 7. State, backup and restore

`qts demo paths` prints the authoritative list. The critical set is:

- `data/sqlite/qts.db` — DEMO journal, stage machine, risk/kill-switch state
- `data/sqlite/forward_observatory.db` — observation history
- `data/evidence/demo_broker_identity_pin.json` — account identity pin
- `data/evidence/demo_execution_authorization_*.json` — owner authorization
- `data/evidence/demo_forward_validation_registry_*.json` — frozen strategies
- `logs/audit.jsonl` — append-only domain-event audit
- `data/setup/mt5_setup.json` — machine-local terminal path and symbol map

Backup (consistent SQLite copy, no downtime required):

```bash
systemctl stop qts
sqlite3 /var/lib/qts/data/sqlite/qts.db ".backup '/backup/qts-$(date +%F).db'"
systemctl start qts
tar -C /var/lib/qts -czf /backup/qts-state-$(date +%F).tar.gz data/evidence logs
```

Restore: stop the service, replace the files under the same `QTS_STATE_ROOT`,
start the service, then verify `qts demo verify` and `GET /api/health`. An old
database restored under a new binary is supported (schema migrations are
additive); a *newer* database under an *older* binary is not — roll back the
binary only with its matching backup.

---

## 7b. Audit retention

The audit log is evidence and it grows. Two sinks exist: the authoritative SQLite
table `audit_events` in `data/sqlite/qts.db`, and the derived JSONL mirror
`logs/audit.jsonl` (append-only, shipped by `qts audit ship`).

Measure first — the report includes size, age and the retention policy:

```bash
qts audit stats                       # rows, age, bytes, policy
qts audit stats --json-out audit.json # machine-readable for monitoring
```

Bound the database (dry run by default; nothing is deleted without `--confirm`):

```bash
qts audit prune --older-than-days 90              # preview
qts audit prune --older-than-days 90 --confirm --vacuum
```

**Safety evidence is never pruned.** Only high-volume market observations
(`BarReceived`, `TickReceived`, `SignalGenerated`, `NoTrade`, `PositionUpdate`,
`AccountUpdate`) can be removed. Kill switches, risk vetoes, order intents, order
events, fills, reconciliations, lifecycle transitions and data-quality alerts are
excluded in SQL at any age; there is no flag that removes them. Every prune writes
its own `LifecycleTransition` record with the real counts, so a deletion leaves a
trace.

Bound the JSONL mirror without destroying history — rotation moves the live file to
a timestamped archive:

```bash
qts audit prune --older-than-days 90 --rotate-jsonl --archive-dir /var/lib/qts/archive
```

Suggested routine: `qts audit stats` weekly, prune market observations at 30–90
days, archive/ship the JSONL monthly, and alert when `db_bytes` exceeds a threshold
you chose. The audit tables are intentionally append-only; pruning is an explicit
operator action, not an automatic background job.

---

## 8. Upgrade and rollback

1. Run the release gate on the candidate (`scripts/verify_release.sh`).
2. Back up as above; record the current `/api/version`.
3. Drain: stop the service (SIGTERM is graceful, 10 s).
4. Install the new wheel / image / EXE.
5. `qts data bootstrap` (idempotent; reuses a usable version).
6. Start, then verify `/api/health/live`, `/api/version`, `/api/health`, and
   `qts demo status`.
7. Keep the previous wheel and state backup for one release cycle.

Rollback is: stop, reinstall the previous wheel, restore the matching state
backup only if the schema advanced, start, verify. LIVE remains locked across
both directions.

---

## 9. Incident response

| Situation | Action |
|---|---|
| Unexpected order activity | `qts risk kill` (durable), stop the service, preserve journal + audit log |
| Suspected unauthorized access | Stop the service, rotate proxy credentials, review rejected-origin logs, move the state root |
| Data integrity doubt | Stop; do not delete evidence; run `qts health`, `qts demo verify`, `qts audit` |
| Broker terminal compromised | Disconnect the terminal, revoke DEMO authorization (`qts demo revoke`), rotate the account password at the broker |
| Container compromise | `docker compose down`, preserve the volume snapshot, rebuild from a verified image |

`qts demo revoke` withdraws DEMO execution permission. It never unlocks live
trading, and no command in this repository can.

---

## 10. Operational limits

- One writer per state root; SQLite is not a cluster database.
- One MT5 terminal per Windows host; the adapter talks to the logged-in terminal.
- **One worker.** `qts serve` refuses `--workers > 1` unless `QTS_ALLOW_MULTIWORKER=1`
  is set, because the observe collector, the DEMO authority and the submission lock
  are process-local: a `POST /api/observe/start` handled by worker A is invisible to a
  `GET /api/observe/status` handled by worker B, which honestly reports `STOPPED`
  while a collector runs. That is a misreporting hazard, not a tuning choice. Scale
  read-only traffic at the proxy; never enable it on a host that observes or submits
  DEMO orders.
- The local API is not rate-limited; put limits at the proxy if exposed.
- The DEMO readiness gate, pre-trade gate and reconciliation remain fail-closed
  regardless of deployment choice.

---

## 11. Release checklist

- [ ] `scripts/verify_release.sh` passed (or the skipped extended suite is recorded)
- [ ] `CHANGELOG.md` updated; version bumped in `pyproject.toml` and `qts.__version__`
- [ ] `requirements-prod.lock` regenerated only with a green gate
- [ ] Wheel contains `qts/desktop/ui`
- [ ] Docker image builds and its healthcheck passes
- [ ] Docs updated (`README.md`, this guide, `QTS_PROJECT_CONTROL.md`)
- [ ] Safety statement unchanged: `LIVE LOCKED`, `REAL_CAPITAL_EXPOSURE = 0`,
      `NO_VALIDATED_EDGE`
- [ ] Tag `vX.Y.Z`; the release workflow publishes artifacts
