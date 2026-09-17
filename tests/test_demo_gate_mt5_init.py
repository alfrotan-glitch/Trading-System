"""Proof: the DEMO readiness gate must establish the MT5 IPC link itself.

Root cause (verified on the user's Windows 10 / Python 3.13.15 machine):
a direct CLI test succeeds because it calls ``mt5.initialize(path=...)`` in
the same process before ``terminal_info()``; the QTS Setup Wizard path
(``/api/demo/readiness`` -> ``demo_forward_readiness_report``) imported
MetaTrader5 but NEVER called ``initialize()``, so every MT5 data function
returned None in the server process even though the terminal was connected
and the account was DEMO. The wizard's terminal-path and symbol inputs were
also inert (never sent to the backend), and the gate hardcoded "XAUUSD"
(the broker's real symbol is "XAUUSD@").

These tests pin the fix without touching any safety gate:
- initialize() is called with the configured path (param > QTS_MT5_PATH > MT5_PATH)
- initialize failure is fail-closed (blocked, demo_enabled False, last_error surfaced)
- broker symbol resolution (param > QTS_MT5_SYMBOL > symbol_map/QTS_MT5_SYMBOL_MAP)
  and symbol_select before symbol_info
- mocks without initialize() keep working (backward compatible)
- a LIVE account fed to DEMO mode is still blocked even when initialize succeeds
- the API forwards terminal_path/symbol query params
"""

from __future__ import annotations

import time
from typing import Any

from qts.lifecycle.demo_gate import demo_forward_readiness_report

TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"


class _SI:
    contract_size = 100
    volume_min = 0.01
    volume_max = 100
    volume_step = 0.01
    digits = 2
    point = 0.01
    trade_allowed = True
    trade_mode = 4


class _Tick:
    bid = 2000.0
    ask = 2000.5

    def __init__(self) -> None:
        self.time = time.time()


class _AccountDemo:
    login = 123
    server = "WMMarkets-Demo"
    company = "WMMarkets"
    balance = 10000
    margin = 0
    trade_mode = 0


class FakeMT5:
    """Records every lifecycle-relevant call; serves only the broker symbol."""

    def __init__(self, *, init_ok: bool = True, broker_symbols: tuple[str, ...] = ("XAUUSD",)) -> None:
        self.init_calls: list[dict[str, Any]] = []
        self.init_ok = init_ok
        self.broker_symbols = broker_symbols
        self.selected: list[tuple[str, bool]] = []
        self.symbol_info_calls: list[str] = []
        self.tick_calls: list[str] = []

    def initialize(self, **kwargs: Any) -> bool:
        self.init_calls.append(kwargs)
        return self.init_ok

    def last_error(self) -> tuple[int, str]:
        return (-10003, "IPC timeout")

    def terminal_info(self) -> Any:
        return object() if self.init_ok else None

    def account_info(self) -> Any:
        return _AccountDemo() if self.init_ok else None

    def symbol_select(self, sym: str, flag: bool) -> bool:
        self.selected.append((sym, flag))
        return True

    def symbol_info(self, sym: str) -> Any:
        self.symbol_info_calls.append(sym)
        return _SI() if sym in self.broker_symbols else None

    def symbol_info_tick(self, sym: str) -> Any:
        self.tick_calls.append(sym)
        return _Tick() if sym in self.broker_symbols else None


def test_initialize_called_with_explicit_terminal_path():
    fake = FakeMT5()
    rpt = demo_forward_readiness_report(mt5_module=fake, terminal_path=TERMINAL_PATH)
    assert fake.init_calls == [{"path": TERMINAL_PATH}]
    assert rpt["checks"]["terminal_running"] is True
    assert "initialize(path=configured)=True" in rpt["details"]["terminal_running"]


def test_initialize_path_from_env(monkeypatch):
    monkeypatch.setenv("QTS_MT5_PATH", TERMINAL_PATH)
    monkeypatch.delenv("MT5_PATH", raising=False)
    fake = FakeMT5()
    demo_forward_readiness_report(mt5_module=fake)
    assert fake.init_calls == [{"path": TERMINAL_PATH}]

    # MT5_PATH is the documented fallback
    monkeypatch.delenv("QTS_MT5_PATH", raising=False)
    monkeypatch.setenv("MT5_PATH", TERMINAL_PATH)
    fake2 = FakeMT5()
    demo_forward_readiness_report(mt5_module=fake2)
    assert fake2.init_calls == [{"path": TERMINAL_PATH}]


def test_initialize_without_path_uses_auto_discovery(monkeypatch):
    monkeypatch.delenv("QTS_MT5_PATH", raising=False)
    monkeypatch.delenv("MT5_PATH", raising=False)
    fake = FakeMT5()
    rpt = demo_forward_readiness_report(mt5_module=fake)
    assert fake.init_calls == [{}]  # initialize() still called, path auto-detected
    assert "initialize(path=auto)=True" in rpt["details"]["terminal_running"]


def test_initialize_failure_is_fail_closed():
    fake = FakeMT5(init_ok=False)
    rpt = demo_forward_readiness_report(mt5_module=fake, terminal_path=TERMINAL_PATH)
    assert rpt["passed"] is False
    assert rpt["demo_enabled"] is False
    assert any("initialize failed" in b for b in rpt["blocked_reasons"])
    assert "last_error=(-10003, 'IPC timeout')" in rpt["details"]["terminal_running"]
    assert rpt["checks"]["terminal_running"] is False
    assert rpt["checks"]["account_connected"] is False


def test_broker_symbol_resolution_env_and_map(monkeypatch):
    # Broker only serves XAUUSD@ — the previously hardcoded XAUUSD would fail.
    fake = FakeMT5(broker_symbols=("XAUUSD@",))
    monkeypatch.delenv("QTS_MT5_SYMBOL", raising=False)
    monkeypatch.setenv("QTS_MT5_SYMBOL_MAP", "XAUUSD=XAUUSD@")
    rpt = demo_forward_readiness_report(mt5_module=fake, terminal_path=TERMINAL_PATH)
    assert fake.symbol_info_calls == ["XAUUSD@"]
    assert fake.tick_calls == ["XAUUSD@"]
    assert ("XAUUSD@", True) in fake.selected  # Market Watch select before info
    assert rpt["checks"]["symbol_available"] is True
    assert "(broker XAUUSD@)" in rpt["details"]["symbol_available"]

    # Explicit symbol param wins over env default
    fake2 = FakeMT5(broker_symbols=("XAUUSD@",))
    rpt2 = demo_forward_readiness_report(mt5_module=fake2, symbol="XAUUSD@", terminal_path=TERMINAL_PATH)
    assert fake2.symbol_info_calls == ["XAUUSD@"]
    assert rpt2["checks"]["symbol_available"] is True

    # QTS_MT5_SYMBOL env alone
    fake3 = FakeMT5(broker_symbols=("XAUUSD@",))
    monkeypatch.setenv("QTS_MT5_SYMBOL", "XAUUSD@")
    rpt3 = demo_forward_readiness_report(mt5_module=fake3, terminal_path=TERMINAL_PATH)
    assert fake3.symbol_info_calls == ["XAUUSD@"]
    assert rpt3["checks"]["symbol_available"] is True


def test_mocks_without_initialize_still_work():
    """Backward compatibility: injected mocks lacking initialize() are not broken."""

    class LegacyMock:
        def terminal_info(self):
            return object()

        def account_info(self):
            return _AccountDemo()

        def symbol_info(self, sym):
            return _SI()

        def symbol_info_tick(self, sym):
            return _Tick()

    rpt = demo_forward_readiness_report(mt5_module=LegacyMock())
    assert rpt["checks"]["terminal_running"] is True
    assert len(rpt["required_checks"]) == 14  # contract unchanged
    assert "initialize" not in rpt["details"]["terminal_running"]


def test_live_account_still_blocked_when_initialize_succeeds():
    """Safety gate intact: the new initialize step never weakens the DEMO-only boundary."""

    class _AccountLive:
        login = 999
        server = "WMMarkets-Live"
        company = "WMMarkets"
        balance = 10000
        margin = 0
        trade_mode = 2

    class LiveFake(FakeMT5):
        def account_info(self):
            return _AccountLive()

    fake = LiveFake(broker_symbols=("XAUUSD",))
    rpt = demo_forward_readiness_report(mt5_module=fake, terminal_path=TERMINAL_PATH)
    assert rpt["checks"]["account_is_demo"] is False
    assert rpt["warn_live_in_demo"] is True
    assert any("LIVE account" in b for b in rpt["blocked_reasons"])
    assert rpt["passed"] is False
    assert rpt["demo_enabled"] is False


def test_api_forwards_terminal_path_and_symbol(monkeypatch):
    from fastapi.testclient import TestClient

    import qts.lifecycle.demo_gate as dg
    from qts.api.server import app

    captured: dict[str, Any] = {}

    def fake_report(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"passed": False, "demo_enabled": False, "blocked_reasons": [], "checks": {}}

    monkeypatch.setattr(dg, "demo_forward_readiness_report", fake_report)
    client = TestClient(app)
    r = client.get("/api/demo/readiness", params={"terminal_path": TERMINAL_PATH, "symbol": "XAUUSD@"})
    assert r.status_code == 200
    assert captured["terminal_path"] == TERMINAL_PATH
    assert captured["symbol"] == "XAUUSD@"

    captured.clear()
    r2 = client.get("/api/demo/readiness")
    assert r2.status_code == 200
    assert captured["terminal_path"] is None
    assert captured["symbol"] is None
