# 7. Risk Controls & Fail-Closed Safety

## Core Safety Philosophy

In QTS, safety is an architectural invariant rather than an advisory banner:
- **Fail-Closed:** Every check must explicitly return `PASS`. Any exception, timeout, unhandled response, or `UNKNOWN` state results in immediate refusal of order submission.
- **Defence-in-Depth:** Safety checks exist across multiple independent layers: UI client guards, REST API middleware, Pre-Trade Gate, Risk Engine limits, and broker terminal controls.

---

## Pre-trade gate

The only order gate is `run_pretrade_gate` in `qts.execution.demo_pretrade`. An order is refused unless every check that runs resolves to `PASS`. `UNKNOWN` does not pass. The canonical names live in that module, not in a second list here.

The gate covers, at minimum: demo account proof, pinned broker identity, canonical symbol mapping, quote freshness, spread, size and stop limits, daily loss and drawdown, duplicate-order protection, the kill switch, reconciliation, a broker dry-run, and the registered policy. A registered policy can only tighten those limits. It cannot loosen them, and it is not a validated edge.

---

## Reconciliation Engine & Drift Handling

Reconciliation runs continuously and after every order and exit event:
- **Quantity Mismatch:** Local position size differs from broker ticket volume $\rightarrow$ **Immediate Halt**.
- **Ghost Position:** Position exists in local portfolio but missing on broker $\rightarrow$ **Immediate Halt**.
- **Unknown Position:** Broker reports position not initiated by QTS $\rightarrow$ **Immediate Halt**.
- **Unattributed Deal:** Deal returned without recognized order mapping $\rightarrow$ **Immediate Halt**.

When a reconciliation suspension occurs, the stage machine transitions to `HALTED`, requiring operator investigation and explicit re-arming.
