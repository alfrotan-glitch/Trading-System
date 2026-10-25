# QTS external robot benchmark — research only

This is a **read-only, strict and auditable** side-by-side comparison of
QTS and a third-party automated trader on matching trade-ledger conditions.
It **never submits orders**. It does not claim any strategy is profitable.

## Why we built this

- **Gold Reaper MT5** has a two-year tracked real account with net profits,
  but other developer accounts experienced materially higher drawdowns.
  One MQL5 signal and its matching Myfxbook page count as **one account**.
  Product: https://www.mql5.com/en/market/product/111357
  Independent review: https://therobotictrader.com/gold-reaper-ea-review
- An additional independent strategy-tester analysis showed a degradation
  from simpler simulation to real ticks and stressed drawdowns:
  https://doittrading.com/insights/strategies/the-gold-reaper-mt5-review/
- EA31337 offers source architecture, NOT proof of profitable gold trading:
  https://github.com/EA31337/EA31337
  Its GPL source must not be silently incorporated into proprietary QTS.
- QTS already has a causal breakout/pullback/sweep research system, tick
  replay, execution-receipt protection, loss controls and audited trades.
  **Do not build a second standalone robot or rerun previously seen
  holdouts until a win appears.**

## Inputs

First obtain genuine closed-trade exports from comparable MT5 Strategy Tester
runs on the *same broker and XAUUSD@*. Both require gross gains/losses measured at **actual executed** entry/exit Bid/Ask fills.
Do **not** subtract spread or slippage a second time. Commission, swap and
fees are separate broker charges; positive swap is a charge, negative is a
credit. Never invent missing trades or charges. A blank slippage field means
not measured, not zero.

Each ledger is a UTF-8 CSV with columns:

    deal_id,position_id,exit_time_utc,side,gross_usd,commission_usd,slippage_usd,swap_usd,fee_usd

Commission and broker fees are nonnegative charges; swap may be a credit.
The slippage_usd column is **diagnostic only** and may be empty (unknown).
It must not be deducted from gross based on actual fills. Exit timestamps
must have an explicit UTC offset. Every deal_id must be unique. Each close
deal needs its MT5 position_id (DEAL_POSITION_ID). Partial closing deals of
the same position count as one position for per-position PF and expectancy;
their realized profits still count on their respective exit dates.

Alongside each CSV create a manifest.json with values like:

    {
      "schema_version": 1,
      "source": "Native MT5 tester: identify settings and tested EA version",
      "broker": "WMMarkets",
      "broker_server": "WMMarkets-Demo",
      "execution_model": "REAL_TICKS",
      "market_data_sha256": "64-character SHA256 digest of the same underlying real-tick archive",
      "contract_size": 100.0,
      "point_size": 0.01,
      "volume_step": 0.01,
      "leverage": 100,
      "symbol": "XAUUSD@",
      "account_type": "TESTER",
      "account_currency": "USD",
      "account_key": "qts-reference-anonymous-1",
      "period_start": "2026-10-01",
      "period_end": "2026-10-25",
      "initial_equity_usd": 10000,
      "cost_basis": "EXECUTABLE_BID_ASK",
      "ledger": "trades.csv",
      "ledger_sha256": "64-character SHA256 digest of exact CSV"
    }

The reference must have a **different account_key**. Use anonymous labels,
not passwords, broker login IDs or secrets. The market data checksum must be the digest of the actual **same real-tick
archive**, not two made-up matching strings. A DEMO or REAL account uses the
matching execution_model instead of REAL_TICKS, and must retain a documented
common tick archive where available. The manifest assertions are
operator-supplied and NOT an independent authentication of trade origin.

## Windows command

    py -3 gold_robot\research\reference_benchmark.py --candidate C:\Research\QTS\manifest.json --reference C:\Research\Reference\manifest.json --output C:\Research\comparison.json

No extra package is required. The output is JSON with research-only status.

## How to read the output

- Reported gross, commission/swap/fees, net, per-position profit factor,
  and realized-deal drawdown use **realized** values, not marked-to-market
  equity risk. Position IDs group partial exits; the CSV does not prove that
  every position is fully closed or that open exposure is absent.
- The daily paired difference is scaled by each starting balance, and
  explicitly includes days without trades.
- The seeded **7-calendar-day moving-block** bootstrap 99% lower bound
  preserves some temporal clustering. For fewer than 28 days, it is omitted.
  This is descriptive only; intraday serial dependence, variable risk,
  broker fills and capital flows may invalidate its coverage.
- Matching declared broker, symbol, account mode, currency, period and cost
  basis is mandatory; mismatches are rejected rather than hidden.
- An attractive signal with unverified provenance is **not** credible proof.
- A real Gold Reaper account on a different broker cannot be relabeled
  as WMMarkets tester data merely to pass validation.
- A positive report **cannot promote** strategies or enable demo/live
  orders. Independent unseen future ticks and official broker receipts
  remain mandatory.

QTS canonical EA is unchanged. Existing safety and LIVE lock remain.
No benchmark reports or tests can unlock real-money trades.
