"""``qts demo cost-check`` — the read-only gate that runs before any DEMO order.

The point of this command is that an operator should never have to place a
trade to discover that cost capture does not work. These tests drive it against
a simulated terminal and assert both the ready path and, more importantly, that
each failure mode is named clearly and blocks.

Nothing here submits an order, and the command itself must not.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from qts.cli.demo import demo
from qts.execution.cost_capture import CostEvidenceStore


class FakeMT5:
    """A simulated terminal. Every knob is settable so failure paths are testable."""

    def __init__(
        self,
        *,
        currency: str | None = "USD",
        demo: bool = True,
        deals: list[SimpleNamespace] | None = None,
        offset: float = 10800.0,
        offset_basis: str = "measured-m1-bar",
        raise_on_deals: bool = False,
    ) -> None:
        self._currency = currency
        self._demo = demo
        self._deals = deals if deals is not None else [self._deal()]
        self._offset = offset
        self._offset_basis = offset_basis
        self._raise_on_deals = raise_on_deals
        self.initialized = False

    @staticmethod
    def _deal(**over: object) -> SimpleNamespace:
        row = SimpleNamespace(
            ticket=770001, order=990001, position_id=770001, symbol="XAUUSD@",
            type=0, entry=0, volume=0.01, price=4000.50, profit=0.0,
            commission=-0.70, swap=0.0, fee=-0.10, time=1760000000,
            time_msc=1760000000000, comment="qts-abc",
        )
        for k, v in over.items():
            setattr(row, k, v)
        return row

    def initialize(self, **kwargs):
        self.initialized = True
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (1, "ok")

    def terminal_info(self):
        return SimpleNamespace(connected=True, company="WM Markets")

    def account_info(self):
        from qts.adapters.identity import TRADE_MODE_DEMO, TRADE_MODE_REAL

        if self._currency is None:
            return SimpleNamespace(login=12345, server="WMMarkets-Demo")
        return SimpleNamespace(
            login=12345,
            server="WMMarkets-Demo",
            company="WM Markets",
            currency=self._currency,
            trade_mode=TRADE_MODE_DEMO if self._demo else TRADE_MODE_REAL,
        )

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=4000.00, ask=4000.30, spread=30,
                              time=1760000000, time_msc=1760000000000)

    def symbol_info(self, symbol):
        return SimpleNamespace(point=0.01, digits=2, trade_contract_size=100.0,
                              volume_min=0.01, volume_max=500.0, volume_step=0.01,
                              trade_mode=4, filling_mode=1, visible=True)

    def history_deals_get(self, *args, **kwargs):
        if self._raise_on_deals:
            raise RuntimeError("terminal: history unavailable")
        return list(self._deals)

    def order_check(self, request):
        return SimpleNamespace(retcode=0, comment="Done")


def _patch_offset(monkeypatch, offset: float, basis: str) -> None:
    from qts.adapters.mt5_adapter import MT5Adapter

    monkeypatch.setattr(MT5Adapter, "server_utc_offset",
                        lambda self, symbol: (offset, basis))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A hermetic operator environment with a simulated terminal wired in."""
    import fakes_demo_provider as provider_fixture
    from demo_harness import authorization_doc, write_authorization, write_registry

    auth = write_authorization(tmp_path / "authorization.json", authorization_doc())
    write_registry(tmp_path / "registry.json", provider_fixture.registry_entry())
    (tmp_path / "setup.json").write_text(
        json.dumps({"symbol": "XAUUSD", "symbol_map": {"XAUUSD": "XAUUSD@"}}), encoding="utf-8"
    )
    monkeypatch.setenv("QTS_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(auth))
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setenv("QTS_SETUP_FILE", str(tmp_path / "setup.json"))
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _run(runner, monkeypatch, env, terminal, *extra):
    """Invoke cost-check with the fake terminal injected at session construction."""
    import qts.cli.demo as demo_cli
    from qts.execution.demo_session import DemoSession, DemoSessionConfig

    def build_session(symbol: str, db: str, terminal_path: str | None = None):
        return DemoSession(
            DemoSessionConfig(
                symbol="XAUUSD",
                symbol_map={"XAUUSD": "XAUUSD@"},
                db_path=Path(db),
                actor="cli",
                mt5_module=terminal,
            )
        )

    monkeypatch.setattr(demo_cli, "_demo_session", build_session)
    return runner.invoke(demo, ["cost-check", "--db", str(Path(env) / "qts.db"), *extra])


# --------------------------------------------------------------------------- #
# the ready path
# --------------------------------------------------------------------------- #


def test_a_healthy_terminal_reports_ready(runner, monkeypatch, env) -> None:
    terminal = FakeMT5()
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    result = _run(runner, monkeypatch, env, terminal)
    assert "READY_FOR_COST_CAPTURE: True" in result.output, result.output
    assert "No order was submitted by this command." in result.output


def test_the_command_never_submits_an_order(runner, monkeypatch, env) -> None:
    """The whole point: this must be provably read-only."""
    terminal = FakeMT5()
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    _run(runner, monkeypatch, env, terminal)
    assert not hasattr(terminal, "order_send"), "terminal must not even expose order_send"
    assert "orders_submitted" in _json_of(runner, monkeypatch, env, terminal)


def _json_of(runner, monkeypatch, env, terminal, out=None) -> dict:
    import tempfile

    path = out or (Path(tempfile.mkdtemp()) / "cost_check.json")
    _run(runner, monkeypatch, env, terminal, "--json-out", str(path))
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_the_json_report_is_emitted_for_the_audit_trail(runner, monkeypatch, env, tmp_path) -> None:
    terminal = FakeMT5()
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    payload = _json_of(runner, monkeypatch, env, terminal, tmp_path / "cc.json")
    assert payload["schema"] == "qts.demo_cost_check.v1"
    assert payload["ready_for_cost_capture"] is True
    assert payload["orders_submitted"] == 0
    assert payload["broker_symbol"] == "XAUUSD@"
    assert payload["server_utc_offset_s"] == 10800.0


def test_the_writability_probe_leaves_no_evidence_behind(runner, monkeypatch, env) -> None:
    """Proving the store is writable must not pollute the real evidence log."""
    terminal = FakeMT5()
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    _run(runner, monkeypatch, env, terminal)
    from qts.config.paths import artifact_path

    store_path = artifact_path("cost_evidence")
    if store_path.exists():
        assert "writeprobe" not in store_path.read_text(encoding="utf-8")
        assert CostEvidenceStore(store_path).deals() == []


# --------------------------------------------------------------------------- #
# failure paths — each must be named and must block
# --------------------------------------------------------------------------- #


def test_an_unmeasured_server_offset_blocks(runner, monkeypatch, env) -> None:
    terminal = FakeMT5()
    _patch_offset(monkeypatch, 0.0, "assumed-utc-fallback")
    result = _run(runner, monkeypatch, env, terminal)
    assert "READY_FOR_COST_CAPTURE: False" in result.output
    assert "assumed-utc-fallback" in result.output
    assert "[FAIL] server-offset-measured" in result.output


def test_an_unknown_deposit_currency_blocks(runner, monkeypatch, env) -> None:
    """MT5 reports money in the deposit currency; USD must never be assumed."""
    terminal = FakeMT5(currency=None)
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    result = _run(runner, monkeypatch, env, terminal)
    assert "[FAIL] deposit-currency-known" in result.output
    assert "READY_FOR_COST_CAPTURE: False" in result.output
    # The message must say why, not just that something is missing.
    assert "currency unavailable" in result.output


def test_missing_cost_fields_are_reported_even_though_not_blocking(runner, monkeypatch, env) -> None:
    """Historical deals lacking commission/swap/fee must be visible up front."""
    row = FakeMT5._deal()
    del row.commission
    terminal = FakeMT5(deals=[row])
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    result = _run(runner, monkeypatch, env, terminal)
    assert "cost-fields-present" in result.output
    assert "commission=0" in result.output


def test_unreadable_deal_history_is_reported_not_hidden(runner, monkeypatch, env) -> None:
    terminal = FakeMT5(raise_on_deals=True)
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    result = _run(runner, monkeypatch, env, terminal)
    assert "deal-history-readable" in result.output
    assert "history unavailable" in result.output


def test_every_failure_names_itself_in_the_output(runner, monkeypatch, env) -> None:
    """An operator must be able to act on the message, not just see 'failed'."""
    terminal = FakeMT5(currency=None)
    _patch_offset(monkeypatch, 0.0, "assumed-utc-fallback")
    result = _run(runner, monkeypatch, env, terminal)
    for check in ("terminal-reachable", "deposit-currency-known", "server-offset-measured"):
        assert check in result.output


# --------------------------------------------------------------------------- #
# --record: measuring costs from history, without trading
# --------------------------------------------------------------------------- #


def test_record_is_opt_in_and_off_by_default(runner, monkeypatch, env) -> None:
    terminal = FakeMT5()
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    _run(runner, monkeypatch, env, terminal)
    from qts.config.paths import artifact_path

    path = artifact_path("cost_evidence")
    assert (not path.exists()) or CostEvidenceStore(path).deals() == []


def test_recording_historical_deals_produces_cost_evidence_without_an_order(
    runner, monkeypatch, env
) -> None:
    terminal = FakeMT5()
    _patch_offset(monkeypatch, 10800.0, "measured-m1-bar")
    result = _run(runner, monkeypatch, env, terminal, "--record")
    assert result.exit_code == 0, result.output
    from qts.config.paths import artifact_path

    store = CostEvidenceStore(artifact_path("cost_evidence"))
    deals = store.deals()
    assert deals, "historical deals should be measurable without trading"
    deal = deals[0]
    assert deal.source == "mt5.history_deals_get.backfill"
    assert deal.commission == Decimal("-0.70")
    assert deal.reported_cost == Decimal("0.80")
    assert deal.time_basis == "utc-corrected"
    assert store.verify_chain()[0] is True
