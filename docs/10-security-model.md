# 10 — Security Model

**Classification:** Credentials, broker connectivity, account state, and capital are HIGH sensitivity.

## 10.1 Secret Isolation

- Secrets never in source, never in YAML, never in logs, never in `ValidationReport`.
- Resolution via `SecretsProvider` abstraction:
  ```python
  class SecretsProvider(Protocol):
      def get(self, key: str) -> str: ...
  # impls: EnvSecretsProvider, VaultSecretsProvider, OnePasswordProvider
  ```
- Config references `secret://mt5/password` → resolved at runtime, held in memory only, redacted in `repr`/`logs`.
- `qts config show` redacts secrets.

## 10.2 Least Privilege

- Broker credentials scoped per env: `dev/*`, `paper/*`, `live/*`. Live scope requires explicit env.
- `paper` process cannot read `live/*` secrets (provider enforces env prefix).
- File permissions: `data/sqlite/qts.db` 600, `configs/live.yaml` 600.

## 10.3 Credential Rotation & Revocation

- Credentials have `expires_at`; `qts security check` warns <7d.
- Rotation: update vault/env, restart process, old credential revoked at broker.
- Emergency revocation: `qts security revoke --scope live` → provider deletes, process fails closed on next broker call.

## 10.4 Secure Configuration

- `config.Settings` validates env separation; `dev` cannot set `mode=live` without `live` env.
- `LIVE` lifecycle requires `env=live` + `--confirm` + secret scope present; otherwise exit 2.

## 10.5 Safe Logging

- All `DomainEvent` loggers use `SafeFormatter` that redacts `password`, `token`, `secret`, `account_id` (show last 4 only).
- Audit log: account ID hashed or truncated; full ID only in encrypted column if needed (not at v1).
- No credential in exception traces.

## 10.6 Audit Logs

- Append-only `audit.jsonl` + SQLite `audit_events` (WORM if filesystem supports).
- Every security-relevant action logged: `connect`, `submit`, `kill_switch`, `promote_lifecycle`, `config_change`.
- Log includes `actor`, `timestamp`, `action`, `result`, `prev_hash` (hash chain for tamper detection at v2).

## 10.7 Environment Separation

| Env | DB | Secrets | Broker | Can Trade Live |
|-----|----|---------|--------|----------------|
| dev | `data/dev.db` | `dev/*` | Replay/Paper | No |
| paper | `data/paper.db` | `paper/*` | Paper/MT5 paper | No (paper adapter) |
| live | `data/live.db` | `live/*` | MT5 live | Yes, with gates |

Different DB files prevent paper experiments contaminating live lineage.

## 10.8 Emergency Shutdown

- `qts risk kill --env live --reason emergency` → sets kill flag, cancels orders, alerts.
- If process unreachable, broker terminal manual close + `qts reconcile` on restart.

## 10.9 Development Isolation

- CI never has live secrets; tests use `FakeBroker` + `EnvSecretsProvider` with dummy values.
- `.gitignore` denies `data/live.db`, `*.key`, `.env.live`, `audit.jsonl`.

## 10.10 Threat Model (v1)

| Threat | Mitigation |
|--------|------------|
| Credential leak via logs | Redaction, safe formatter, review |
| Accidental live trade from dev | Env isolation, fail-closed, confirm flag |
| Stolen DB with account IDs | File perms, truncation, encryption at rest (v2) |
| Replay of old order (duplicate) | Idempotency key, venue comment dedup |
| Privilege escalation (paper→live) | Provider scope, no cross-env read |

## 10.11 Checklist Before LIVE

- [ ] Secrets in vault, not env file
- [ ] `live.yaml` 600, no secrets in repo
- [ ] Audit log writable, rotation configured
- [ ] Kill-switch tested (`qts risk test-kill`)
- [ ] Reconciler healthy
- [ ] No `print` of secrets in codebase (bandit check)
