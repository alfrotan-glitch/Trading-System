"""Read-only MT5 historical capability probe contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts.probe_mt5_history import probe_mt5_history


class FakeMT5:
    COPY_TICKS_ALL = 7
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, *, with_history: bool = True, with_bid_ask: bool = True) -> None:
        self.with_history = with_history
        self.with_bid_ask = with_bid_ask
        self.order_send_calls = 0
        self.selected: list[str] = []

    def last_error(self):
        return (1, "ok")

    def account_info(self):
        return SimpleNamespace(trade_mode=0, server="WMMarkets-Demo")

    def terminal_info(self):
        return SimpleNamespace(build=5000, community_account=False)

    def symbol_info(self, symbol: str):
        if symbol != "XAUUSD@":
            return None
        return SimpleNamespace(
            name=symbol,
            visible=True,
            path="Metals\\XAUUSD@",
            digits=2,
            point=0.01,
            trade_mode=4,
            currency_base="XAU",
            currency_profit="USD",
        )

    def symbol_select(self, symbol: str, selected: bool):
        if selected:
            self.selected.append(symbol)
        return True

    def symbols_get(self):
        return [SimpleNamespace(name="XAUUSD@")]

    def copy_ticks_range(self, symbol, start, end, flags):
        if not self.with_history:
            return None
        base = int((end - timedelta(minutes=2)).timestamp() * 1000)
        if self.with_bid_ask:
            return [
                {"time": base // 1000, "time_msc": base, "bid": 2000.0, "ask": 2000.5, "flags": 1},
                {"time": (base + 1000) // 1000, "time_msc": base + 1000, "bid": 2000.1, "ask": 2000.6, "flags": 1},
            ]
        return [{"time": base // 1000, "time_msc": base, "last": 2000.0, "flags": 1}]

    def order_send(self, *args, **kwargs):  # pragma: no cover - sentinel only
        self.order_send_calls += 1
        raise AssertionError("probe must never submit orders")


def test_probe_reports_bid_ask_fields_without_orders() -> None:
    fake = FakeMT5()
    report = probe_mt5_history(
        fake,
        symbol="XAUUSD@",
        windows_days=[1, 7],
        end_utc=datetime(2026, 9, 19, tzinfo=UTC),
    )
    assert report["read_only"] is True
    assert report["orders_submitted"] == 0
    assert report["order_send_called"] is False
    assert report["account"]["is_demo"] is True
    assert report["symbol"]["actual_symbol"] == "XAUUSD@"
    assert report["capability"]["status"] == "RESPONSE_RECEIVED"
    assert report["capability"]["bid_ask_status"] == "PRESENT"
    assert len(report["windows"]) == 2
    assert all(window["raw_rows_sha256"] for window in report["windows"])
    assert fake.order_send_calls == 0


def test_probe_does_not_infer_bid_ask_from_rows_without_fields() -> None:
    report = probe_mt5_history(
        FakeMT5(with_bid_ask=False),
        symbol="XAUUSD@",
        windows_days=[1],
        end_utc=datetime(2026, 9, 19, tzinfo=UTC),
    )
    assert report["capability"]["status"] == "RESPONSE_RECEIVED"
    assert report["capability"]["bid_ask_status"] == "ABSENT_OR_UNAVAILABLE"
    assert report["windows"][0]["status"] == "RESPONSE_RECEIVED_BID_ASK_ABSENT"


def test_probe_reports_no_response_without_promoting_candles() -> None:
    report = probe_mt5_history(
        FakeMT5(with_history=False),
        symbol="XAUUSD@",
        windows_days=[1],
        end_utc=datetime(2026, 9, 19, tzinfo=UTC),
    )
    assert report["capability"]["status"] == "NO_TICK_RESPONSE"
    assert report["capability"]["bid_ask_status"] == "ABSENT_OR_UNAVAILABLE"
    assert report["windows"][0]["status"] == "NO_RESPONSE"


def test_probe_reports_unknown_symbol_and_does_not_query_history() -> None:
    fake = FakeMT5()
    report = probe_mt5_history(fake, symbol="XAUUSD", windows_days=[1])
    assert report["capability"]["status"] == "SYMBOL_UNAVAILABLE"
    assert report["windows"] == []
    assert report["symbol"]["candidates"] == ["XAUUSD@"]
