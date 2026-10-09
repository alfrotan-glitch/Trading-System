# Edge & Risk Closure — 2026-10-09

**Branch:** `arena/db6f7053-trading-system`  
**Phase 2 (frozen candidate set + backtest exit rules): §6b**
**Predecessor:** [`deep_repository_and_edge_audit_2026-10-09.md`](deep_repository_and_edge_audit_2026-10-09.md)

This document records what was changed to close the findings of the
2026-10-09 deep audit, what was deliberately *not* changed, and what is
still open. It is an engineering record, not a claim that a trading edge
exists.

**`NO_VALIDATED_EDGE` is unchanged. LIVE remains locked. `REAL_CAPITAL_EXPOSURE` remains 0.**

---

## 1. P0 — DEMO authorization artifact incompatible with its validator

**Audit finding.** `data/evidence/demo_execution_authorization_2026-09-23.json`
declares `risk_ceiling.max_drawdown_pct: 5`. `_RISK_CEILING_FIELDS` did not
contain that key, and `_validate_risk_ceiling()` fails closed on unknown keys.
The checked-in authorization therefore could not validate, and DEMO execution
stayed disabled by policy.

**Audit's required resolution.** *"Either implement percentage drawdown
end-to-end in canonical risk authority/engine/context and test it … or obtain
an explicit owner decision to withdraw that percentage limit."*

**What was done — the first option, in full.**

The authorization artifact was **not edited** and its `integrity.content_sha256`
was **not recomputed**. The limit was implemented instead, so the artifact now
validates exactly as the owner signed it.

| Layer | Change |
|:---|:---|
| `risk/authority.py` | `CanonicalRiskLimits.max_drawdown_pct` (base **10%**). Validated to be a real percentage (`0 < pct <= 100`) — `0` is a unit mistake, not a limit. Added to `_CAP_FIELDS`. Schema `version` 2 → 3. |
| `risk/authority.py` | New `apply_risk_ceiling()` — tightens a resolved snapshot and records per-field provenance. Widening is refused and *reported*; a non-numeric or out-of-range ceiling is ignored with a warning. |
| `risk/engine.py` | `RiskLimits.max_drawdown_pct`, two new veto reasons (`DRAWDOWN_PCT_BREACH`, `DRAWDOWN_PCT_UNMEASURABLE`), enforcement in `pre_trade`, `post_trade` (kill switch) and `check_portfolio`. |
| `risk/engine.py` | `RiskContext.peak_equity` / `drawdown_pct` and `measured_drawdown_pct()`. A zero dollar drawdown is 0% at *any* positive peak (arithmetic). A non-zero drawdown with no known peak is **UNKNOWN**, and UNKNOWN blocks. |
| `execution/engine.py` | Tracks `drawdown_pct` next to the durable peak it was derived from and passes both into `RiskContext`. |
| `execution/demo_session.py` | **The owner's `risk_ceiling` is now APPLIED, not merely validated.** `apply_risk_ceiling()` sits between the resolved snapshot and the engine's limits. |
| `risk/demo_limits.py` | `max_drawdown_pct` was hard-coded to `None`. It is now resolved from the canonical authority. |
| `api/routes/risk.py`, `config/settings.py` | The percentage cap is exposed and operator-overridable (tightening only). |

**Verification.**

```
>>> authorization_status()
exists=True valid=True reasons=[]
>>> resolve_demo_execution_policy(mode="demo_execution")
ENABLED_AUTHORIZED  authorization_id=DEMO-AUTH-2026-09-23-01
```

The resolved DEMO ceiling is 10% (canonical base) tightened by the artifact to
**5%** — the number the owner wrote — and that 5% is what the risk engine
enforces, with `sources["max_drawdown_pct"] == "owner_authorization"`.

**Why the base is 10% and not 5%.** Setting the canonical DEMO value to 5%
would have made the artifact validate by construction, which is circular. The
system's percentage cap is 10%; the owner's artifact tightens it to 5%; both
facts are visible and separately auditable.

---

## 2. P0 — No validated trading edge, and the cost gate could not decide one

**Audit finding.** `edge_validation.json` recorded
`cost: "gross/net cost decomposition NOT_IMPLEMENTED — blocks"` and
`expectancy: "net_exp 0.0000 pf 0.00"`.

**Root cause found.** Two separate defects, both now fixed:

1. `validate_edge_survival` called `compute_expectancy(trades_pnl, costs_per_trade=0.0)`.
   *Net* expectancy was gross expectancy wearing a costume.
2. The orchestrator passed `trades_pnl=[]` with the comment
   *"BacktestResult exposes fills, not realized trade PnL attribution"*. There
   was no code that paired an entry fill with its exit fill.

### 2a. New `qts/research/costs.py` — an explicit cost model

* `CostComponent` carries its own provenance: `MEASURED`, `ASSUMED` or
  `UNKNOWN`. A zero-magnitude component with a confident basis raises — a
  silently free cost is a bug, not a free lunch.
* `CostModel` is per-instrument, per-round-turn: spread (1 crossing),
  commission and slippage (2 fills), financing (per lot per night).
* `decompose_costs()` returns gross, cost, net, cost drag, **break-even cost
  multiple**, gross/net equity curves and per-component totals.
* **Claim eligibility requires MEASURED costs.** See §3.

### 2b. New `qts/research/trade_ledger.py` — fills → round turns

* FIFO pairing. Lots are *appended*, never averaged: merging two entry prices
  would make the P&L of a partial close depend on lots that are still open.
* A direction flip closes and opens the remainder.
* An unclosed position is reported as an open lot, never as a zero-P&L trade.
* Each fill's recorded reference price (`bar_open`, now joined by `fee` in the
  backtest fill record) separates the **frictionless mid-to-mid P&L** from the
  **cost the simulation actually charged**. A backtest can now say "you assumed
  5 USD per round turn; the simulation charged 7.20 USD".
* Unparseable fills are counted, not dropped.

### 2c. Three distinct gate outcomes, never conflated

| Situation | Report | Gate |
|:---|:---|:---|
| No cost model | `GROSS exp … — net expectancy was NOT measured (blocks)` | FAIL |
| Costs modelled but **ASSUMED** | net reported + `[costs ASSUMED: … — not claim-grade]` | FAIL |
| Costs **MEASURED** | net reported | may PASS |

`edge/orchestrator.py` no longer hard-codes
`expectancy: UNAVAILABLE` / `economic_edge: UNAVAILABLE`; both now report what
was measured, or why nothing was.

### 2d. End-to-end result on the canonical bootstrap dataset

```
cost gate      : False | only 1 completed round turn(s) — a gross vs net equity
                        comparison needs at least 2; the decomposition is
                        reported but this gate cannot pass
expectancy gate: False | net_exp 776.3000 (gross 781.3000 - cost 5.0000/trade)
                        pf inf [costs ASSUMED: commission, slippage, spread —
                        not claim-grade]
economic gate  : False | economic edge blocked: costs were modelled but not
                        MEASURED — an assumed cost cannot establish an
                        economic edge
conclusion     : BLOCKED_INSUFFICIENT_DATA
```

The synthetic bootstrap fixture produces a single round turn with +781 USD of
frictionless P&L. That number is real arithmetic on a random walk and it is
worth exactly nothing as evidence — which is precisely why it cannot pass any
gate. The `cost` gate message was also corrected: "one round turn" is
*insufficient evidence*, not `NOT_IMPLEMENTED`, and the two now read
differently.

---

## 3. A regression this work caught in its own tests

`tests/adversarial/test_edge_capital.py::test_final_gate_keeps_no_trade_when_blocked`
began failing: with a default **ASSUMED** cost model, `economic_edge` started
returning `True` on the synthetic fixture.

The first version of the cost model treated `ASSUMED` as claim-eligible. That
is wrong. Gross P&L minus a number somebody chose is arithmetic about the
number somebody chose. `CLAIM_ELIGIBLE_BASES` is now `{MEASURED}` only: an
assumed cost produces a valid **sensitivity** result and a legible
`NOT_CLAIM_GRADE` record, and it can never unlock an edge gate.

A second defect surfaced in the same area: two fills in the same direction were
merged into one averaged lot, which is average-cost accounting, not the FIFO
the module documents. Fixed by appending lots.

---

## 4. P1 (residual) — cwd-relative evidence writers

The state-root pass merged in PR #10 anchored `dry_run`, `micro`, `paper`,
`shadow` and the audit sink. Two writers were still relative:

* `qts edge validate` → `data/evidence/edge_validation.json` **and** the five
  generated `docs/*.md` files;
* `qts research run` / `autonomous` → `campaign_last.json`,
  `autonomous_campaign.json`.

All now resolve through `artifact_path()` / `resolve_state_path()`. New
artifacts `campaign_last` and `autonomous_campaign` are registered with
`QTS_CAMPAIGN_LAST_PATH` / `QTS_AUTONOMOUS_CAMPAIGN_PATH` overrides, and
`tests/test_cli_evidence_path_contract.py` asserts the relative strings are
gone.

This matters more here than elsewhere: `edge_validation.json` is *the*
canonical edge evidence, and a launch from another directory would have written
it into a second tree.

---

## 5. Deliberately NOT done

* **The authorization artifact was not edited and its hash was not
  recomputed.** The audit forbids it and it would have destroyed the owner's
  signature.
* **No `main`-branch data was regenerated.** `data/evidence/edge_validation.json`
  still records the historical 500-bar synthetic run; it was not refreshed,
  because refreshing it would be a new measurement presented as an old one.
* **No strategy was promoted, no threshold was relaxed, and no gate was
  weakened.** Every change either adds enforcement or replaces a conflated
  number with two labelled ones.
* **No real broker data was acquired.** The repository contains no claim-eligible
  dataset; `data/curated/` is gitignored and the bootstrap dataset is synthetic.

---

## 6. Still open

1. **Measure the costs.** Every gate above is one honest measurement away from
   becoming decidable: the broker's quoted spread on `XAUUSD@`, the commission
   per lot per side, and the swap table. Build the model with
   `CostModel.xauusd_default(..., basis=CostBasis.MEASURED, source="<provenance>")`.
2. **Acquire real history.** The audit's step 1 stands unchanged: pinned WM
   Markets DEMO terminal, exact `XAUUSD@` mapping, raw preservation with
   timestamp and clock-offset provenance, immutable hashes. The candidates are
   defined on **15m** bars; the bootstrap dataset is 1H, so every current
   observation is a timeframe mismatch.
3. ~~Freeze the candidate set before evaluation~~ **DONE** — three frozen
   hypotheses in `qts/research/benchmarks.py`, evaluated by
   `qts edge benchmark`. What remains is running them on **real 15m data** with
   **measured** costs.
4. **Execute the randomized and placebo controls.** Both gates still report
   `NOT_IMPLEMENTED` and both still block; they were not touched here.
5. **Launchers must pin `QTS_STATE_ROOT`** (audit acceptance gate, unchanged).

---

## 6b. Phase 2 — the backtest could not simulate the registered strategy

While building the frozen candidate set (open item 3) a deeper defect surfaced.

**The backtest engine had no stop-loss and no time exit.** The only thing that
closed a position was an opposite signal. Every stop-loss strategy was
therefore backtested as a naked always-in reversal system — a different
strategy wearing the same name.

Concretely, the registered DEMO benchmark is an EMA 12/48 rule with a **3.00 USD
protective stop** and a **4-hour maximum hold**. Backtested, it had neither. The
historical measurement and the DEMO measurement were not describing the same
strategy, so no comparison between them was meaningful.

### What was done

| Layer | Change |
|:---|:---|
| `backtest/engine.py` | Declared `exit_rules`: `stop_distance_usd` (protective stop, intrabar) and `max_hold_bars` (deterministic time exit). Part of `config_hash`, so a run with a stop and a run without one are different experiments. |
| `backtest/engine.py` | **Time exits fill at the bar open** and are considered **first**, so a bar that triggers both is settled by the clock. **Stop exits fill at the stop level — or at the open when the bar gapped through it**, because a stop is an order, not a guarantee. Exits are priced by the matching engine, so an exit pays spread and slippage exactly like an entry. |
| `backtest/engine.py` | `run_stress()` carries the same exit rules: stressing the spread of a strategy with a stop while the baseline had none would compare two different strategies. |

On the bootstrap fixture, adding a 3.00 USD stop and a 16-bar hold turned
**2 fills into 38** (18 stop exits, 1 time exit).

### Two integrity bugs found while wiring it up

1. **Silent strategy substitution.** The engine inferred a strategy family from
   a substring of `strategy_id` and swallowed every constructor error, falling
   back to a default. Benchmarks B and C produced *byte-identical* results
   because both had silently run the same fallback. An explicit `_family` now
   **raises** instead of falling back.
2. **Harness params leaked into the constructor.** `quantity` (an order-sizing
   parameter the engine consumes itself) was forwarded to the strategy, raising
   a `TypeError` that was then swallowed — feeding bug 1. Harness params are now
   stripped.

Both produced reproducible, confident evidence about the wrong strategy, which
is worse than no evidence at all.

### The frozen candidate set (audit step 3)

`qts/research/benchmarks.py` — three hypotheses, declared before anything was
measured, each hashed and verified by `verify_frozen()`:

| ID | Family | Role |
|:---|:---|:---|
| `BENCH-A-TREND-EMA-12-48` | EMA 12/48 trend | **CANDIDATE** — the registered DEMO rule, included unchanged |
| `BENCH-B-BREAKOUT-DONCHIAN-20` | Donchian-20 breakout | **CANDIDATE** — volatility-normalized entry |
| `BENCH-C-MEANREV-BOLLINGER-20-2.0` | Bollinger(20, 2.0) reversion | **CONTROL** — exists to be falsified |

A and B share size, stop and hold, so any difference between them is the entry
logic. C is a control that could *plausibly* pass — the only kind worth having:
if a trend rule and its opposite both survive the same gates, the gates are
measuring something other than an edge.

Every evaluation is recorded as a trial, because running three hypotheses *is*
the multiple testing DSR exists to penalise.

New command:

```
qts edge benchmark --spread 0.35 --slippage 0.12 --swap-per-night -1.20 \
    --cost-source "WM Markets XAUUSD@ quoted 2026-10-09 09:15 UTC"
```

Without measured costs it reports `Cost basis: ASSUMED — nothing below can pass
an edge gate` and says what to measure.

### Result on the current dataset

```
BENCH-A  14 round turns  gross +108.36  cost  7.00  net +101.36
BENCH-B  82 round turns  gross -133.09  cost 28.00  net -161.09
BENCH-C  59 round turns  gross -139.59  cost 29.50  net -169.09

NO_EDGE_ESTABLISHED — mechanism evidence only
```

Every row is marked `mechanism_only`, for three independent reasons: the
hypotheses are defined on 15m bars and were evaluated on 1H; the dataset is
synthetic and not claim-eligible; and the costs were not measured. The report
states all three rather than implying the numbers mean what they look like.

---

## 7. External methodology references

Unchanged from the predecessor audit: Moskowitz, Ooi & Pedersen (2012);
Bailey & López de Prado (2014, DSR); Bailey et al. (PBO). These support the
validation methodology. They do not prove that any QTS strategy is profitable.
