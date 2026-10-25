# Backtest metrics — completed round trips vs fills

**Scope:** QTS Python PAPER backtest only. No change to MT5 order submission,
strategy parameters, capital allocation, DEMO execution or the LIVE lock.

## Discovered reporting problem

The baseline backtest's BacktestResult.trades was the number of individual
order **fills**. One round trip often has two fills; partial exits and flip
orders can have more. The displayed BacktestResult.profit_factor was calculated
from bar-to-bar marked-equity returns, which is a *different* measure than
completed-trade gross profits divided by completed-trade gross losses.

A strategy can have positive marked-bar returns on an unclosed position while
having **zero completed trades**. Neither the fill count nor marked-bar profit
factor is evidence of a profitable completed-trade strategy.

## Fixed reporting contract

- BacktestResult.trades = number of **fully closed netted positions** (one
  completed round trip, potentially many entry/exit fills).
- BacktestResult.fill_count = number of actual execution fills, and fills
  retains the original detailed fill tape.
- BacktestResult.profit_factor = ratio of profits to losses from completed
  positions only. Zero when there are no completed positions or no gains.
  The no-loss positive-only convention remains infinity, which is NOT
  sufficient evidence of a reliable strategy.
- BacktestResult.bar_return_profit_factor = pre-existing ratio of positive
  and negative **marked-bar returns**, explicitly separated from trade PF.
- BacktestResult.completed_trade_net_usd = per-position completed net result
  after actual executed prices and opening/closing fees.
- BacktestResult.incomplete_position_count = number of not-flat positions
  at end of replay (these must NOT be counted as completed trades).
- BacktestResult.realized_partial_close_pnl_usd and
  unallocated_open_entry_fees_usd are disclosed independently while positions
  remain open, rather than inflating completed trade results.

The read-only ledger accounts for weighted-average entry price, same-side
adds, partial closes, flips, separate contract sizes by symbol, and
proportional entry/exit fee allocation. It uses execution prices already
inclusive of simulated spread and slippage; costs are not deducted twice.

## Remaining limitations

1. The PAPER matching engine still uses a model, not verified WMMarkets real
   fill receipts. No new XAUUSD@ profitability validation occurred.
2. Net position closes differ from independent signal opportunities; use
   separate strategy-intent analytics for missed-opportunity analysis.
3. MT5-native EA testing, $100/$200 minimum-volume checks, actual financing,
   commission and slippage verification are still outstanding.
4. The numerical ratio can still overfit: complete-trade PF is a reporting
   correction, not a survival test. Positive after-cost edge needs untampered
   broker data, pre-registration, independent unseen holdout and demo forward.
5. Performance metrics in old saved reports are not automatically corrected;
   regenerate historical research using this new source version.
6. Source-level Python test success cannot certify that the MQL5 EA compiles.

**Release/authority state:** research only / no verified edge / LIVE locked.
