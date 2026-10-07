from decimal import Decimal
from types import SimpleNamespace

from qts.adapters.mt5_adapter import MT5Adapter


class _MT5:
    def __init__(self):
        self.calls = []

    def history_deals_get(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("position") != 77:
            return []
        return [
            SimpleNamespace(
                position_id=77,
                profit=Decimal("2.50"),
                commission=Decimal("-0.20"),
                swap=Decimal("-0.05"),
                fee=Decimal("-0.03"),
                ticket=1001,
                comment="close-comment",
            ),
            SimpleNamespace(
                position_id=77,
                profit=Decimal("0.00"),
                commission=Decimal("-0.10"),
                swap=Decimal("0.00"),
                fee=Decimal("0.00"),
                ticket=1002,
                comment="older-entry",
            ),
        ]


def test_position_realized_result_uses_position_filtered_history():
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
    assert fake.calls == [{"position": 77}]
