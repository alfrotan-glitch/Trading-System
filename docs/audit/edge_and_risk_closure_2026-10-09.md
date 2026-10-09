# Edge & Risk Closure — 2026-10-09

**Branch:** `arena/db6f7053-trading-system`
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
   timestamp and clock-offset provenance, immutable hashes.
3. **Freeze the candidate set before evaluation** (audit step 3): benchmark A
   EMA 12/48 completed-bar trend, benchmark B volatility-normalized breakout,
   benchmark C mean-reversion control — and evaluate all three against the same
   measured cost model.
4. **Execute the randomized and placebo controls.** Both gates still report
   `NOT_IMPLEMENTED` and both still block; they were not touched here.
5. **Launchers must pin `QTS_STATE_ROOT`** (audit acceptance gate, unchanged).

---

## 7. External methodology references

Unchanged from the predecessor audit: Moskowitz, Ooi & Pedersen (2012);
Bailey & López de Prado (2014, DSR); Bailey et al. (PBO). These support the
validation methodology. They do not prove that any QTS strategy is profitable.
