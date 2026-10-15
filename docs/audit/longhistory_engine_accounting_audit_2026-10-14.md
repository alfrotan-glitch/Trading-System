# Long-history backtest accounting audit — 2026-10-14

## Decision

A source-level audit found a material accounting defect in the research-only
long-history engine (`src/qts/research/longhistory/engine.py`). It has been
corrected as `fixed_units.v2`, with synthetic regression tests. This is an
execution-model correction, **not** evidence of an XAUUSD edge.

The frozen daily, M15, seasonal, and reversal evidence remains archived exactly
as generated under the previous accounting model. It was **not** rerun on the
reused 2020–2025 holdout or the already-seen Dukascopy replicate. Its numerical
performance results are now historical diagnostics only and are not comparable
to results produced by `fixed_units.v2`. Those studies had no passing edge
anyway; their standing verdict remains `NO_VALIDATED_EDGE`. No candidate is
promoted, and LIVE remains locked.

## Defects

### 1. Mark-to-market implicitly rebalanced positions for free

The previous mark-to-market formula was equivalent to:

```python
pnl = direction * position_fraction * current_equity * price_return
```

The fraction was set at entry and normally changed only at an explicit signal
rebalance. Multiplying it by *current* equity at every bar silently changed the
number of ounces held as equity moved. That is continuous/daily target-weight
rebalancing, but the engine did not create those orders, add their turnover, or
charge the configured spread, slippage, and commission. The declared execution
contract instead says a position keeps its size until an entry, exit, stop, or
explicit `rebalance=True` fill.

The direction of the resulting P&L error is path-dependent; it cannot be
corrected by applying a single haircut. For a 0.5-equity position entered at
$100 with $10,000 equity and then held through $110 and $121, the prior formula
records $1,025 of gross P&L. A fixed 50-ounce position records $1,050. A real
resize at $110 would be an explicit fill with costs; no such fill occurred in
the prior simulation.

### 2. “Per day” financing was charged once per bar

The old engine charged `financing_bps_per_day` at every bar. On M15 data that
would apply a daily rate 92 times in a complete QTS trading day. All frozen
long-history protocols use an explicit zero financing assumption, so this
specific issue did not add financing to their old numbers. It did make the
shared engine unsafe for a future non-zero M15 carry assumption.

## Correction

`fixed_units.v2` now:

- Converts an entry target notional into a signed XAU quantity (ounces); that
  quantity remains fixed between fills.
- Marks gaps, intrabar P&L, and stop exits against the held quantity, not a
  fraction of changing equity.
- Changes quantity only on an entry, exit, stop, or explicit same-direction
  `rebalance=True`. A resize's actual quantity delta is included in turnover
  and charged as a fill at the modeled side rate.
- Accrues the simplified `financing_bps_per_day` continuously in proportion to
  elapsed calendar time between bar stamps. Timestamps are normalized to
  nanoseconds before duration arithmetic so Pandas datetime resolutions cannot
  change the result. The last in-window bar uses the median interval observed
  inside that run window; data after the window cannot change its carry charge.
- Rejects non-finite/negative cost inputs, non-positive fill prices, invalid
  OHLC ranges, malformed plan values, non-positive initial equity, and a
  notional cap above 1.0 (no leverage).
- Includes `accounting_model_version` in run summaries so future artifacts
  identify the position-accounting contract.

**Carry limitation:** this bps/day calculation is intentionally a simple,
symmetric, time-prorated rate. It is not an empirical broker swap schedule; it
does not model long/short-specific financing or weekday-specific multi-day
rollover. Those costs remain `ASSUMED`/`UNKNOWN` until captured from the actual
broker and reconciled to held positions. No frozen protocol is upgraded to
`MEASURED` by this change.

## Verification

Verification run on 2026-10-15:

- Focused engine/protocol/Agent-4 tests: **104 passed, 2 skipped** (106
  collected). The two skips are existing data-dependent cases; the suite did
  not perform a market-performance evaluation.
- Fast CI Python suite: **exit 0**, 1,528 tests collected (integration and
  research directories excluded, matching the fast CI job).
- Extended CI integration/research suite: **exit 0**. Its synthetic/fake
  integration cases and audit checks passed; frozen long-history final-stage
  and reused-holdout evaluation commands were not invoked.
- UI suite: **48/48 passed**.
- Ruff: passed. Mypy: passed across 186 source files. Bandit: exit 0.
- Seasonal synthetic-gate tests emit SciPy precision-loss warnings for
  deliberately near-identical return arrays; there were no test failures.
- No frozen final/holdout market evaluation was run.
- Frozen final JSON files were hash-checked and remain unchanged:
  `research_final.json` `a2bc0a5040dc6ed959eef178a331db72f82da26e2f62942d66554fe1fa08c19d`,
  `intraday_research_final.json` `5097feb8b4ea441333e3c65d29735dd67b455d7aa8b8604b545390b2c607d321`,
  `seasonal_research_final.json` `785ae4d5c2d2f90c7120ea78a996a29ff3b2012b463adb254a6f7876b7f645a2`,
  and `reversal_research_final.json` `0c44de5c608033e4399a9097b42954fe049377734579369831c87de14cbe5e99`.

Synthetic accounting tests pin:

1. Fixed-unit P&L across sequential price gaps, versus a separately flagged
   explicit rebalance; resize turnover and costs use the actual quantity delta,
   including the zero-size close edge case.
2. Commission/spread/slippage on actual fill notionals, zero-cap entry refusal,
   malformed inputs, and no-leverage bounds.
3. Time-prorated carry on M15 bars, a Friday-to-Monday calendar interval,
   Pandas lower-resolution timestamps, and exclusion of post-window time gaps.
4. Stop and gap execution, ledger/equity reconciliation, and deterministic
   smoke output with the accounting and financing convention identified.

The mechanism-only smoke fixture now reports, under `fixed_units.v2`:

| Input | Round turns | Gross | Fill costs | Carry | Net | Final equity |
|---|---:|---:|---:|---:|---:|---:|
| Deterministic synthetic path, base assumed costs | 3 | $277.1050 | $17.2546 | $0.00 | $259.8504 | $10,259.8504 |
| Same synthetic path, 2× assumed costs | 3 | $276.9209 | $34.4895 | $0.00 | $242.4314 | $10,242.4314 |

This path is deliberately synthetic and rising in places. It is a regression
fixture only, not market evidence, and its positive net result is not a claim.

## Research-integrity consequences

- The committed final-stage JSON and tables were **not** rewritten, since doing
  so would silently replace a frozen result with a different engine and revisit
  reused evaluation data.
- Existing historical results must be labelled as using the pre-v2 model and
  cannot validate, select, or promote a strategy under the corrected engine.
- The corrected accounting contract is recorded in
  `docs/research/preregistration_longhistory_fixed_units_v2_2026-10-14.md`
  before any future v2 market-performance evaluation. That addendum authorizes
  no evaluation and does not create a candidate or change existing gates.
- A future strategy-performance study needs its own preregistration and an
  untouched, licensed independent test window. The already reused holdout is
  not refreshed by changing the simulator.
- Costs still need actual DEMO broker measurements (spread, slippage,
  commission, and direction-/rollover-specific swap). No MT5 order was sent.

The execution engine, DEMO authorization, risk limits, promotion state, and
`LIVE_LOCKED` boundary were not changed. `REAL_CAPITAL_EXPOSURE` remains zero.
