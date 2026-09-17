"""MT5 SymbolInfo contract-size field mapping regression (real Windows evidence).

Verified on the user's Windows 10 machine (MetaTrader5 5.0.6180, server
WMMarkets-Demo, symbol XAUUSD@):

    trade_contract_size = 100.0
    contract_size       = None   (the attribute does not exist on SymbolInfo)
    volume_min = 0.01, volume_step = 0.01, digits = 2, point = 0.01

The real MetaTrader5 API exposes the contract size as ``trade_contract_size``;
QTS canonicalizes it as ``contract_size`` (SymbolSpec, Instrument, risk and
portfolio math). Two places broke on that boundary:

1. demo_gate check 8 required ``hasattr(si, "contract_size")`` on the RAW
   SymbolInfo -> symbol_spec_valid=False, missing ['contract_size'] even
   though the broker spec is perfectly valid.
2. MT5Adapter.get_symbol_spec read ``getattr(info, "contract_size", 100)`` —
   wrong field for real MT5 AND a fabricated default: every real symbol got
   contract_size=100 regardless of the broker's actual value, feeding
   notional/margin/risk math with an unaudited number.

Fix contract pinned here: alias mapping (trade_contract_size -> canonical
contract_size), None counted as missing, NO default ever invented
(fail-closed RuntimeError), and existing mocks/contracts stay compatible.
"""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from qts.adapters.mt5_adapter import MT5Adapter
from qts.lifecycle.demo_gate import demo_forward_readiness_report


class RealisticSymbolInfo:
    """Mirrors MetaTrader5 5.0.6180 SymbolInfo('XAUUSD@') on WMMarkets-Demo.

    There is deliberately NO ``contract_size`` attribute — getattr must fall
    through to ``trade_contract_size``.
    """

    trade_contract_size = 100.0
    volume_min = 0.01
    volume_max = 500.0
    volume_step = 0.01
    digits = 2
    point = 0.01
    trade_tick_size = 0.01
    trade_mode = 4  # SYMBOL_TRADE_MODE_FULL — the authoritative tradability signal
    trade_allowed = True
    filling_mode = 1
    trade_exemode = 2  # SYMBOL_TRADE_EXECUTION_MARKET (WMMarkets-Demo)
    trade_stops_level = 0
    trade_freeze_level = 0


class RealisticSymbolInfoExplicitNone(RealisticSymbolInfo):
    """Variant where ``contract_size`` exists but is None (as the user's
    getattr dump showed) — None must never be mistaken for a value."""

    contract_size = None


class NoContractSizeAnywhere(RealisticSymbolInfo):
    """Broken/absent contract size: trade_contract_size None, no alias."""

    trade_contract_size = None


class LegacyMockSymbolInfo:
    """Historical QTS mocks expose only ``contract_size`` — must keep working."""

    contract_size = 100
    volume_min = 0.01
    volume_max = 100
    volume_step = 0.01
    digits = 2
    point = 0.01
    trade_tick_size = 0.01
    trade_mode = 4
    trade_allowed = True
    filling_mode = 1
    trade_exemode = 0
    trade_stops_level = 0
    trade_freeze_level = 0


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
    """Minimal real-API-shaped module double for the readiness gate."""

    def __init__(self, symbol_info_obj: Any) -> None:
        self._si = symbol_info_obj
        self.symbol_info_calls: list[str] = []

    def initialize(self, **kwargs: Any) -> bool:
        return True

    def last_error(self) -> tuple[int, str]:
        return (1, "ok")

    def terminal_info(self) -> Any:
        return object()

    def account_info(self) -> Any:
        return _AccountDemo()

    def symbol_select(self, sym: str, flag: bool) -> bool:
        return True

    def symbol_info(self, sym: str) -> Any:
        self.symbol_info_calls.append(sym)
        return self._si

    def symbol_info_tick(self, sym: str) -> Any:
        return _Tick()


def _adapter(fake_module: Any, tmp_path: Path) -> MT5Adapter:
    return MT5Adapter(mt5_module=fake_module, db_path=tmp_path / "adapter.db")


# ---------------------------------------------------------------- gate side


def test_realistic_symbol_info_satisfies_symbol_spec_valid():
    rpt = demo_forward_readiness_report(mt5_module=FakeMT5(RealisticSymbolInfo()), symbol="XAUUSD@")
    assert rpt["checks"]["symbol_available"] is True
    assert rpt["checks"]["symbol_tradable"] is True
    assert rpt["checks"]["symbol_spec_valid"] is True
    assert not any("contract_size" in b for b in rpt["blocked_reasons"])


def test_explicit_none_contract_size_alias_still_valid_via_trade_contract_size():
    rpt = demo_forward_readiness_report(mt5_module=FakeMT5(RealisticSymbolInfoExplicitNone()), symbol="XAUUSD@")
    assert rpt["checks"]["symbol_spec_valid"] is True


def test_missing_contract_size_still_fails_closed_in_gate():
    rpt = demo_forward_readiness_report(mt5_module=FakeMT5(NoContractSizeAnywhere()), symbol="XAUUSD@")
    assert rpt["checks"]["symbol_spec_valid"] is False
    assert "contract_size" in rpt["details"]["symbol_spec_valid"]
    assert any("Symbol specification invalid" in b for b in rpt["blocked_reasons"])
    assert rpt["demo_enabled"] is False


def test_legacy_mock_symbol_info_remains_valid_in_gate():
    rpt = demo_forward_readiness_report(mt5_module=FakeMT5(LegacyMockSymbolInfo()))
    assert rpt["checks"]["symbol_spec_valid"] is True


# -------------------------------------------------------------- adapter side


def test_adapter_maps_trade_contract_size_to_canonical_contract_size(tmp_path: Path):
    adapter = _adapter(FakeMT5(RealisticSymbolInfo()), tmp_path)
    spec = adapter.get_symbol_spec("XAUUSD@")
    assert spec.contract_size == Decimal("100.0")
    assert spec.symbol == "XAUUSD@"
    assert spec.volume_min == Decimal("0.01")
    assert spec.digits == 2


def test_adapter_uses_trade_contract_size_when_alias_is_explicit_none(tmp_path: Path):
    adapter = _adapter(FakeMT5(RealisticSymbolInfoExplicitNone()), tmp_path)
    assert adapter.get_symbol_spec("XAUUSD@").contract_size == Decimal("100.0")


def test_adapter_never_invents_a_default_contract_size(tmp_path: Path):
    adapter = _adapter(FakeMT5(NoContractSizeAnywhere()), tmp_path)
    with pytest.raises(RuntimeError, match="refusing to fabricate broker metadata"):
        adapter.get_symbol_spec("XAUUSD@")
    # and the broken symbol is therefore not tradable (fail-closed, no raise)
    assert adapter.is_symbol_tradable("XAUUSD@") is False


def test_adapter_rejects_non_positive_contract_size(tmp_path: Path):
    class ZeroContract(RealisticSymbolInfo):
        trade_contract_size = 0.0

    adapter = _adapter(FakeMT5(ZeroContract()), tmp_path)
    with pytest.raises(RuntimeError, match="refusing to fabricate broker metadata"):
        adapter.get_symbol_spec("XAUUSD@")


def test_adapter_legacy_contract_size_mock_still_works(tmp_path: Path):
    adapter = _adapter(FakeMT5(LegacyMockSymbolInfo()), tmp_path)
    assert adapter.get_symbol_spec("XAUUSD").contract_size == Decimal("100")


def test_adapter_magicmock_with_contract_size_still_works(tmp_path: Path):
    """cli.py/live_gate.py inject MagicMocks with concrete contract_size=100.

    A MagicMock auto-creates ``trade_contract_size`` as a child mock; the
    resolver must skip non-numeric candidates instead of crashing or
    accepting the mock object as a size.
    """
    info = MagicMock(
        contract_size=100,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        digits=2,
        point=0.01,
        trade_tick_size=0.01,
        trade_mode=4,
        trade_allowed=True,
        filling_mode=1,
        execution_mode=0,
        trade_stops_level=0,
        trade_freeze_level=0,
    )
    fake = FakeMT5(info)
    adapter = _adapter(fake, tmp_path)
    assert adapter.get_symbol_spec("XAUUSD").contract_size == Decimal("100")


def test_adapter_bare_magicmock_fails_closed_instead_of_defaulting(tmp_path: Path):
    """A fully unspecified mock previously got a fabricated 100 — now it must
    fail closed rather than feed invented numbers into risk math."""
    adapter = _adapter(FakeMT5(MagicMock()), tmp_path)
    with pytest.raises(RuntimeError, match="refusing to fabricate broker metadata"):
        adapter.get_symbol_spec("XAUUSD")
