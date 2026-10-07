# 3 — Component Boundaries & Interfaces

## 3.1 Module Map

```
src/qts/
  domain/         # pure, zero deps — value objects, enums, invariants
  data/           # DataStore, DataFeed, DataVersion, Quality, Normalization
  execution/      # ExecutionEngine, OrderManager, MatchingEngine, Reconciler
  adapters/       # BrokerAdapter implementations: MT5, Paper, Replay, Null
  risk/           # RiskEngine, limits, kill-switch
  portfolio/      # Portfolio, PositionSizer, Target
  regime/         # RegimeDetector interface + detectors
  research/       # Hypothesis, FeatureStore, Experiment, ExperimentStore, StrategyFactory
  validation/     # Validator pipeline, WalkForward, Adversarial, Stress, metrics
  observability/  # AuditLog, Metrics, Health, Alerting
  security/       # SecretsProvider, Config, redaction
  lifecycle/      # State machine, gates
  config/         # Settings (Pydantic), env separation
```

## 3.2 Dependency Rule

- `domain` imports nothing from `qts`.
- All other modules may import `domain` and `config` (read-only).
- `research` may import `data`, `validation`.
- `execution` may import `data`, `risk`, `observability`.
- `adapters` implements interfaces defined in `execution`.
- Enforced by `import-linter` / `ruff` import rules in CI.

## 3.3 Key Interfaces (Python Protocol / ABC)

```python
class DataFeed(Protocol):
    def subscribe(self, instrument: Instrument, timeframe: str, handler: Callable[[Bar], None]): ...
    def bars(self, instrument, timeframe, start, end, version: str|None) -> list[Bar]: ...

class DataStore(Protocol):
    def write_bars(self, bars: list[Bar], version: str) -> Manifest: ...
    def read_bars(self, instrument, timeframe, start, end, version) -> list[Bar]: ...
    def manifest(self, version) -> Manifest: ...

class BrokerAdapter(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def submit(self, intent: OrderIntent) -> Order: ...  # lots×contract enforced in MT5Adapter.lots_to_mt5_volume
    def cancel(self, order_id: str) -> None: ...
    def positions(self) -> list[Position]: ...  # quantity in lots
    def account(self) -> Account: ...
    def orders(self) -> list[Order]: ...
    def ticks(self, instrument: Instrument) -> Tick: ...

class ExecutionEngine(Protocol):
    def submit_intent(self, intent: OrderIntent, bar: Bar|None) -> tuple[Order|None, list[Fill]]: ...  # risk gate + NO_TRADE, next-bar exec via exec_bar
    def on_tick(self, tick: Tick): ...
    def on_bar(self, bar: Bar): ...
    def reconcile(self) -> ReconcileReport: ...  # requires_suspend → NO_TRADE gate

class RiskEngine(Protocol):
    def pre_trade(self, intent: OrderIntent, ctx: RiskContext) -> RiskDecision: ...  # lots×contract×price, step/min lots, veto/allow/resize
    def post_trade(self, fill: Fill, ctx: RiskContext) -> None: ...  # triggers kill on daily/dd
    def check_portfolio(self, ctx: RiskContext) -> list[RiskVeto]: ...
    def kill_switch(self, reason: str) -> None: ...  # SQLite risk_state persists survives restart

class RegimeDetector(Protocol):
    def label(self, bars: list[Bar]) -> RegimeLabel: ...  # e.g. TREND, RANGE, HIGH_VOL
    def confidence(self) -> float: ...

class Validator(Protocol):
    def validate(self, experiment: Experiment, data: DataSlice) -> ValidationReport: ...

class ExperimentStore(Protocol):
    def put(self, exp: Experiment) -> None: ...
    def get(self, exp_id: str) -> Experiment: ...
    def lineage(self, exp_id: str) -> LineageGraph: ...

class AuditLog(Protocol):
    def emit(self, event: DomainEvent) -> None: ...  # redacts password/secret/token
    def query(self, **filters) -> list[DomainEvent]: ...

class Shipper(Protocol):
    def ship(self, local_path: Path, key: str|None) -> str|None: ...  # LocalShipper / S3Shipper(content-hash, prefix)

class ResearchLoop(Protocol):
    def propose(self, n:int) -> list[str]: ...
    def run_experiment(self, hypothesis_id:str, strategy_id:str, params:dict, data_version:str) -> LoopResult: ...
```

## 3.4 Plug Points

| Plug | Interface | Current Impl | Future |
|------|-----------|--------------|--------|
| Instrument | `Instrument` | XAUUSD (MT5) | Any symbol, any venue |
| Data source | `DataFeed` + `DataStore` | Parquet+SQLite, MT5 history | CCXT, IB, Ducascopy, Polygon |
| Broker | `BrokerAdapter` | Paper, Replay, MT5 | IB, OANDA, cTrader |
| Execution matching | `MatchingEngine` | Spread+slippage+latency | Full L2 simulator |
| Strategy | `Strategy` callback | SMA breakout example | Any alpha |
| Risk limits | `RiskLimits` (config) | Per-trade, daily, drawdown | Correlated exposure, vol-target |
| Regime | `RegimeDetector` | HMM / vol quantile (hypothesis) | ML ensemble |
| Validation | `Validator` pipeline | Walk-forward + stress | CPCV, Bayesian |

## 3.5 Isolation Guarantees

- MT5 code lives only in `adapters/mt5_adapter.py`; core never imports `MetaTrader5`.
- Risk never imports Execution; Execution calls Risk via interface — circular deps prevented.
- Research DataFrames never cross into Execution without `Bar` conversion + validation.

## 3.6 Testing Seams

Every interface has a `Fake`/`InMemory` implementation for unit tests:
`FakeBroker`, `InMemoryDataStore`, `FakeRiskEngine`, `DeterministicMatchingEngine`.

## 3.7 Configuration Boundary

`config.Settings` is the only place reading env/YAML. Other modules receive plain dataclasses (`RiskLimits`, `ExecutionConfig`). No `os.getenv` elsewhere.
