# Quarantined Evidence — NOT valid market or execution evidence

Nothing in this directory may be cited as current real-market evidence,
used to satisfy a forward-evidence gate, or displayed as DEMO execution
reality.

## demo_forward_observations.json (quarantined 2026-09-17)

Violations found during the evidence-integrity audit:

1. **Fabricated execution metrics** — every "demo_fill" record carries
   `slippage_bps: 2.5` and `latency_ms: 120` (constant synthetic values),
   and `actual_price` differs from `requested_price` by exactly +0.05 on
   every record. No real broker produced these; no order was ever sent.
2. **Fabricated broker state** — `broker_response: "FILLED"` with fills and
   P&L for orders that were never submitted (`order_send` was never called).
3. **Wrong symbol lineage** — records say `XAUUSD`; the verified broker
   symbol is `XAUUSD@`.
4. **Stale price regime** — prices cluster near 2000 (Jan-2020 fixture
   territory), inconsistent with any live session at generation time.
5. **False provenance** — records are labeled `source=REAL DEMO` despite
   being synthetic; under the provenance model they are UNVERIFIED at best.

Under the canonical provenance model these records are classified
**UNVERIFIED / FABRICATED-ORIGIN** and are excluded from every claim.

Replacement: real observations live in the canonical SQLite observation
store (`data/sqlite/forward_observatory.db`) written by the readiness-gated
OBSERVE-ONLY collector with explicit provenance, session identity, and
timestamp lineage. JSON files under `data/evidence/` are derived exports
only.

## micro.fabricated-mock-broker.json (quarantined 2026-09-22)

Committed as `data/evidence/micro.json`; moved here because it is not broker
execution evidence. Every field is traceable to the in-process `MagicMock`
that `qts run --mode micro` used to construct by default (`src/qts/cli.py`,
"Mock MT5 that simulates successful micro execution"):

| Claimed evidence field | Value | Actual origin in the mock |
| --- | --- | --- |
| `order.exchange_id` | `"123456"` | `_res.order = 123456` on a `MagicMock` `order_send` result |
| `order.state` | `"FILLED"` | synthesized fill record appended by the CLI, not a broker state transition |
| `fills[0].price` | `"2000.5"` | `_t.ask = 2000.5` on a `MagicMock` tick |
| `portfolio.equity` | `"10000"` | `_mock.account_info.return_value = MagicMock(balance=10000, equity=10000, ...)` |
| `portfolio.positions` | `1` | a position injected into the mock's `positions_get` return by the CLI |
| `reconcile.drift` | `"NONE"` | computed against that same injected mock position |
| `audit_count` | `100` | audit rows from the rehearsal run, not from a broker interaction |

Violations under the canonical provenance model:

1. **No order was ever sent to a broker.** `order_send` was called on a
   `MagicMock`; `terminal_contacted` was false. The artifact nonetheless
   recorded `state: FILLED` and an `exchange_id`, presenting a simulated
   rehearsal as broker execution reality.
2. **No provenance or lineage.** The artifact carried no `is_mock`,
   `broker_source`, `terminal_contacted`, `data_class`, `generated_at` or
   `code_version` field, so nothing in it allowed a reader or a gate to tell
   it apart from a real execution record.
3. **Fixture price regime.** `2000.5` is the synthetic fixture/mock tick
   territory, inconsistent with any real XAUUSD session.
4. **Stale location.** It sat at the primary `data/evidence/` path that
   README describes as the audit trail, alongside real derived exports.

Classification: **SYNTHETIC / MECHANISM-VALIDATION-ONLY**. It may be cited
only as evidence that the micro rehearsal code path runs end to end against a
simulated broker. It must never be cited as execution, fill, slippage,
latency, reconciliation or DEMO/LIVE reality evidence, and it satisfies no
forward-evidence, paper-evidence or promotion gate.

Replacement: `qts run --mode micro` now (a) refuses to synthesize a fill or
inject a position, (b) records `is_mock`, `terminal_contacted`,
`broker_source`, `data_class`, `data_class_reason`, `dataset_class`,
`dataset_source`, `generated_at` and `code_version` in the artifact it writes,
and (c) prints a stderr warning whenever the mock broker was used. Micro
execution evidence is only produced in the operator's own workspace, never
committed here.
