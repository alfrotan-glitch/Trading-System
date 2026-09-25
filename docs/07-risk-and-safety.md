# 7. Risk Controls & Fail-Closed Safety

## Core Safety Philosophy

In QTS, safety is an architectural invariant rather than an advisory banner:
- **Fail-Closed:** Every check must explicitly return `PASS`. Any exception, timeout, unhandled response, or `UNKNOWN` state results in immediate refusal of order submission.
- **Defence-in-Depth:** Safety checks exist across multiple independent layers: UI client guards, REST API middleware, Pre-Trade Gate, Risk Engine limits, and broker terminal controls.

---

## The 22 Pre-Trade Safeguard Checks

Every prospective order intent must pass all 22 pre-trade checks simultaneously:

| Check Name | Category | Failure Condition |
|:---|:---|:---|
| `mode_is_demo_execution` | Environment | Process mode is not `DEMO_EXECUTION`. |
| `authorization_valid` | Governance | Owner authorization artifact missing or tampered. |
| `execution_permission` | Authority | Authority state not enabled or readiness expired. |
| `stage_allows_order` | Stage Machine | Stage machine is not in Stage 2 or Stage 3. |
| `account_is_demo` | Broker Identity | Connected account is not a verified DEMO account. |
| `broker_identity_verified`| Identity Pin | Observed login/server does not match confirmed pin. |
| `symbol_mapping_canonical`| Instrument | Canonical symbol `XAUUSD` unmapped to broker alias. |
| `symbol_tradable` | Specification | Broker reports trading disabled on instrument. |
| `market_data_fresh` | Quotes | Tick age exceeds maximum allowable age ($>5.0\text{ s}$). |
| `spread_available` | Market Quality | Bid or ask price missing or unmeasurable. |
| `spread_within_limits` | Execution Cost | Current spread exceeds policy cap (e.g. 3.0 bps). |
| `trading_hours_allowed` | Timing | Order time falls outside allowed liquid session window. |
| `daily_loss_limit` | Risk Engine | Accumulated daily losses exceed hard ceiling ($5.00). |
| `max_drawdown` | Risk Engine | Equity drawdown exceeds maximum allowed threshold. |
| `order_size_within_limits`| Sizing | Order size exceeds broker min or policy cap (0.01 lots).|
| `stop_loss_present` | Protection | Mandatory protective stop-loss is missing or invalid. |
| `order_rate_limit` | Throttling | Order frequency exceeds maximum allowed rate. |
| `kill_switch_functional` | Emergency | Durable kill switch is active or unreadable. |
| `reconciliation_ready` | Accounting | Broker vs portfolio drift detected or suspended. |
| `broker_order_check` | Dry Run | MT5 dry-run order check returns rejection. |
| `strategy_registered` | Evidence | Strategy not registered in forward validation registry. |
| `parameters_unaltered` | Tamper Proof | Parameter SHA-256 hash does not match preregistration. |

---

## Reconciliation Engine & Drift Handling

Reconciliation runs continuously and after every order and exit event:
- **Quantity Mismatch:** Local position size differs from broker ticket volume $\rightarrow$ **Immediate Halt**.
- **Ghost Position:** Position exists in local portfolio but missing on broker $\rightarrow$ **Immediate Halt**.
- **Unknown Position:** Broker reports position not initiated by QTS $\rightarrow$ **Immediate Halt**.
- **Unattributed Deal:** Deal returned without recognized order mapping $\rightarrow$ **Immediate Halt**.

When a reconciliation suspension occurs, the stage machine transitions to `HALTED`, requiring operator investigation and explicit re-arming.
