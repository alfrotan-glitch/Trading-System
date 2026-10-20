# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| < 1.0 | No — upgrade |

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** on this repository
(Security → Advisories → Report a vulnerability). Do not open a public issue for
an unfixed vulnerability, and do not include broker credentials, account
identifiers or state databases in a report.

Include: version (`GET /api/version`), platform, reproduction steps, and the
security impact you believe exists. We aim to acknowledge within 5 business days.

## Product security model

QTS is a **single-operator, local-first** gold research workstation.

- The HTTP API binds `127.0.0.1` by default. A non-loopback bind requires an
  explicit `QTS_ALLOW_REMOTE=1` and is expected to sit behind an authenticated,
  TLS-terminating proxy (`packaging/nginx-qts.conf.example`).
- There are no user accounts and no remote authentication inside QTS. The proxy
  is the authentication boundary.
- Mutating requests require a trusted `Origin`/`Referer` and a local (or
  explicitly listed) `Host` header. The literal `null` origin is never trusted.
- Responses carry a restrictive Content-Security-Policy, `X-Frame-Options: DENY`
  (unless framing is explicitly allowed), `nosniff`, `no-referrer`, COOP/CORP and
  a permissions policy. The `Server` banner is suppressed.
- Mutating bodies are capped at 1 MiB; numeric operator input is parsed strictly
  (finite, positive, plausible) before any session or broker work.
- The pre-trade gate treats non-finite quotes, ages and spreads as `UNKNOWN` and
  a zero/locked spread as `FAIL`. Unknown never passes.
- `LIVE` trading is structurally locked. No configuration, API payload, demo
  result or environment variable can unlock it in this repository.
- Broker credentials are held by the MT5 terminal, not by QTS. QTS stores no
  passwords or API keys.
- Committed evidence must not contain broker account identity. Readiness
  snapshots are git-ignored; the product redacts login/name on export.

## Hardening checklist for operators

- Keep the default loopback bind; expose it only through an authenticating proxy.
- Use a dedicated OS user and the supplied systemd hardening (or the container's
  non-root, read-only profile).
- `chmod 600` the environment file; never commit `.env`.
- Restrict the state root (`QTS_STATE_ROOT`) to that user; it contains journals,
  the identity pin and the authorization record.
- Back up before upgrades; verify `/api/version` and `/api/health` after.
- Treat the audit log and order journal as evidence: append-only, backed up, not
  hand-edited.
- Rotate proxy credentials on staff change or suspected exposure.

## Out of scope

- Bugs requiring the attacker to already control the operator's OS account.
- A deliberately misconfigured deployment that exposes the loopback API directly
  to the internet without authentication.
- Market losses. QTS makes no profitability claim; there is no validated edge.
