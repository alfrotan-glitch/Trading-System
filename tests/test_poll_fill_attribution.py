"""Live fill-poll attribution regression suite.

Root cause found in the Windows audit (latent on every platform):
``MT5Adapter.poll_fills`` returned deal dicts WITHOUT ``client_order_id`` and
without a stable ``fill_id``. ``ExecutionEngine.poll_live_fills`` therefore:

* applied fills to the portfolio that could not be attributed to any order
  (portfolio/order-state divergence — the order stayed ACCEPTED although the
  fill was booked, i.e. state said "not filled" while exposure existed);
* generated a fresh uuid fill_id per poll, so dedupe never worked — repeated
  polls would double-apply the same economic fill.

Fixed behavior pinned here:
1. attributed fills advance order state (PARTIALLY_FILLED -> FILLED) and are
   applied exactly once (stable deal-ticket fill ids dedupe across polls);
2. UNATTRIBUTED fills are never applied (fail closed) and are audited as
   UNATTRIBUTED_FILL for reconciliation;
3. an order is never marked FILLED merely because it was submitted.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from qts.adapters.matching import MatchingConfig, MatchingEngine
from qts.adapters.mt5_adapter import MT5Adapter
from qts.domain.value_objects import Instrument, OrderIntent, OrderState, OrderType, Side
from qts.execution.engine import ExecutionEngine, OrderManager
from qts.execution.idempotency import IdempotencyStore
from qts.observability.audit import InMemoryAuditLog
from qts.portfolio.portfolio import Portfolio
from qts.risk.engine import RiskEngine, RiskLimits


def _mock_mt5(deals=None, positions=None):
    m = MagicMock()
    info = MagicMock()
    info.contract_size = 100
    info.volume_min = 0.01
    info.volume_max = 100
    info.volume_step = 0.01
    info.digits = 2
    info.point = 0.01
    info.trade_tick_size = 0.01
    info.trade_mode = 4
    info.trade_allowed = True
    info.filling_mode = 1
    info.execution_mode = 0
    info.trade_stops_level = 10
    info.trade_freeze_level = 0
    m.symbol_info.return_value = info
    m.symbol_select.return_value = True
    m.last_error.return_value = (1, "ok")
    tick = MagicMock()
    tick.bid = 2000.0
    tick.ask = 2000.5
    tick.time = datetime.now(UTC).timestamp()
    m.symbol_info_tick.return_value = tick
    m.terminal_info.return_value = MagicMock(connected=True, trade_allowed=True)
    m.account_info.return_value = MagicMock(
        balance=10000, equity=10000, margin=0, margin_free=10000, leverage=100, currency="USD", login=1
    )
    sym = MagicMock()
    sym.name = "XAUUSD"
    m.symbols_get.return_value = [sym]
    res = MagicMock()
    res.retcode = 10009
    res.order = 123456
    res.deal = 654321
    res.comment = ""
    m.order_send.return_value = res
    m.positions_get.return_value = positions or []
    m.orders_get.return_value = []
    m.history_deals_get.return_value = deals or []
    return m


def _deal(ticket, comment, volume=0.01, price=2000.5, deal_type=0):
    d = MagicMock()
    d.ticket = ticket
    d.comment = comment
    d.symbol = "XAUUSD"
    d.volume = volume
    d.price = price
    d.type = deal_type
    d.time = datetime.now(UTC).timestamp()
    return d


def _engine(tmp: Path, mock):
    from qts.adapters.market_data import MarketDataProvider

    broker = MT5Adapter(mt5_module=mock)
    audit = InMemoryAuditLog()
    db = tmp / "eng.db"
    om = OrderManager(audit=audit, idempotency=IdempotencyStore(db_path=db))
    risk = RiskEngine(RiskLimits(), db_path=db)
    pf = Portfolio(initial_balance=Decimal("10000"))
    eng = ExecutionEngine(
        om,
        risk,
        broker,
        MatchingEngine(MatchingConfig()),
        pf,
        audit=audit,
        db_path=db,
        market_data=MarketDataProvider(broker),
    )
    return eng, broker, om, pf, audit


def _submit(eng, cid="poll-test-0001", qty="0.02"):
    intent = OrderIntent(
        instrument=Instrument(symbol="XAUUSD", venue="MT5"),
        side=Side.BUY,
        quantity=Decimal(qty),
        client_order_id=cid,
        strategy_id="s",
        order_type=OrderType.MARKET,
    )
    order, _ = eng.submit_intent(intent)
    assert order.state == OrderState.ACCEPTED  # submitted != filled
    return intent, order


def test_attributed_fill_advances_state_and_applies_once():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        mock = _mock_mt5()
        eng, broker, om, pf, audit = _engine(tmp, mock)
        intent, order = _submit(eng, qty="0.01")
        comment = broker._load_comment_map(intent.client_order_id)
        assert comment is not None
        mock.history_deals_get.return_value = [_deal(1001, comment, volume=0.01)]

        fills = eng.poll_live_fills()
        assert len(fills) == 1
        refreshed = om.get(intent.client_order_id)
        assert refreshed.state == OrderState.FILLED
        assert refreshed.filled_quantity == Decimal("0.01")
        assert len(pf.positions) == 1

        # second poll with the same deal (stable ticket id) must NOT double-apply
        fills2 = eng.poll_live_fills()
        assert fills2 == []
        assert pf.positions["XAUUSD"].quantity == Decimal("0.01")


def test_partial_fill_marks_partially_filled():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        mock = _mock_mt5()
        eng, broker, om, pf, audit = _engine(tmp, mock)
        intent, order = _submit(eng, qty="0.02")
        comment = broker._load_comment_map(intent.client_order_id)
        mock.history_deals_get.return_value = [_deal(2001, comment, volume=0.01)]
        eng.poll_live_fills()
        mid = om.get(intent.client_order_id)
        assert mid.state == OrderState.PARTIALLY_FILLED
        assert mid.filled_quantity == Decimal("0.01")
        # remainder fills -> FILLED
        mock.history_deals_get.return_value = [
            _deal(2001, comment, volume=0.01),
            _deal(2002, comment, volume=0.01),
        ]
        eng.poll_live_fills()
        done = om.get(intent.client_order_id)
        assert done.state == OrderState.FILLED
        assert done.filled_quantity == Decimal("0.02")
        assert pf.positions["XAUUSD"].quantity == Decimal("0.02")


def test_unattributed_fill_is_never_applied():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        mock = _mock_mt5()
        eng, broker, om, pf, audit = _engine(tmp, mock)
        _submit(eng, qty="0.01")
        # deal whose comment maps to nothing we ever submitted
        mock.history_deals_get.return_value = [_deal(3001, "unknown-manual-deal", volume=0.5)]
        fills = eng.poll_live_fills()
        assert fills == []
        # portfolio untouched — no phantom exposure booked from an unknown deal
        assert pf.positions.get("XAUUSD") is None or pf.positions["XAUUSD"].quantity == Decimal("0")
        # audited for reconciliation, not silently dropped
        assert any("UNATTRIBUTED_FILL" in str(e.payload) for e in audit.events)


def test_poll_fills_dicts_carry_attribution_and_stable_ids():
    with tempfile.TemporaryDirectory() as td:
        _tmp = Path(td)
        mock = _mock_mt5()
        broker = MT5Adapter(mt5_module=mock)
        cid = "attribution-check-0001"
        comment = broker._build_comment(cid)  # persists mapping
        mock.history_deals_get.return_value = [_deal(4001, comment, volume=0.01)]
        raw = broker.poll_fills("")
        assert len(raw) == 1
        item = raw[0]
        assert item["client_order_id"] == cid
        assert item["fill_id"] == "mt5-deal-4001"
        # stable across polls
        raw2 = broker.poll_fills("")
        assert raw2[0]["fill_id"] == item["fill_id"]
