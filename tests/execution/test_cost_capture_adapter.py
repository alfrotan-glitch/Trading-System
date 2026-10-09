"""The adapter must actually expose the broker's charges, not just the fill price.

Before this, ``last_submission`` carried ids and an executed price while the
commission, swap and fee — fetched from the terminal and then discarded — were
unrecoverable. These tests pin the new fields, and pin that failure to read
them degrades to "unavailable" rather than to "zero cost".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qts.adapters.mt5_adapter import MT5Adapter


def deal_row(**overrides: object) -> SimpleNamespace:
    row = SimpleNamespace(
        ticket=1001,
        order=501,
        position_id=77,
        symbol="XAUUSD@",
        type=0,
        entry=0,
        volume=0.01,
        price=4000.50,
        profit=0.0,
        commission=-0.70,
        swap=0.0,
        fee=-0.10,
        time=1_760_000_000,
        time_msc=1_760_000_000_000,
        comment="qts-abc",
        magic=20250916,
        reason=3,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class _MT5:
    def __init__(self, *, rows=None, currency="USD", tick=True) -> None:
        self._rows = rows if rows is not None else []
        self._currency = currency
        self._tick = tick
        self.deal_queries: list[dict[str, object]] = []

    def history_deals_get(self, **kwargs):
        self.deal_queries.append(dict(kwargs))
        return list(self._rows)

    def account_info(self):
        return SimpleNamespace(currency=self._currency)

    def symbol_info_tick(self, symbol):
        if not self._tick:
            return None
        return SimpleNamespace(bid=4000.00, ask=4000.30, spread=30)

    def symbol_info(self, symbol):
        return SimpleNamespace(point=0.01, digits=2)

    def last_error(self):
        return (1, "ok")


class _Empty:
    """A terminal that has nothing to say: no rows and no account info."""

    def history_deals_get(self, **kwargs):
        return None

    def account_info(self):
        return None

    def symbol_info_tick(self, symbol):
        return None

    def symbol_info(self, symbol):
        return None


# --------------------------------------------------------------------------- #
# deal row freezing
# --------------------------------------------------------------------------- #


def test_deal_rows_are_frozen_with_every_cost_field_intact() -> None:
    adapter = MT5Adapter(mt5_module=_MT5())
    rows = adapter._deal_rows_as_dicts([deal_row()])
    assert len(rows) == 1
    row = rows[0]
    assert row["commission"] == -0.70
    assert row["swap"] == 0.0
    assert row["fee"] == -0.10
    assert row["profit"] == 0.0
    assert row["volume"] == 0.01
    assert row["price"] == 4000.50
    assert row["ticket"] == 1001
    assert row["position_id"] == 77


def test_a_deal_row_missing_a_field_stays_missing() -> None:
    """Absence must survive freezing — defaulting it to 0 would fabricate a fact."""
    row = deal_row()
    del row.commission
    rows = MT5Adapter._deal_rows_as_dicts([row])
    assert "commission" not in rows[0]
    assert rows[0]["swap"] == 0.0  # a real zero is preserved as zero


def test_a_none_deal_stream_is_an_empty_list_not_an_error() -> None:
    adapter = MT5Adapter(mt5_module=_MT5())
    assert adapter._deal_rows_as_dicts(None) == []
    assert adapter._deal_rows_as_dicts([]) == []


# --------------------------------------------------------------------------- #
# quote snapshot
# --------------------------------------------------------------------------- #


def test_quote_snapshot_records_the_pre_trade_spread() -> None:
    snapshot = MT5Adapter._quote_snapshot(_MT5(), "XAUUSD@")
    assert snapshot["unavailable"] is False
    assert snapshot["bid"] == "4000.0"
    assert snapshot["ask"] == "4000.3"
    assert snapshot["spread_points"] == "30"
    assert snapshot["observed_at"]


def test_quote_snapshot_derives_spread_when_the_terminal_does_not_report_it() -> None:
    class _NoSpreadField(_MT5):
        def symbol_info_tick(self, symbol):
            return SimpleNamespace(bid=4000.00, ask=4000.30)  # no .spread

    snapshot = MT5Adapter._quote_snapshot(_NoSpreadField(), "XAUUSD@")
    assert snapshot["spread_points"] == "30"


def test_quote_snapshot_is_unavailable_when_the_terminal_has_no_quote() -> None:
    snapshot = MT5Adapter._quote_snapshot(_MT5(tick=False), "XAUUSD@")
    assert snapshot["unavailable"] is True
    assert snapshot["bid"] is None
    assert snapshot["ask"] is None
    # The critical part: no spread is recorded, rather than a spread of zero.
    assert snapshot["spread_points"] is None


def test_quote_snapshot_survives_a_failing_terminal() -> None:
    class _Boom:
        def symbol_info_tick(self, symbol):
            raise RuntimeError("terminal gone")

        def symbol_info(self, symbol):
            raise RuntimeError("terminal gone")

    snapshot = MT5Adapter._quote_snapshot(_Boom(), "XAUUSD@")
    assert snapshot["unavailable"] is True


def test_a_missing_module_snapshot_is_unavailable() -> None:
    assert MT5Adapter._quote_snapshot(None, "XAUUSD@")["unavailable"] is True


# --------------------------------------------------------------------------- #
# account currency
# --------------------------------------------------------------------------- #


def test_account_currency_is_reported_when_known() -> None:
    assert MT5Adapter._account_currency(_MT5(currency="EUR")) == "EUR"


def test_account_currency_is_none_when_unknown_not_usd() -> None:
    """MT5 reports in the deposit currency; assuming USD is a silent conversion."""
    assert MT5Adapter._account_currency(_Empty()) is None
    assert MT5Adapter._account_currency(None) is None


def test_account_currency_survives_a_failing_terminal() -> None:
    class _Boom:
        def account_info(self):
            raise RuntimeError("terminal gone")

    assert MT5Adapter._account_currency(_Boom()) is None


# --------------------------------------------------------------------------- #
# close-path attribution
# --------------------------------------------------------------------------- #


def test_closing_deals_are_attributed_to_the_close_order() -> None:
    fake = _MT5(rows=[deal_row(order=999), deal_row(order=501)])
    adapter = MT5Adapter(mt5_module=fake)
    rows = adapter._deals_for_order(fake, 501)
    assert len(rows) == 1
    assert rows[0].order == 501


def test_unreadable_closing_deals_are_empty_not_fatal() -> None:
    """A succeeded close must not fail because its charges cannot be read."""
    adapter = MT5Adapter(mt5_module=_Empty())
    assert adapter._deals_for_order(adapter._mt5, 0) == []
    assert adapter._deals_for_order(None, 501) == []


def test_a_failing_deal_lookup_returns_nothing() -> None:
    class _Boom:
        def history_deals_get(self, **kwargs):
            raise RuntimeError("terminal gone")

    adapter = MT5Adapter(mt5_module=_Boom())
    assert adapter._deals_for_order(adapter._mt5, 501) == []


@pytest.mark.parametrize("rows", [[], [deal_row()]])
def test_rows_always_serialise_to_plain_dicts(rows: list[object]) -> None:
    """Numpy rows are views over terminal memory; only dicts survive a reconnect."""
    out = MT5Adapter._deal_rows_as_dicts(rows)
    assert all(isinstance(row, dict) for row in out)
