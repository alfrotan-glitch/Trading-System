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
