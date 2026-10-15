# XAUUSD strategy implementation status — 2026-10-11

## Implementation binding

No Agent 1 proposal/selection artifact was present in the checked-out baseline. To make progress without inventing a new rule or tuning after results, this implementation pass binds to the repository's most defensible already-researched daily candidate: **`ma_20_100_atr3`**. The 2026-10-10 long-history report names it the strongest candidate by robustness (four of seven gates, including walk-forward and regime gates), while explicitly rejecting it as validated. This is a provisional engineering choice, not evidence that the strategy has an edge and not a promotion.

The implementation is deliberately a thin, research-only entry point in `qts.research.longhistory.selected`. It reuses the frozen candidate, signal builder, daily window logic and execution/cost engine; it does not copy the strategy logic or connect an order path.

## Frozen rule, unchanged

- **Bars:** daily XAUUSD OHLC, UTC-normalized to midnight timestamps.
- **Signal:** after SMA warm-up, target long while SMA(20) > SMA(100), otherwise short. The decision at the completed daily close uses only data available through that close.
- **Entry/reversal:** next daily bar open, never the same close.
- **Risk:** 3 × ATR(14) protective stop; size from the existing 1%-of-equity stop-risk formula, capped at 1.0× notional.
- **Stops:** checked against the next bar's high/low; fill at the stop or at the open if the market gaps through. The existing engine blocks re-entry in the stopped direction until the signal state changes.
- **Costs:** the frozen study's **ASSUMED** model: 3 bps full spread, 1 bp slippage per side, USD 7/lot/side commission, and 0 financing bps/day. Zero financing is an explicit assumption—not a measured zero swap. The output remains non-claim-eligible.
- **No parameter selection in this wrapper:** candidate ID is fixed to `ma_20_100_atr3`; a rule or parameter change requires a new preregistration.

`build_selected_plan()` rejects intraday, non-normalized, duplicate/out-of-order, non-finite, non-positive, or inconsistent OHLC inputs. `run_selected_window()` delegates to the existing cost-aware long-history runner and refuses a cost model labeled `MEASURED`, because no broker cost evidence is bound to this wrapper. There is no broker, demo, live, or order-submission import in this entry point.

## Existing historical evidence — not a new result

The checked-in final-stage artifact is `data/evidence/longhistory/research_final.json`, governed by `docs/research/preregistration_longhistory_2026-10-10.md`. At the time it was generated, its daily `ma_20_100_atr3` result was:

- Holdout net: **+$530**, Sharpe **0.30**, 14 round turns; net at 2× assumed costs **+$506**.
- Walk-forward: Sharpe **0.17**, 6/10 positive years.
- Gates: **4/7**. Fails Holm-adjusted significance; DSR is **0.12** against a 0.95 threshold; only **61** out-of-sample round turns against a 100 minimum.
- Buy-and-hold's holdout was **+$8,796**, materially higher. Other pre-registered families also failed the full gates.

**Accounting audit, 2026-10-14:** `docs/audit/longhistory_engine_accounting_audit_2026-10-14.md` found that the prior engine's mark-to-market multiplied a fixed entry fraction by changing equity, which implicitly resized positions without a fill or costs. These committed historical numbers use that pre-v2 execution model. They remain archived as historical diagnostics only; they are not validated performance evidence, are not comparable to the corrected `fixed_units.v2` engine, and have not been recomputed on the reused holdout. The standing verdict is still `NO_VALIDATED_EDGE`.

## Reproducible mechanism smoke output

`scripts/run_selected_strategy_smoke.py` builds the 260-bar synthetic daily path and writes `reports/selected_strategy_smoke_2026-10-11.json`; the unit/regression test checks that artifact against the live runner output. The machine-readable record includes the OHLC fixture hash, assumptions, the `fixed_units.v2` accounting-model version, per-trade accounting, base-cost result, and 2× sensitivity. The base run is:

| Data | Candidate | Round turns | Gross | Simulated costs | Financing | Net | Final equity |
|---|---|---:|---:|---:|---:|---:|---:|
| Synthetic, mechanism-only (`fixed_units.v2`) | `ma_20_100_atr3` | 3 | $277.1050 | $17.2546 | $0.0000 | $259.8504 | $10,259.8504 |

The 2× assumed-cost regression run is gross $276.9209, fill costs $34.4895, net $242.4314, and final equity $10,242.4314. These numbers are a regression fixture for timing, fixed-quantity accounting, sizing, cost decomposition and determinism. The synthetic path intentionally contains a trend; it is **not a market backtest**, must not be compared with historical performance, and is not claim-eligible. The tests also verify truncation causality, 3×ATR sizing and stops, next-open entry, intrabar stop fills without same-direction re-entry, explicit cost assumptions, no implicit resize between fills, explicit rebalance fills, and time-prorated carry.

Reproduce the JSON output and its regression check with:

```bash
python scripts/run_selected_strategy_smoke.py
pytest tests/unit/test_longhistory_selected_strategy.py -q
```

## Performance validation: BLOCKED

The raw processed inputs used by the committed historical study are absent in this checkout (`data/raw/longhistory/processed/*.csv`, gitignored), so the full historical result cannot be independently regenerated here. The corresponding real-input tests skip for this reason. The existing provenance report also identifies the BaseMax history as an unverified third-party quote stream; its cross-exports are not independent. The Dukascopy series is only a short, previously used replicate and its upstream licence is absent. No measured broker spread, slippage, commission, or financing evidence is available. The repository does contain a separate 23-event Dukascopy spread sample (`data/evidence/xauusd_event_spread_evidence.json`), but it is neither continuous nor broker-specific and says nothing about actual fills, commission, or swap; it is not substituted for the frozen cost assumption.

Accordingly, performance validation for this implementation is **BLOCKED**. The existing study's reported values are retained as context only; the smoke test does not unblock it. Any next performance test needs a new preregistration and a genuinely untouched/independent licensed dataset, plus measured execution costs (including swap where applicable). Do not retune this rule on the reused holdout.

## Safety boundary

No live or demo orders were placed. `LIVE_LOCKED`, demo authorization, risk limits, and promotion state were not changed. This module is research-only and has no route to execution.
