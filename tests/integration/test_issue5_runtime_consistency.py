"""Issue #5 regression tests — the runtime split between CLI, backend and terminal.

Five independent root causes were traced from the reported symptoms:

RC-1  every machine-local artefact defaulted to a **cwd-relative** path, so a
      CLI invoked outside the repository read no setup/pin/authorization/registry
      and a *different* database than the backend;
RC-2  the mode came only from per-process environment, so the desktop backend
      resolved DEVELOPMENT while the operator's shell resolved DEMO_EXECUTION;
RC-3  two API probes built ``MT5Adapter`` without the alias table and asked the
      broker for ``XAUUSD`` while the DEMO session traded ``XAUUSD@``;
RC-4  the MT5 IPC link was only ever established as a side effect of the
      readiness probe, so a process that went straight to execution
      (``qts demo run``, whose first step reconciles) failed with
      ``(-10004, 'No IPC connection')``;
RC-5  the registered policy's stop distance was not authoritative — a caller
      could submit a wider stop than the experiment preregistered.

Each test below pins the fixed behaviour *and* the safety property that must not
change while fixing it: LIVE stays locked, nothing is retried blindly, a genuine
broker disconnect still suspends reconciliation and halts.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes_mt5_demo import FakeTerminal

from qts.adapters.mt5_adapter import MT5Adapter, MT5SessionError
from qts.adapters.mt5_factory import adapter_from_setup, resolve_connection
from qts.config.paths import artifact_path, paths_report
from qts.config.wizard import declare_mode, load_setup, save_setup, setup_file
from qts.domain.modes import (
    ExecutionMode,
    effective_mode_report,
    mode_source,
    persisted_mode_declaration,
    resolve_mode,
)


@pytest.fixture()
def state(tmp_path: Path, monkeypatch):
    """A hermetic machine-local state root, with no mode declared anywhere."""
    monkeypatch.setenv("QTS_STATE_ROOT", str(tmp_path))
    for name in ("QTS_MODE", "QTS_ENV", "QTS_SETUP_FILE", "QTS_DEMO_IDENTITY_PIN",
                 "QTS_DEMO_AUTHORIZATION", "QTS_DEMO_REGISTRY", "QTS_DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "data/setup").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_setup(root: Path, **fields) -> Path:
    path = root / "data/setup/mt5_setup.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------- RC-1


def test_artefact_paths_do_not_depend_on_the_working_directory(state, monkeypatch):
    """The flaw behind "symbol_map saved but ignored": relative defaults.

    Two processes on one machine must resolve the same setup, pin, authorization,
    registry and database no matter which directory they were launched from.
    """
    from_repo = {name: str(artifact_path(name)) for name in ("setup", "identity_pin", "authorization", "registry", "db")}

    elsewhere = tmp_other = state.parent / "some-other-cwd"
    elsewhere.mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_other)
    from_elsewhere = {name: str(artifact_path(name)) for name in from_repo}

    assert from_repo == from_elsewhere
    assert all(str(state) in path for path in from_elsewhere.values())
    assert paths_report()["cwd_independent"] is True
    assert paths_report()["working_directory"] == str(tmp_other)


def test_a_setup_written_at_the_state_root_is_found_from_any_directory(state, monkeypatch):
    _write_setup(state, symbol="XAUUSD", symbol_map={"XAUUSD": "XAUUSD@"})

    monkeypatch.chdir(state.parent)
    saved = load_setup()
    assert saved["symbol_map"] == {"XAUUSD": "XAUUSD@"}
    # ...and the connection factory therefore resolves the venue alias.
    assert resolve_connection()["broker_symbol"] == "XAUUSD@"
    assert resolve_connection()["canonical_symbol"] == "XAUUSD"


def test_environment_overrides_still_win_verbatim(state, monkeypatch):
    """Portability and tests keep working: an explicit env path is used as given."""
    custom = state / "custom" / "elsewhere.json"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text(json.dumps({"symbol": "XAUUSD"}), encoding="utf-8")
    monkeypatch.setenv("QTS_SETUP_FILE", str(custom))
    assert setup_file() == custom
    assert artifact_path("setup") == custom
    assert paths_report()["artifacts"]["setup"]["source"].startswith("QTS_SETUP_FILE")


def test_backend_and_cli_resolve_the_same_database(state):
    """`server._db_path()` was a relative literal; the CLI default was another."""
    from qts.api.server import _db_path
    from qts.config.paths import default_db_path

    assert _db_path() == artifact_path("db")
    assert Path(default_db_path()) == artifact_path("db")


# --------------------------------------------------------------------- RC-2


def test_a_persisted_declaration_makes_both_surfaces_resolve_the_same_mode(state):
    """The backend has no shell environment: it must read what the operator declared."""
    assert resolve_mode() is ExecutionMode.DEVELOPMENT  # fail closed with nothing declared

    _write_setup(state, symbol="XAUUSD", symbol_map={"XAUUSD": "XAUUSD@"})
    declare_mode("demo_execution")

    assert resolve_mode() is ExecutionMode.DEMO_EXECUTION
    assert "mode declaration" in mode_source()
    assert persisted_mode_declaration()[0] == "demo_execution"
    # A second process (the backend) resolving from the same file agrees — this is
    # the whole fix: no per-shell env required for the two to match.
    assert effective_mode_report()["effective_mode"] == "DEMO_EXECUTION"


def test_environment_still_overrides_the_persisted_declaration(state):
    _write_setup(state, mode="demo_execution")
    import os

    os.environ["QTS_MODE"] = "development"
    try:
        assert resolve_mode() is ExecutionMode.DEVELOPMENT
        assert mode_source().startswith("QTS_MODE=")
    finally:
        del os.environ["QTS_MODE"]


def test_live_can_never_be_declared(state):
    """No config file, API call or UI action may select a real-capital mode."""
    with pytest.raises(ValueError, match="never declarable"):
        declare_mode("live")
    with pytest.raises(ValueError, match="never declarable"):
        declare_mode("micro")  # historical alias of LIVE

    # Even hand-written into the file, it is refused — and falls through to
    # DEVELOPMENT (the safest, least-capable mode). The refusal is auditable in
    # diagnostics.
    _write_setup(state, mode="live")
    assert resolve_mode() is ExecutionMode.DEVELOPMENT
    report = effective_mode_report()
    assert report["refused_real_capital_declarations"]
    assert any("live" in r.lower() for r in report["refused_real_capital_declarations"])
    assert not resolve_mode().can_submit_broker_orders


def test_the_api_cannot_write_the_mode_declaration(state):
    """`save_setup` is what POST /api/setup/mt5 calls: mode must be rejected."""
    result = save_setup({"symbol": "XAUUSD", "symbol_map": {"XAUUSD": "XAUUSD@"}, "mode": "demo_execution"})
    assert "mode" in result["rejected_fields"]
    assert result["mode_note"]
    assert load_setup().get("mode") is None
    assert resolve_mode() is ExecutionMode.DEVELOPMENT


def test_demo_status_reports_the_resolved_mode_not_a_literal(state, monkeypatch):
    """`qts demo status` used to print the literal "DEMO_EXECUTION" in DEVELOPMENT."""
    from click.testing import CliRunner

    from qts.cli import main

    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(state / "absent-authorization.json"))
    out = CliRunner().invoke(main, ["demo", "status"])
    body = json.loads(out.output[out.output.index("{"):])
    assert body["mode"] == "DEVELOPMENT"
    assert "mode_source" in body
    assert body["policy"]["enabled"] is False


# --------------------------------------------------------------------- RC-3


def test_every_api_adapter_carries_the_alias_table(state):
    """An adapter with an empty map asks the broker for a symbol it does not have."""
    _write_setup(state, symbol="XAUUSD", symbol_map={"XAUUSD": "XAUUSD@"}, terminal_path="C:/MT5/terminal64.exe")

    adapter, connection = adapter_from_setup()
    assert adapter.symbol_map == {"XAUUSD": "XAUUSD@"}
    assert connection["canonical_symbol"] == "XAUUSD"
    assert connection["broker_symbol"] == "XAUUSD@"
    assert connection["alias_declared"] is True
    # The adapter itself sends the venue symbol, never the canonical name.
    assert adapter._map_symbol("XAUUSD") == "XAUUSD@"


def test_a_setup_storing_the_venue_alias_still_resolves_canonically(state):
    """Operators save either spelling; canonical stays XAUUSD, venue stays XAUUSD@."""
    _write_setup(state, symbol="XAUUSD@", symbol_map={"XAUUSD": "XAUUSD@"})
    connection = resolve_connection()
    assert connection["canonical_symbol"] == "XAUUSD"
    assert connection["broker_symbol"] == "XAUUSD@"


def test_mt5_panel_probes_the_venue_symbol_and_says_so(state, monkeypatch):
    """/api/mt5 must not imply one symbol while testing another."""
    from fastapi.testclient import TestClient

    from qts.api import server

    _write_setup(state, symbol="XAUUSD", symbol_map={"XAUUSD": "XAUUSD@"})
    terminal = FakeTerminal()
    seen: list[str] = []
    real_symbol_info = terminal.symbol_info

    def spy(name):
        seen.append(name)
        return real_symbol_info(name)

    terminal.symbol_info = spy  # type: ignore[method-assign]
    monkeypatch.setattr(server, "_connection_adapter", lambda symbol=None: adapter_from_setup(symbol, mt5_module=terminal))

    with TestClient(server.app) as client:
        body = client.get("/api/mt5").json()

    assert body["connection"]["canonical_symbol"] == "XAUUSD"
    assert body["connection"]["broker_symbol"] == "XAUUSD@"
    assert body["connection"]["alias_declared"] is True
    assert body["spec"]["probed_symbol"] == "XAUUSD@"
    assert seen and set(seen) == {"XAUUSD@"}, f"the broker was asked for {seen}"


def test_runtime_state_endpoint_publishes_mode_provenance_and_paths(state):
    from fastapi.testclient import TestClient

    from qts.api import server

    _write_setup(state, symbol="XAUUSD", symbol_map={"XAUUSD": "XAUUSD@"})
    declare_mode("demo_execution")
    with TestClient(server.app) as client:
        body = client.get("/api/runtime/state").json()

    assert body["mode"]["effective_mode"] == "DEMO_EXECUTION"
    assert "mode declaration" in body["mode"]["mode_source"]
    assert body["state"]["state_root"] == str(state)
    assert body["state"]["artifacts"]["setup"]["exists"] is True
    assert "LIVE stays locked" in body["note"]


def test_observation_symbol_resolution_returns_canonical_first(state):
    """An observer configured with the alias used to record the venue spelling."""
    from qts.api.server import _resolve_observe_symbol

    canonical, broker = _resolve_observe_symbol({"symbol": "XAUUSD@", "symbol_map": {"XAUUSD": "XAUUSD@"}})
    assert (canonical, broker) == ("XAUUSD", "XAUUSD@")
    assert _resolve_observe_symbol({"symbol": "XAUUSD", "symbol_map": {"XAUUSD": "XAUUSD@"}}) == ("XAUUSD", "XAUUSD@")


# --------------------------------------------------------------------- RC-4


class CountingTerminal(FakeTerminal):
    """A terminal that counts IPC establishments — proves there is no retry loop."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.initialize_calls = 0

    def initialize(self, **kwargs):
        self.initialize_calls += 1
        return True


class DeadTerminal(FakeTerminal):
    """A terminal whose IPC link cannot be established (-10004)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.initialize_calls = 0

    def initialize(self, **kwargs):
        self.initialize_calls += 1
        return False

    def last_error(self):
        return (-10004, "No IPC connection")

    def terminal_info(self):
        return None


def test_a_fresh_process_establishes_ipc_before_its_first_broker_call():
    """The exact `qts demo run` failure: reconcile first, nothing initialized."""
    terminal = CountingTerminal()
    adapter = MT5Adapter(
        config={"path": "C:/MT5/terminal64.exe", "symbol_map": {"XAUUSD": "XAUUSD@"}},
        mt5_module=terminal,
        db_path=":memory:",
    )
    # No readiness probe, no connect() — straight to a broker-facing call.
    assert adapter.positions() == []
    assert terminal.initialize_calls == 1
    assert adapter.session_state()["established"] is True
    assert adapter.session_state()["kind"] == "initialized"


def test_ipc_is_established_once_and_never_blindly_retried():
    terminal = CountingTerminal()
    adapter = MT5Adapter(config={"path": ""}, mt5_module=terminal, db_path=":memory:")
    for _ in range(5):
        adapter.positions()
        adapter.account()
    assert terminal.initialize_calls == 1, "the link must be established once per process, not per call"


def test_a_dead_link_fails_closed_with_a_lifecycle_diagnosis():
    terminal = DeadTerminal()
    adapter = MT5Adapter(config={"path": "C:/MT5/terminal64.exe"}, mt5_module=terminal, db_path=":memory:")
    with pytest.raises(MT5SessionError) as excinfo:
        adapter.positions()
    message = str(excinfo.value)
    assert "-10004" in message
    assert "per process" in message
    assert "NOT a reconciliation drift" in message
    assert "no order was sent" in message.lower()
    assert terminal.initialize_calls == 1, "one deterministic attempt — never a retry loop"


def test_health_check_reports_a_failed_link_instead_of_raising():
    terminal = DeadTerminal()
    adapter = MT5Adapter(config={"path": "C:/MT5/terminal64.exe"}, mt5_module=terminal, db_path=":memory:")
    health = adapter.health_check()
    assert health["connected"] is False
    assert "-10004" in health["session_error"]
    assert adapter.is_connected() is False


def test_an_explicit_disconnect_invalidates_the_cached_link():
    """A dead link must never be believed established on the strength of a cache."""
    terminal = CountingTerminal()
    adapter = MT5Adapter(config={"path": ""}, mt5_module=terminal, db_path=":memory:")
    adapter.positions()
    assert adapter.session_state()["established"] is True

    adapter.disconnect()
    assert adapter.session_state()["established"] is False
    adapter.positions()  # re-establishes deliberately, once
    assert terminal.initialize_calls == 2


def test_reconciliation_still_suspends_on_a_genuine_broker_disconnect(state):
    """Fixing the lifecycle must not weaken the fail-closed reconciliation path."""
    from qts.execution.demo_session import DemoSession, DemoSessionConfig

    terminal = DeadTerminal()
    session = DemoSession(
        DemoSessionConfig(
            symbol="XAUUSD",
            symbol_map={"XAUUSD": "XAUUSD@"},
            db_path=state / "qts.db",
            actor="issue5-test",
            mt5_module=terminal,
        )
    )
    outcome = session.reconcile()
    assert outcome["drift"] == "BROKER_DISCONNECT"
    assert outcome["requires_suspend"] is True
    assert "-10004" in str(outcome["details"]) or "IPC" in str(outcome["details"])
    assert terminal.requests == []


def test_an_injected_double_without_initialize_needs_no_ipc():
    """Test doubles keep working: no IPC to establish, nothing invented."""
    minimal = SimpleNamespace(
        positions_get=lambda *a, **k: [],
        account_info=lambda: SimpleNamespace(balance=10_000.0, equity=10_000.0, currency="USD", login=1),
    )
    adapter = MT5Adapter(config={}, mt5_module=minimal, db_path=":memory:")
    assert adapter.session_state()["established"] is False  # not established yet
    assert adapter.positions() == []
    assert adapter.session_state()["kind"] == "injected"


# --------------------------------------------------------------------- RC-5


def test_a_stop_wider_than_the_registered_policy_is_refused(tmp_path: Path):
    """The immutable policy caps per-order risk; a caller cannot widen it."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adversarial"))
    from test_demo_pretrade_gate import _entry, _research_policy, healthy_ctx  # noqa: PLC0415

    from qts.execution.demo_pretrade import run_pretrade_gate

    entry = _entry(policy=_research_policy({"lookback": 16}))
    registered = Decimal(str(entry.policy.stop_distance_price()))
    ask = Decimal("2000.20")  # healthy_ctx's BUY reference price

    wider = healthy_ctx(tmp_path, entry=entry, stop_loss=ask - registered - Decimal("1.00"))
    verdict = run_pretrade_gate(wider)
    assert not verdict.passed
    assert "stop_within_policy_distance" in verdict.failed
    assert "never preregistered" in verdict.checks["stop_within_policy_distance"].detail

    exact = healthy_ctx(tmp_path, entry=entry, stop_loss=ask - registered)
    assert run_pretrade_gate(exact).checks["stop_within_policy_distance"].passed

    tighter = healthy_ctx(tmp_path, entry=entry, stop_loss=ask - Decimal("1.00"))
    result = run_pretrade_gate(tighter)
    assert result.checks["stop_within_policy_distance"].passed
    assert "tighter" in result.checks["stop_within_policy_distance"].detail


def test_registry_refuses_a_params_policy_stop_distance_divergence(state, monkeypatch):
    """One registered quantity, one value — even where the hashes cannot see it.

    ``params_hash`` and the policy's ``config_hash`` bind the *params* dict, so
    editing params is already caught. They do not bind the policy's own
    ``stop_loss_logic.distance_price``: a policy can hash params declaring 2.00
    while its stop logic declares 5.00, and the two are read by different code.
    That silent disagreement is what an order would be submitted with.
    """
    from qts.lifecycle.demo_policy import policy_fingerprint
    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    registry_path = state / "registry.json"
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(registry_path))
    shipped = json.loads(
        (Path(__file__).resolve().parents[2] / "data/evidence/demo_forward_validation_registry_2026-09-23.json").read_text(
            encoding="utf-8"
        )
    )
    entry = shipped["entries"][0]
    params_distance = float(entry["params"]["stop_distance_price"])
    entry["policy"]["stop_loss_logic"]["distance_price"] = params_distance + 3.0
    # Re-seal the policy document so policy_hash passes, exposing the semantic
    # cross-check between the params dict and the policy's stop_loss_logic.
    entry["policy"]["policy_hash"] = policy_fingerprint(entry["policy"])
    registry_path.write_text(json.dumps(shipped, indent=2), encoding="utf-8")

    snapshot = load_registry()
    assert snapshot.valid is False
    assert any("stop_loss_logic.distance_price" in problem for problem in snapshot.reasons), snapshot.reasons
    assert resolve_entry(snapshot)[0] is None


def test_registry_refuses_edited_params_before_any_stop_comparison(state, monkeypatch):
    """The pre-existing immutability guard still fires first and still refuses."""
    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    registry_path = state / "registry.json"
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(registry_path))
    shipped = json.loads(
        (Path(__file__).resolve().parents[2] / "data/evidence/demo_forward_validation_registry_2026-09-23.json").read_text(
            encoding="utf-8"
        )
    )
    shipped["entries"][0]["params"]["stop_distance_price"] = 5.0
    registry_path.write_text(json.dumps(shipped, indent=2), encoding="utf-8")

    snapshot = load_registry()
    assert snapshot.valid is False
    assert any("params_hash mismatch" in problem for problem in snapshot.reasons), snapshot.reasons
    assert resolve_entry(snapshot)[0] is None


def test_the_shipped_registry_is_internally_consistent():
    """Guard the shipped diagnostic entry against the divergence class itself."""
    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    snapshot = load_registry()
    entry, reasons = resolve_entry(snapshot)
    assert snapshot.valid is True, snapshot.reasons
    assert entry is not None, reasons
    assert entry.policy.stop_distance_price() == float(entry.params["stop_distance_price"])
