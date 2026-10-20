from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
from click.testing import CliRunner

from qts.cli.data import data


def _fake_mt5(*, demo: bool = True) -> ModuleType:
    module = ModuleType("MetaTrader5")
    module.ACCOUNT_TRADE_MODE_DEMO = 0
    module.TIMEFRAME_M15 = 15
    module._shutdown_called = False
    module._demo = demo
    module.initialize = lambda **kwargs: True
    module.shutdown = lambda: setattr(module, "_shutdown_called", True)
    module.last_error = lambda: (1, "ok")
    module.account_info = lambda: SimpleNamespace(
        trade_mode=0 if module._demo else 2,
        server="WMMarkets-Demo" if module._demo else "WMMarkets-Live",
    )
    module.symbol_info = lambda symbol: SimpleNamespace(name=symbol)
    module.symbol_select = lambda symbol, visible: True

    def copy_rates_from_pos(symbol, timeframe, start, count):
        times = pd.date_range("2020-01-01", periods=count, freq="15min", tz="UTC")
        rows = np.zeros(
            count,
            dtype=[
                ("time", "i8"),
                ("open", "f8"),
                ("high", "f8"),
                ("low", "f8"),
                ("close", "f8"),
                ("tick_volume", "i8"),
                ("spread", "i4"),
                ("real_volume", "i8"),
            ],
        )
        rows["time"] = times.astype("int64") // 10**9
        rows["open"] = 2000.0
        rows["high"] = 2001.0
        rows["low"] = 1999.0
        rows["close"] = 2000.5
        rows["tick_volume"] = 100
        rows["spread"] = 20
        rows["real_volume"] = 0
        return rows

    module.copy_rates_from_pos = copy_rates_from_pos
    return module


def test_mt5_bars_exports_real_ohlc_and_provenance(tmp_path, monkeypatch):
    module = _fake_mt5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    monkeypatch.setattr(
        "qts.config.wizard.load_setup",
        lambda: {
            "symbol": "XAUUSD",
            "symbol_map": {"XAUUSD": "XAUUSD@"},
            "terminal_path": None,
        },
    )
    csv_path = tmp_path / "xauusd.csv"
    report_path = tmp_path / "evidence.json"

    result = CliRunner().invoke(
        data,
        [
            "mt5-bars",
            "--symbol",
            "XAUUSD@",
            "--count",
            "500",
            "--out",
            str(csv_path),
            "--json-out",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(report_path.read_text(encoding="utf-8"))
    exported = pd.read_csv(csv_path)
    assert report["status"] == "COMPLETE"
    assert report["data_class"] == "REAL_BROKER_DEMO_OHLC"
    assert report["broker_symbol"] == "XAUUSD@"
    assert report["bars_exported"] == 500
    assert report["orders_submitted"] == 0
    assert report["order_apis_called"] == []
    assert {"timestamp", "time", "open", "high", "low", "close"}.issubset(exported.columns)
    assert module._shutdown_called is True


def test_mt5_bars_refuses_non_demo_account(tmp_path, monkeypatch):
    module = _fake_mt5(demo=False)
    monkeypatch.setitem(sys.modules, "MetaTrader5", module)
    monkeypatch.setattr(
        "qts.config.wizard.load_setup",
        lambda: {
            "symbol": "XAUUSD",
            "symbol_map": {"XAUUSD": "XAUUSD@"},
            "terminal_path": None,
        },
    )
    csv_path = tmp_path / "must_not_exist.csv"

    result = CliRunner().invoke(
        data,
        [
            "mt5-bars",
            "--symbol",
            "XAUUSD@",
            "--count",
            "500",
            "--out",
            str(csv_path),
            "--json-out",
            str(tmp_path / "evidence.json"),
        ],
    )

    assert result.exit_code != 0
    assert "DEMO-only acquisition" in result.output
    assert not csv_path.exists()
    assert module._shutdown_called is True
