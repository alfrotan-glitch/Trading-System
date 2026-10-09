# 5. Research & Validation Methodology

## The Evidence Covenant

QTS enforces an unyielding research covenant: **trading execution requires proven, preregistered statistical evidence.** No strategy is deployed merely because a curve looks profitable in historical backtesting.

---

## The Research Lifecycle

$$\text{Acquire Data} \longrightarrow \text{Verify Lineage} \longrightarrow \text{Data Quality Check} \longrightarrow \text{Preregister Hypothesis} \longrightarrow \text{Evaluate Edge} \longrightarrow \text{Walk-Forward Validation} \longrightarrow \text{Register Artifact}$$

### 1. Data Integrity & Completeness
- **Zero Synthetic Smoothing:** Missing price bars or weekend rollover gaps are never cosmetically interpolated. If 6.42% of 1-minute intervals are absent from a broker export, QTS marks the dataset as incomplete.
- **Timestamp Truth:** All market events preserve broker-authoritative timestamps converted to UTC with verified server offsets.

### 2. Hypothesis Preregistration
Before any strategy code is evaluated against test data, its hypothesis must be preregistered with:
- Exact mathematical entry rules.
- Mandatory protective stop-loss formula.
- Target hold time and exit rules.
- Deterministic sizing formulas (e.g. broker minimum 0.01 lots).
- Canonical hash of all parameters (`params_hash`).

### 3. Statistical Defense Mechanisms
- **Holm-Bonferroni Correction:** Multiple testing adjustments prevent selecting random noise patterns from historical sweeps.
- **Deflated Sharpe Ratio (DSR):** Accounts for non-normal asset returns, sample length, and the total number of tested variations.
- **Walk-Forward Invariance:** Edge parameters must demonstrate stability across out-of-sample temporal partitions.

### 4. Cost Accounting — an edge is a NET claim

A backtest that reports gross P&L as "expectancy" has not measured an edge; it
has measured arithmetic. Every round turn costs money: you cross the spread, you
pay commission, you slip, and you pay financing for every night you hold.

QTS models this explicitly in `qts.research.costs`, and pairs a backtest's fills
into round turns in `qts.research.trade_ledger` (FIFO — the convention a broker
statement uses). Each fill records the reference price it was priced against, so
the **frictionless mid-to-mid P&L** and the **cost the simulation actually
charged** are reported separately rather than conflated.

The headline number is the **break-even cost multiple**: how many times costs
could rise before the strategy stops making money. `1.0x` means costs already
consume the entire edge.

Every cost component declares where it came from:

| Basis | Meaning | Can it unlock an edge gate? |
|:---|:---|:---:|
| `MEASURED` | Observed — a broker quote, a filled order, a commission schedule. | **Yes** |
| `ASSUMED` | Chosen, not observed. Valid for a sensitivity sweep. | **No** — reported, never claim-grade |
| `UNKNOWN` | Not known. | **No** — and never silently treated as zero |

Gross P&L minus a number somebody chose is arithmetic about the number somebody
chose. To make an economic-edge claim decidable, measure the costs:

```python
from qts.research.costs import CostBasis, CostModel

model = CostModel.xauusd_default(
    spread_price_units=0.30,            # quoted bid/ask width, from your broker
    commission_per_lot_usd=0.0,         # per fill
    slippage_price_units=0.10,          # per fill
    swap_per_night_per_lot_usd=-1.20,   # from the swap table; None means UNKNOWN
    basis=CostBasis.MEASURED,
    source="WM Markets XAUUSD@ — quoted 2026-10-09 09:15 UTC",
)
```

Until then the system says so: `economic edge blocked: costs were modelled but
not MEASURED — an assumed cost cannot establish an economic edge`.

### 5. Exit rules are part of the hypothesis

A trend rule with a 3.00 USD stop and the same rule without one are **two
different strategies**. Backtesting one while registering the other is how a
system lies to itself.

`BacktestEngine.run()` therefore takes declared `exit_rules`:

```python
engine.run(..., exit_rules={"stop_distance_usd": 3.00, "max_hold_bars": 16})
```

Conventions, all deliberately conservative:

| Rule | Behaviour |
|:---|:---|
| `max_hold_bars` | Fills at the bar's **open**. Considered first, so a bar that triggers both is settled by the clock. |
| `stop_distance_usd` | Fills at the stop level — **or at the open when the bar gapped through it**. A stop is an order, not a guarantee. |

Exits are priced by the matching engine, so an exit pays spread and slippage
exactly like an entry. Exits are not free.

### 6. The frozen candidate set

Not hundreds of indicator variants — three hypotheses, written down before
anything was measured (`qts/research/benchmarks.py`):

| ID | Family | Role |
|:---|:---|:---|
| `BENCH-A-TREND-EMA-12-48` | EMA 12/48 trend | **CANDIDATE** — the registered DEMO rule, unchanged |
| `BENCH-B-BREAKOUT-DONCHIAN-20` | Donchian-20 breakout | **CANDIDATE** — volatility-normalized entry |
| `BENCH-C-MEANREV-BOLLINGER-20-2.0` | Bollinger(20, 2.0) reversion | **CONTROL** — exists to be falsified |

A and B share size, stop and hold, so any difference between them is the entry
logic. C is a control that could *plausibly* pass — the only kind worth having.
If a trend rule and its opposite both survive the same gates, the gates are
measuring something other than an edge.

Each spec is hashed and verified by `verify_frozen()`: change a parameter after
registration and the run refuses. Evaluations are recorded as trials, because
running three hypotheses *is* the multiple testing DSR exists to penalise.

```
qts edge benchmark --spread 0.35 --slippage 0.12 --swap-per-night -1.20 \
    --cost-source "WM Markets XAUUSD@ quoted 2026-10-09 09:15 UTC"
```

**This command never promotes anything.** It reports gross, cost and net per
hypothesis and states whether the dataset could support a claim.

---

## Forward Validation Registry

The registry (`data/evidence/demo_forward_validation_registry_2026-09-23.json`) is the authoritative bridge between research and execution:

| Registration Status | Meaning | Order Permission |
|:---|:---|:---:|
| `ELIGIBLE` | Passed all research, statistical, and walk-forward validation gates with a proven edge. | **Yes** (in DEMO) |
| `ELIGIBLE_DIAGNOSTIC` | Preregistered execution-cost and control measurement probe (e.g. `H-EXEC-01`). No edge is claimed. | **Yes** (in DEMO) |
| `NO_TRADE` | Hypothesis inconclusive, regime-dependent, or failed validation. | **No** (Orders Refused) |
| `HALTED` / `REJECTED` | Prohibited from generating orders due to drift or invalid parameters. | **No** (Orders Refused) |

---

## Parameter Freeze & Anti-Drift Protection

At runtime, QTS recalculates the SHA-256 fingerprint of the strategy configuration:
$$\text{Fingerprint} = \text{SHA256}(\text{Canonical JSON}(\text{params}))$$

If a single parameter is altered after registration, the gate detects `PARAMETER_DRIFT` and refuses all order intents. Updating strategy parameters requires recording a new hypothesis, not editing historical artifacts.
