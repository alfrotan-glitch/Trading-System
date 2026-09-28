"""MT5 order-comment compatibility contract (real Windows failure regression).

Evidence: the first real DEMO submission (journal_id=1,
client_order_id ``demo-20260928T140630-884971d1e6``, WMMarkets-Demo) was
refused BEFORE reaching the broker: ``mt5.order_send`` returned ``None`` with
``last_error() == (-2, 'Invalid "comment" argument')``. The engine correctly
failed closed (state AMBIGUOUS, durable suspend), but the order could never
succeed while QTS sent that comment.

Root cause, pinned here:

* ``new_client_order_id`` produces a 31-char id, and the old ``_build_comment``
  sent any id of <= 31 chars VERBATIM as the MT5 comment.
* The MetaTrader5 Python library rejects comments well below the documented
  31-char ceiling (empirically around 29-30 chars -> ``(-2, 'Invalid
  "comment" argument')``), and some brokers retain only the first 16 chars.
* The pre-trade dry-run (``mt5_order_check``) validated volume/price/margin
  but never the comment field, so the gate passed while ``order_send`` failed.

Fixed behavior pinned here:

1. every generated comment is deterministic, printable ASCII, and at most
   ``MT5_COMMENT_MAX`` (16) chars — below every observed limit;
2. the full client_order_id <-> comment mapping stays persisted, so restart
   recovery and fill attribution are unchanged;
3. the dry-run validates the same comment the real send would use;
4. close markers are normalized by the same constraint.

No risk limit, gate, authorization, stage permission, or LIVE lock is touched
by this fix — only the comment string that MT5 refused.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from qts.adapters.mt5_adapter import (
    MT5_COMMENT_MAX,
    MT5Adapter,
    mt5_comment_for,
    mt5_safe_comment_text,
)

FAILED_CLIENT_ORDER_ID = "demo-20260928T140630-884971d1e6"  # journal_id=1


def _mock_mt5():
    """Minimal terminal mock — same shape as other adapter regression tests."""
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
    info.trade_stops_level = 0
    info.trade_freeze_level = 0
    m.symbol_info.return_value = info
    m.symbol_select.return_value = True
    m.last_error.return_value = (1, "ok")
    tick = MagicMock()
    tick.bid = 3700.0
    tick.ask = 3700.5
    tick.time = datetime.now(UTC).timestamp()
    m.symbol_info_tick.return_value = tick
    return m


def _adapter(tmp_path: Path) -> MT5Adapter:
    return MT5Adapter(mt5_module=_mock_mt5(), db_path=tmp_path / "qts.db")


# --------------------------------------------------------------- the contract


def test_max_length_stays_below_every_observed_limit():
    # Library rejects around 29-30 chars; the observed broker retains 16.
    # If this constant ever grows, the real-terminal evidence must grow first.
    assert MT5_COMMENT_MAX <= 16


def test_real_failed_id_now_produces_an_mt5_safe_comment():
    assert len(FAILED_CLIENT_ORDER_ID) == 31  # the value that was refused
    comment = mt5_comment_for(FAILED_CLIENT_ORDER_ID)
    assert comment != FAILED_CLIENT_ORDER_ID  # never sent verbatim again
    assert 0 < len(comment) <= MT5_COMMENT_MAX
    assert comment.isascii()
    assert comment.isprintable()
    assert " " not in comment


def test_comment_is_deterministic_across_calls_and_adapters(tmp_path: Path):
    a = mt5_comment_for(FAILED_CLIENT_ORDER_ID)
    b = mt5_comment_for(FAILED_CLIENT_ORDER_ID)
    assert a == b
    adapter = _adapter(tmp_path)
    assert adapter._build_comment(FAILED_CLIENT_ORDER_ID) == a


def test_generated_demo_ids_are_unique_and_recoverable(tmp_path: Path):
    adapter = _adapter(tmp_path)
    ids = [f"demo-20260928T140630-{uuid.uuid4().hex[:10]}" for _ in range(200)]
    comments = [mt5_comment_for(cid) for cid in ids]
    assert len(set(comments)) == len(ids), "comment collision among live ids"
    for cid in ids:
        assert adapter._build_comment(cid) == mt5_comment_for(cid)
        # persisted mapping survives: forward and reverse lookup both work
        assert adapter._load_comment_map(cid) == mt5_comment_for(cid)
        assert adapter._reverse_comment_map(mt5_comment_for(cid)) == cid


def test_build_broker_request_sends_only_the_safe_comment(tmp_path: Path):
    from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Side

    adapter = _adapter(tmp_path)
    intent = OrderIntent(
        instrument=Instrument(symbol="XAUUSD", venue="MT5"),
        side=Side.BUY,
        quantity=Decimal("0.01"),
        order_type=OrderType.MARKET,
        client_order_id=FAILED_CLIENT_ORDER_ID,
        strategy_id="s",
    )
    request = adapter.build_broker_request(intent)
    comment = request["comment"]
    assert comment == mt5_comment_for(FAILED_CLIENT_ORDER_ID)
    assert len(comment) <= MT5_COMMENT_MAX
    assert comment.isascii()


def test_dry_run_validates_the_same_comment_the_send_uses(tmp_path: Path, monkeypatch):
    from qts.adapters import order_check as oc
    from qts.domain.value_objects import Instrument, OrderIntent, OrderType, Side

    adapter = _adapter(tmp_path)
    intent = OrderIntent(
        instrument=Instrument(symbol="XAUUSD", venue="MT5"),
        side=Side.BUY,
        quantity=Decimal("0.01"),
        order_type=OrderType.MARKET,
        client_order_id=FAILED_CLIENT_ORDER_ID,
        strategy_id="s",
    )
    account = MagicMock()
    account.leverage = Decimal("100")
    account.free_margin = Decimal("10000")
    adapter.account = MagicMock(return_value=account)

    ok = oc.mt5_order_check(adapter, intent, market_price=Decimal("3700.5"))
    assert ok.ok is True, ok.comment  # a safe comment passes the dry-run

    # If the comment builder could ever produce an invalid value, the dry-run
    # must fail closed instead of waving the order through to order_send.
    def _broken(_cid: str) -> str:
        raise ValueError("simulated invalid comment")

    monkeypatch.setattr("qts.adapters.mt5_adapter.mt5_comment_for", _broken)
    refused = oc.mt5_order_check(adapter, intent, market_price=Decimal("3700.5"))
    assert refused.ok is False
    assert "invalid comment" in refused.comment


def test_close_marker_is_normalized_by_the_same_constraint():
    assert mt5_safe_comment_text("qts-close") == "qts-close"
    long = mt5_safe_comment_text("operator wrote a very long close reason " * 3)
    assert 0 < len(long) <= MT5_COMMENT_MAX
    assert long.isascii()
    # non-ASCII is dropped, never sent
    assert mt5_safe_comment_text("ปิดตำแหน่ง") == ""
    assert mt5_safe_comment_text("") == ""


def test_close_request_never_carries_an_oversized_comment(tmp_path: Path):
    adapter = _adapter(tmp_path)
    mt5 = adapter._mt5
    position = MagicMock()
    position.symbol = "XAUUSD"
    position.volume = 0.01
    position.type = 0
    mt5.positions_get.return_value = [position]
    result = MagicMock()
    result.retcode = 10009
    result.order = 1
    result.deal = 2
    mt5.order_send.return_value = result

    adapter.close_position(12345, volume=Decimal("0.01"), comment="X" * 500)
    sent = mt5.order_send.call_args.args[0]
    assert len(sent["comment"]) <= MT5_COMMENT_MAX
    assert sent["comment"].isascii()
    assert sent["comment"] == "X" * MT5_COMMENT_MAX
