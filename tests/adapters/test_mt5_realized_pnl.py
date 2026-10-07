from datetime import UTC, datetime
from types import SimpleNamespace
from decimal import Decimal

from qts.adapters.mt5_adapter import MT5Adapter


class _MT5:
    def __init__(self):
        self.calls = []

    def history_deals_get(self, start, end):
        self.calls.append((start, end))
        if (end - start).days <= 31:
            return []
        return [
            SimpleNamespace(position_id=77, profit=Decimal("2.50"), commission=Decimal("-0.20"), swap=Decimal("-0.05"), fee=Decimal("-0.03"), ticket=1001),
            SimpleNamespace(position_id=77, profit=Decimal("0.00"), commission=Decimal("-0.10"), swap=Decimal("0.00"), fee=Decimal("0.00"), ticket=1002),
        ]


def test_position_realized_result_falls_back_to_full_history_for_old_position(monkeypatch):
    adapter = object.__new__(MT5Adapter)
    fake = _MT5()
    adapter._mt5 = fake
    result = adapter.position_realized_result(77)

    assert result["deal_count"] == 2
    assert result["profit"] == Decimal("2.50")
    assert result["commission"] == Decimal("-0.30")
    assert result["swap"] == Decimal("-0.05")
    assert result["fee"] == Decimal("-0.03")
    assert result["net_realized_pnl"] == Decimal("2.12")
    assert len(fake.calls) == 2
    assert fake.calls[1][0] == datetime(1970, 1, 1, tzinfo=UTC)
