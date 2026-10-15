# Preregistration addendum — long-history fixed-unit accounting v2

- **Protocol ID:** `LH-XAUUSD-ACC-V2-2026-10-14`
- **Frozen on:** 2026-10-14 (UTC)
- **Status:** Methodological amendment preregistered before any `fixed_units.v2`
  market-performance evaluation. No such evaluation is authorized by this
  document or has been run.
- **Scope:** Research-only daily and intraday engines in
  `qts.research.longhistory.engine`; not a strategy proposal, candidate
  selection, or promotion.
- **Audit:** `docs/audit/longhistory_engine_accounting_audit_2026-10-14.md`

## 1. Purpose and separation from frozen results

The former engine marked a position as a fraction of changing equity, which
implicitly changed physical exposure without a fill, turnover, or execution
cost. This amendment freezes the corrected `fixed_units.v2` accounting
contract. It does not revise, reproduce, or reinterpret the historical results
already generated under the former engine.

The daily, M15, seasonal, and reversal final-stage artifacts are immutable
historical diagnostics under the pre-v2 method. The reused 2020–2025 holdout
and already-seen Dukascopy replicate are **not eligible** for evaluating the
correction, selecting a strategy, or making a v2 performance claim. A future
claim-grade study requires a newly preregistered protocol and a genuinely
untouched, appropriately licensed evaluation dataset.

No candidate IDs, signal rules, parameters, date splits, or multiple-testing
counts are introduced or changed here. Any future strategy evaluation must
freeze those items separately before inspecting its evaluation data.

## 2. Frozen position-accounting contract

1. **Decision/fill timing:** a plan written from bar `t` executes no earlier
   than bar `t+1` open. Existing conservative stop and gap-fill ordering is
   unchanged.
2. **Entry sizing:** for a non-flat target at an entry fill price `p`, use
   `f = min(plan.size, cap)`, where `0 <= cap <= 1`; create signed ounces
   `units = direction * f * equity_before_fill / p`. The engine starts flat.
   A zero size or zero cap creates no position and no fill.
3. **Between fills:** signed ounces stay constant. Mark-to-market P&L is
   `units * (price_change)`; do not multiply exposure by current equity or
   create implicit bar-by-bar rebalances.
4. **Explicit rebalance:** resize only when the plan explicitly sets
   `rebalance=True` for an open position. At the fill price, calculate target
   units from the capped requested fraction of current equity. Trade the
   actual signed-quantity difference; a zero-size rebalance closes the
   position.
5. **Exit and stop:** close or stop the actual held units. A stop crossed at
   the open fills at that open; otherwise it fills at the stop level, with the
   existing adverse-gap convention. Forced window-end closure is a real fill.
6. **Fill costs:** charge each entry, exit, stop, and explicit rebalance on the
   absolute notional actually traded, `abs(delta_units * fill_price)`, at that
   fill price. A full exit trades all remaining units. Cost-rate inputs,
   accounting version, and basis are recorded; non-finite/negative cost
   components, invalid prices, inconsistent OHLC, malformed targets, invalid
   equity, and leverage above the cap fail closed.
7. **Financing:** the engine's optional `financing_bps_per_day` is a simplified,
   symmetric bps-per-calendar-day sensitivity charge on marked notional,
   prorated by elapsed timestamp duration. Normalize timestamps before
   duration arithmetic. On the terminal in-window bar, use the median interval
   observed strictly inside that run window; later timestamps cannot influence
   its carry charge. This is **not** a measured broker swap schedule: it does not model
   long/short differences, contract-specific rules, or weekday multi-day
   rollover. It must not be labeled `MEASURED` without separate broker evidence
   and reconciliation.
8. **Metadata and accounting:** every run summary must identify
   `accounting_model_version = "fixed_units.v2"`; cost descriptions must
   identify the simplified financing convention. Preserve the existing
   trade-ledger/equity reconciliation invariant whenever all positions are
   closed.

The implementation revision used by any later study must be identified by
its exact source revision and `fixed_units.v2` accounting-model version in the
result manifest. Changes to these semantics require another versioned
amendment before market evaluation.

## 3. Cost evidence and claim eligibility

`ASSUMED` inputs may be used only for transparent mechanism checks and
sensitivity analysis. They cannot establish an economic edge. Any future
claim-grade run must bind costs to reproducible evidence from the intended
broker and instrument, including the applicable spread, slippage, commission,
contract conversion, and direction-/rollover-specific financing. Missing cost
components remain `UNKNOWN`; they may not silently become zero. The simplified
symmetric carry model alone is not broker-cost evidence.

## 4. Validation allowed by this amendment

Before using any market data, the implementation may be validated with
synthetic, deterministic fixtures only. The acceptance checks are:

- A fixed signed quantity produces the hand-calculated P&L across sequential
  prices without a fill.
- An explicit resize changes units only at its declared fill and turnover/cost
  use the actual quantity delta; zero size closes and zero cap prevents entry.
- Entry, stop, reversal, and forced-exit costs match hand calculations on the
  actual traded quantity; ledger and equity reconcile.
- Carry scales with elapsed time across intraday intervals and calendar gaps,
  is independent of Pandas timestamp storage resolution, and cannot be changed
  by observations after a run window.
- Invalid cost, OHLC, plan, window, equity, and leverage inputs are rejected.
- Smoke output is deterministic, synthetic-only, version-labeled, and makes no
  performance or edge claim.

These checks test implementation mechanics only. A positive synthetic result
is not evidence about XAUUSD.

## 5. Requirements before a future market evaluation

A future evaluation is blocked until a *separate* preregistration records, at
minimum:

- frozen hypotheses, signal/exit/sizing rules, source revision, complete trial
  count, and all statistical gates before evaluation;
- a licensed source, point-in-time provenance, timestamp/session basis, data
  quality rules, sample boundaries, and a genuinely untouched evaluation
  window not present in any prior QTS report, holdout, replicate, or tuning;
- independently measured broker execution costs and their evidence IDs,
  including financing where positions can cross a rollover; and
- an explicit prohibition on changing the candidates, gates, cost model, or
  splits after viewing evaluation outcomes.

The 2020–2025 reused holdout and previously seen replicate named above are
permanently excluded from a fresh v2 claim. If suitable independent data or
measured costs are unavailable, the output remains diagnostic and the project
verdict remains `NO_VALIDATED_EDGE`.

## 6. Results and authorization

- **Market evaluation under v2:** none performed.
- **Historical evidence rewritten or rerun:** no.
- **Promotion:** none; all prior edge gates and trial counts remain unchanged.
- **Execution authority:** unchanged; research-only, `LIVE_LOCKED`,
  `REAL_CAPITAL_EXPOSURE = 0`.
- **Project verdict:** `NO_VALIDATED_EDGE`.
