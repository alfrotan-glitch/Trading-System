# 2 — Domain Model

Ubiquitous language. All names map 1:1 to code in `src/qts/domain/`.

## 2.1 Value Objects (immutable, validated)

| Object | Fields | Invariants |
|--------|--------|------------|
| `Instrument` | `symbol: str` (e.g. `"XAUUSD"`), `venue: str` (`"MT5"`), `asset_class: AssetClass`, `tick_size`, `lot_size`, `contract_size` | `symbol` upper, venue required; tick_size > 0 |
| `Bar` | `instrument`, `open, high, low, close: Decimal`, `volume: Decimal`, `open_time, close_time: datetime UTC`, `data_version: str`, `source: str` | `high >= max(o,h,l,c)`, `low <= min(...)`, `open_time < close_time`, `close_time - open_time == timeframe`, no NaN |
| `Tick` | `instrument`, `bid, ask: Decimal`, `bid_size, ask_size`, `event_time` | `ask >= bid`, spread >= 0 |
| `Signal` | `instrument`, `side: Side`, `strength: float [-1,1]`, `event_time`, `hypothesis_id`, `features: dict` | strength clipped, hypothesis required |
| `OrderIntent` | `instrument`, `side`, `quantity`, `order_type`, `limit_price?`, `stop_price?`, `client_order_id`, `strategy_id`, `signal_id` | quantity >0, idempotent key |
| `Order` | `order_id`, `client_order_id`, `state: OrderState`, `intent`, `exchange_order_id?` | state machine valid |
| `Fill` | `fill_id`, `order_id`, `instrument`, `side`, `quantity`, `price`, `fee`, `liquidity`, `event_time` | quantity>0 |
| `Position` | `instrument`, `quantity` (signed), `avg_price`, `unrealized_pnl` | recomputed from fills |
| `Account` | `balance`, `equity`, `margin`, `leverage`, `currency` | equity = balance + floating |
| `Money` | `amount: Decimal`, `currency: str` | — |

Enums: `AssetClass {FX, METAL, EQUITY, FUTURE, CRYPTO}`, `Side {BUY,SELL}`, `OrderType {MARKET,LIMIT,STOP,STOP_LIMIT}`, `OrderState {PENDING, ACCEPTED, REJECTED, PARTIALLY_FILLED, FILLED, CANCELLED}`, `TimeInForce {GTC,IOC,FOK}`.

## 2.2 Aggregates

### Experiment (research aggregate root)
```
Hypothesis --1:N--> Experiment --1:1--> ValidationReport
              │
              └──1:N ExperimentRun (with manifest_hash, data_version, code_version, seed, params, result)
```
- Hypothesis has `statement`, `rationale`, `falsifiability_criteria`.
- Experiment is reproducible iff `manifest_hash` resolves.

### Strategy (alpha aggregate)
```
StrategyDef (code_version, params) --1:N--> StrategyInstance (lifecycle_state)
```
- Strategy is pure: `on_bar(bar) -> list[Signal]`; no direct I/O.
- PortfolioConstruction: `signals -> targets`; ExecutionModel: `targets -> OrderIntents`.

### Order Aggregate
```
OrderIntent --1:1--> Order --1:N--> Fill --1:1--> Position delta
```
- All state transitions emit domain events.

## 2.3 Entities & Identity

- Identity via `UUID7` (time-ordered) for events; `client_order_id = f"{strategy_id}:{uuid7}"` for idempotency.
- `Instrument` identity is `(symbol, venue)`.

## 2.4 Domain Services (stateless)

- `MatchingEngine`: `match(order, book) -> fills` with spread/slippage/latency models.
- `PnlCalculator`, `DrawdownCalculator`, `RiskCalculator`.
- `DataNormalizer`: timezone, session, corporate actions (no-op for XAUUSD but interface present).

## 2.5 Invariants Enforced in Domain

- No order without `client_order_id`.
- No fill without order in ACCEPTED/PARTIALLY_FILLED.
- No position without fills.
- No strategy promotion without `ValidationReport` + `RiskLimits`.
- All timestamps UTC, tz-aware; naive datetime rejected.
- Decimals for prices/quantities (no float leakage into execution/money).

## 2.6 Anti-Corruption

- Broker DTOs → domain via adapter mappers; broker strings never leak inward.
- Research pandas DataFrames → domain Bars via `DataFrame ↔ List[Bar]` mappers with schema validation.

## 2.7 Example Flow (type signatures)

```python
def on_bar(bar: Bar) -> list[Signal]: ...
def construct(signals: list[Signal], portfolio: Portfolio) -> list[Target]: ...
def execute(targets: list[Target], market: MarketSnapshot) -> list[OrderIntent]: ...
def pre_trade(intent: OrderIntent, account: Account, positions: dict, limits: RiskLimits) -> RiskDecision: ...
def send(intent: OrderIntent) -> Order: ...  # via BrokerAdapter
```
