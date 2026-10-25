# QTS — Binance Spot, $200 USDT account: research-only first phase

**Date:** 2026-10-25. **Current state:** public market-data probe + offline 200-USDT paper account only. **No Binance API key, no credentials, no authentication, no order submission, no trading permission.** Gold/MT5 remains unchanged. There is no validated Binance edge.

## Why this is a separate venue

MT5 \`XAUUSD@\` is a broker-specific gold CFD/symbol; Binance Spot uses actual base/quote balances and venue-specific symbol constraints (e.g. \`BTCUSDT\`, \`ETHUSDT\`). A \`SELL\` on Spot disposes of *owned* assets; it does not create a new short position. No margin, perpetual/futures or leverage is in scope.

A third-party EA written for MT5 does not automatically connect to Binance. The long-term route is \`QTS Signals -> venue adapter (MT5 or Binance Spot) -> independent risk authority -> idempotent broker ledger\`. **Never reuse MT5 position/order semantics or unlock policies as an implicit Binance trading permission.**

## What was actually delivered

\`src/qts/research/binance_spot_paper.py\`

- Public Binance Spot exchange metadata (\`GET /api/v3/exchangeInfo\`) and executable bid/ask snapshots (\`GET /api/v3/ticker/bookTicker\`) over the Binance **market-data-only** host \`https://data-api.binance.vision\`.
- Allowlisted read-only endpoints and strict public-symbol matching; **no key, signature, POST or account access**.
- Decimal-precision sizing with detected LOT_SIZE, quantity step and minimum notional; rejects non-USDT pairs, inactive spot symbols, inconsistent data and too-small hypothetical trades.
- Paper-only long-spot ledger: 200 USDT initial cash, 40 USDT maximum buy allocation, 0.50 USDT notional stop-loss risk budget, assumed 0.1% per-side fee, one asset at a time, cannot short or average down. These are **defaults for modelling, not recommended live settings**.
- Paper fills assume displayed ask on entry and displayed bid on exit; real spread/slippage, partial fills, maker/taker rate differences, base-asset/BNB fees, suspended symbols and order latency are not fully modelled.
- Five offline unit tests in \`tests/test_binance_spot_paper.py\`, run locally before committing (5 passed). **No native Binance API connection test was performed**, because credentials/network from user environment are not available.
- A paper stop price is used **only to size** a hypothetical purchase; it is *not* a placed, working or automatically enforced protective order. The ledger and trade record are in memory only and reset with the Python process.

## Windows usage (public observation only)

1. Open PowerShell in the current \`Trading-System\` repository folder.
2. \`git pull origin main\` (only if the local worktree is clean and no unpublished work would be overwritten).
3. From an already-installed QTS Python environment, run:
   \`python -m qts.research.binance_spot_paper --symbol BTCUSDT\`

Expected shape: \`mode: PUBLIC_DATA_ONLY\`, \`orders_submitted: 0\`, \`live_access: false\`, and bid/ask/quantity-filter data if the Binance public host is reachable. This command does **not** simulate an order, log into Binance or trade $200. Other symbols such as \`ETHUSDT\` need fresh metadata and independent checks.

**Do not enter, email, paste, screenshot or commit an API key/secret to QTS, GitHub, chat or logs.** API keys for future research should be created locally on the exchange's official page, have only minimal permissions, withdrawals disabled, and IP restrictions where supported. Public prices need no key.

## Next phase — Binance Spot Demo Mode

Binance now provides official **Demo Mode**, separate from the older Spot Testnet:

- https://developers.binance.com/en/docs/products/spot/demo-mode/general-info
- Demo REST \`https://demo-api.binance.com/api\`; Demo API keys are created via Binance's official Demo API management.
- Per Binance, Demo prices and market books are *similar* to live; Testnet prices and books are independent. Demo balances are virtual. **No Demo order connector is implemented in this phase.**
- Build a new *explicitly DEMO-only*, fully journalled and idempotent adapter; use Demo-only keys and host allowlists; enforce all exchange filters and correct wallet order/fee semantics; handle execution status UNKNOWN after API timeouts by querying the order, not blindly retrying.
- Wire only after local operator consent, qualified region/KYC, key management, read-after-write reconciliation tests, real-bid/ask market data, and a strategy with independent after-fee prospective evidence. The main QTS real-money lock does not authorize Binance Spot.

References: 
- https://developers.binance.com/en/docs/products/spot/demo-mode/general-info
- https://developers.binance.com/en/docs/products/spot/rest-api
- https://github.com/binance/binance-spot-api-docs/blob/master/filters.md
- https://www.binance.com/en/fee/trading

## Costs for a small balance

Regular-spot fee published by Binance is 0.10% maker / 0.10% taker before eligible discounts, but actual user/pair fee must be verified. If a 40 USDT position is opened and later sold near the same price, 0.1% each side costs approximately **0.08 USDT** before bid/ask spread and slippage. A 1% favorable price move on 40 USDT produces only about **0.40 USDT gross**. This makes high-frequency marginal signals especially cost-sensitive. The paper cap of 0.50 USDT is a sizing *estimate* and does **not** guarantee loss cannot exceed it during price gaps.

A 200-USDT Spot account should not be compared with leveraged MT5 XAUUSD scalping results. No daily-profit target and no mandatory daily trade count are valid risk controls.

## Geographic eligibility

Trading and API access depend on the **account's actual verified country of residence** and applicable regional restrictions. App-store availability does not establish exchange-trading permission. Binance's 2026 spot trading-pair announcements explicitly restrict Canada for certain products/pairs; do not assume a Canadian resident can trade on Binance.com. We have not checked the user's personal KYC or account eligibility and do not bypass geo controls.

## What is NOT complete

No exchange account connection, Demo order placement, key storage, production service, persistence, Binance kill switch, stop-order lifecycle or integrated OTT/QQE buy-sell signal driver. This is a deliberately constrained first phase: safe public data and auditable offline portfolio arithmetic. The negative XAUUSD M5 research results cannot be turned into evidence for crypto Spot, and no Binance profitable edge has been shown.
