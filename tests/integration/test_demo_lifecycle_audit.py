"""End-to-end DEMO lifecycle audit — the defects the Windows terminal exposed.

Each test here corresponds to a defect found on the real MT5 DEMO host and
reproduced against the simulated terminal:

1.  readiness TTL expiry at Stage 2 (authority refresh deadlock);
2.  ``arm --stage 2`` requiring an illegal ``STAGE_2 → STAGE_2`` transition;
3.  the venue alias (``XAUUSD@``) not resolving to the canonical symbol the
    registered policy is bound to;
4.  a required stop-loss that no caller supplied.

The file also pins the invariants that must survive those fixes: a fresh process
never inherits stale authority, identity mismatch blocks, policy hashes bind,
reconciliation drift halts, the kill switch halts, and no test path can reach a
real broker.

Every terminal here is ``tests/fakes_mt5_demo.FakeTerminal``. No broker is
contacted and no real order exists anywhere.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from demo_harness import authorization_doc
from fakes_mt5_demo import FakeTerminal

from qts.db import connect as db_connect
from qts.execution.demo_identity import confirm_pin, write_pin
from qts.execution.demo_session import DemoSession, DemoSessionConfig
from qts.lifecycle.demo_authority import readiness_age_seconds
from qts.lifecycle.demo_gate import demo_forward_readiness_report
from qts.lifecycle.demo_policy import policy_fingerprint
from qts.lifecycle.demo_registry import load_registry, resolve_entry
from qts.lifecycle.demo_stage import ORDER_STAGES, DemoStage

SYMBOL_MAP = {"XAUUSD": "XAUUSD@"}
PROVIDER_SOURCE = Path(__file__).resolve().parents[2] / "src/qts/research/demo_execution_probe.py"


def _shipped_entry() -> dict:
    doc = json.loads(
        (Path(__file__).resolve().parents[2] / "data/evidence/demo_forward_validation_registry_2026-09-23.json").read_text(
            encoding="utf-8"
        )
    )
    return next(e for e in doc["entries"] if e["strategy_id"] == "DEMO-EXECPROBE-XAUUSD-V1")


def _registry_doc(entry_overrides: dict | None = None, policy_overrides: dict | None = None) -> dict:
    """The registered diagnostic policy, with hours widened and hashes re-sealed.

    Hours are widened so the lifecycle is testable at any time of day; the
    shipped Mon–Fri 08:00–16:00 UTC window is asserted as registered data in
    ``tests/integration/test_demo_research_policy_loop.py``.
    """
    entry = json.loads(json.dumps(_shipped_entry()))  # deep copy
    policy = dict(entry["policy"])
    policy["code_hash"] = hashlib.sha256(PROVIDER_SOURCE.read_bytes()).hexdigest()
    policy["allowed_trading_hours"] = {
        "timezone": "UTC",
        "sessions": [
            {"days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"], "start": "00:00", "end": "23:59"}
        ],
    }
    policy.update(policy_overrides or {})
    policy["policy_hash"] = policy_fingerprint(policy)
    entry["policy"] = policy
    entry.update(entry_overrides or {})
    return {
        "schema": "qts.demo_forward_registry.v2",
        "research_integrity": {
            "optimization_allowed": False,
            "no_forward_fitting": True,
            "parameters_frozen": True,
        },
        "entries": [entry],
    }


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    auth = authorization_doc()
    (tmp_path / "authorization.json").write_text(json.dumps(auth), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(_registry_doc(), indent=2), encoding="utf-8")
    monkeypatch.setenv("QTS_MODE", "demo_execution")
    monkeypatch.setenv("QTS_DEMO_AUTHORIZATION", str(tmp_path / "authorization.json"))
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(registry))
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    # The Windows host's setup stores the venue alias, which is exactly the
    # configuration that exposed the symbol defect — keep it that way here.
    setup = tmp_path / "setup.json"
    setup.write_text(json.dumps({"symbol": "XAUUSD@", "symbol_map": {"XAUUSD": "XAUUSD@"}}), encoding="utf-8")
    monkeypatch.setenv("QTS_SETUP_FILE", str(setup))
    import qts.execution.demo_session as dsmod

    monkeypatch.setattr(dsmod, "SELF_TEST_DB", tmp_path / "selftest.db")
    return {"tmp": tmp_path, "registry": registry, "auth": auth}


def _session(tmp_path: Path, terminal: FakeTerminal, *, symbol: str = "XAUUSD") -> DemoSession:
    return DemoSession(
        DemoSessionConfig(
            symbol=symbol,
            symbol_map=dict(SYMBOL_MAP),
            db_path=tmp_path / "qts.db",
            actor="lifecycle-audit",
            mt5_module=terminal,
        )
    )


def _arm_to_stage_2(session: DemoSession, terminal: FakeTerminal) -> None:
    write_pin(session.adapter.broker_identity(), actor="test", symbol=session.connectivity_report()["symbol_mapping"])
    assert confirm_pin(actor="owner")[0] is True
    report = session.connectivity_report()
    session.stage.advance(
        DemoStage.STAGE_1_CONNECTIVITY,
        actor="test",
        reason="audit arming",
        prerequisites={
            "readiness_passed": bool(report["readiness"]["passed"]),
            "account_is_demo": report["identity"]["is_demo"] is True,
            "symbol_ok": bool(report["symbol_mapping"]["ok"]),
            "quote_fresh": bool(report["quote"]["fresh"]),
        },
    )
    rpt = demo_forward_readiness_report(
        mt5_module=terminal, symbol=session.canonical_symbol, symbol_map=SYMBOL_MAP
    )
    decision = session.authority.enable(
        readiness=rpt, confirmed=True, risk_ack=True, readiness_age_s=readiness_age_seconds(rpt), actor="audit"
    )
    assert decision.execution_permitted is True, decision.reasons
    session.stage.advance(DemoStage.STAGE_2_MIN_SIZE_ORDER, actor="test", reason="audit arming")
    session.reconcile()


def _expire_authority(db_path: Path, *, age_s: float = 300.0) -> None:
    """Age the persisted enablement past REVERIFY_TTL_S (never change the TTL)."""
    stamp = (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat()
    # Through qts.db.connect, never sqlite3.connect directly: the structural
    # guard exists because an unclosed file-backed connection holds a Windows
    # file lock — the very host this lifecycle runs on.
    with db_connect(db_path) as con:
        con.execute(
            "UPDATE demo_execution_state SET decided_at=? WHERE seq=(SELECT MAX(seq) FROM demo_execution_state)",
            (stamp,),
        )
        con.commit()


def _stage_rows(db_path: Path) -> list[tuple]:
    with db_connect(db_path) as con:
        return con.execute("SELECT stage, allowed FROM demo_execution_stage ORDER BY seq").fetchall()


# --------------------------------------------------------------------- tests


def test_venue_alias_resolves_to_the_canonical_symbol_the_policy_binds_to(env):
    """Defect: a setup holding ``XAUUSD@`` compared against a policy allowing ``XAUUSD``."""
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal, symbol="XAUUSD@")  # venue alias, as on the host
    assert session.canonical_symbol == "XAUUSD"
    assert session.broker_symbol == "XAUUSD@"

    _arm_to_stage_2(session, terminal)
    out = session.preflight(side="BUY")
    assert out["verdict"]["passed"], out["verdict"]["failed"]
    assert out["verdict"]["checks"]["symbol_allowed_by_policy"]["passed"]
    assert out["verdict"]["checks"]["broker_symbol_matches_registry"]["passed"]
    assert out["intended_order"]["symbol"] == "XAUUSD"
    assert out["intended_order"]["broker_symbol"] == "XAUUSD@"


def test_policy_pinned_to_another_alias_refuses(env, monkeypatch):
    """The registered alias is binding — a different instrument is not authorised."""
    doc = _registry_doc(entry_overrides={"broker_symbol": "EURUSD@"})
    (env["registry"]).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    out = session.preflight(side="BUY")
    assert not out["verdict"]["passed"]
    assert "broker_symbol_matches_registry" in out["verdict"]["failed"]


def test_required_stop_loss_is_derived_from_the_registered_policy(env):
    """Defect: no supplied SL under a required-SL policy, and no derivation."""
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    params = session.resolve_order_parameters(side="BUY")
    assert params["stop_derived_from_policy"] is True
    assert params["stop_loss"] == Decimal("1998.20")  # ask 2000.20 − 2.00 (policy distance)

    sell = session.resolve_order_parameters(side="SELL")
    assert sell["stop_loss"] == Decimal("2002.00")  # bid 2000.00 + 2.00

    out = session.preflight(side="BUY")
    assert out["verdict"]["passed"], out["verdict"]["failed"]
    assert out["intended_order"]["stop_derived_from_policy"] is True

    # An operator-supplied stop is still used verbatim (and validated).
    explicit = session.preflight(side="BUY", stop_loss=Decimal("1997.00"))
    assert explicit["intended_order"]["stop_loss"] == "1997.00"
    assert explicit["intended_order"]["stop_derived_from_policy"] is False


def test_required_stop_cannot_reach_the_broker_without_a_value(env):
    """A required-SL policy never reaches submission unprotected — even by accident."""
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    entry = resolve_entry(load_registry())[0]

    # No quote ⇒ nothing can be derived ⇒ refused, and the broker sees nothing.
    session._quote_probe = lambda: {"ok": False, "error": "no quote"}  # type: ignore[method-assign]
    result = session.submit(side="BUY", rationale="no quote", entry=entry)
    assert result.allowed is False
    assert terminal.requests == []


def test_stage_2_authority_refresh_after_readiness_ttl_expiry(env):
    """Defect: expired evidence at Stage 2 with no legal way to refresh it."""
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    _expire_authority(env["tmp"] / "qts.db")

    assert session.authority.current().execution_permitted is False
    result = session.submit(side="BUY")
    assert result.allowed is False
    assert "execution_permission" in (result.verdict or {}).get("failed", [])

    outcome = session.reverify_authority(confirmed=True, risk_ack=True, actor="audit")
    assert outcome["reverified"] is True
    assert outcome["stage"]["stage"] == DemoStage.STAGE_2_MIN_SIZE_ORDER.value  # unchanged
    assert session.authority.current().execution_permitted is True

    # The TTL was NOT changed: only a fresh probe can re-grant permission.
    from qts.lifecycle.demo_authority import REVERIFY_TTL_S

    assert REVERIFY_TTL_S == 120.0


def test_arm_at_the_current_stage_refreshes_without_an_illegal_transition(env):
    """Defect: `arm --stage 2` at Stage 2 → REFUSED (STAGE_2 → STAGE_2 not allowed)."""
    from click.testing import CliRunner

    from qts.cli import main

    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    _expire_authority(env["tmp"] / "qts.db")
    rows_before = _stage_rows(env["tmp"] / "qts.db")

    import sys

    original = sys.modules.get("MetaTrader5")
    sys.modules["MetaTrader5"] = terminal
    try:
        runner = CliRunner()
        db = str(env["tmp"] / "qts.db")
        refused = runner.invoke(main, ["demo", "arm", "--stage", "2", "--db", db])
        assert refused.exit_code == 2  # confirmation is still required
        assert "re-verifying requires explicit confirmation" in refused.output

        ok = runner.invoke(main, ["demo", "arm", "--stage", "2", "--confirm", "--risk-ack", "--db", db])
        assert ok.exit_code == 0, ok.output
        assert "already at STAGE_2_MIN_SIZE_ORDER" in ok.output
    finally:
        if original is None:
            sys.modules.pop("MetaTrader5", None)
        else:  # pragma: no cover
            sys.modules["MetaTrader5"] = original

    rows_after = _stage_rows(env["tmp"] / "qts.db")
    assert rows_after == rows_before, "a refresh must not append a stage transition"
    assert session.stage.current().stage in ORDER_STAGES


def test_reverify_command_refreshes_permission_and_reports_it(env):
    import sys

    from click.testing import CliRunner

    from qts.cli import main

    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    _expire_authority(env["tmp"] / "qts.db")

    original = sys.modules.get("MetaTrader5")
    sys.modules["MetaTrader5"] = terminal
    try:
        runner = CliRunner()
        db = str(env["tmp"] / "qts.db")
        without_flags = runner.invoke(main, ["demo", "reverify", "--db", db])
        assert without_flags.exit_code == 2
        assert "requires explicit confirmation" in without_flags.output

        ok = runner.invoke(main, ["demo", "reverify", "--confirm", "--risk-ack", "--db", db])
        assert ok.exit_code == 0, ok.output
        assert "REVERIFIED: True" in ok.output
        assert "unchanged" in ok.output
    finally:
        if original is None:
            sys.modules.pop("MetaTrader5", None)
        else:  # pragma: no cover
            sys.modules["MetaTrader5"] = original


def test_verify_suggests_a_command_that_actually_works(env):
    """The NEXT action after expiry must be runnable, not an illegal transition."""
    import sys

    from click.testing import CliRunner

    from qts.cli import main

    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    _expire_authority(env["tmp"] / "qts.db")

    original = sys.modules.get("MetaTrader5")
    sys.modules["MetaTrader5"] = terminal
    try:
        runner = CliRunner()
        db = str(env["tmp"] / "qts.db")
        first = runner.invoke(main, ["demo", "verify", "--db", db])
        assert first.exit_code == 2
        assert "qts demo reverify --confirm --risk-ack" in first.output
        assert "STAGE_2 → STAGE_2" not in first.output

        suggested = runner.invoke(main, ["demo", "reverify", "--confirm", "--risk-ack", "--db", db])
        assert suggested.exit_code == 0, suggested.output

        again = runner.invoke(main, ["demo", "verify", "--db", db])
        assert again.exit_code == 0, again.output
        assert "READY: True" in again.output
    finally:
        if original is None:
            sys.modules.pop("MetaTrader5", None)
        else:  # pragma: no cover
            sys.modules["MetaTrader5"] = original


def test_fresh_process_does_not_inherit_stale_authority(env):
    """A new process must re-prove permission; it never inherits an old enablement."""
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    _expire_authority(env["tmp"] / "qts.db")

    fresh = _session(env["tmp"], terminal)  # new process, same durable state
    assert fresh.authority.current().execution_permitted is False
    assert fresh.stage.current().stage == DemoStage.STAGE_2_MIN_SIZE_ORDER.value  # the stage persisted
    result = fresh.submit(side="BUY")
    assert result.allowed is False
    assert "execution_permission" in (result.verdict or {}).get("failed", [])
    assert terminal.requests == []


def test_identity_mismatch_blocks_orders(env):
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    # The pinned account is no longer the one connected.
    terminal.account.server = "Broker-Live"
    out = session.preflight(side="BUY")
    assert not out["verdict"]["passed"]
    assert "broker_identity_verified" in out["verdict"]["failed"]
    assert terminal.requests == []


def test_policy_hash_and_config_drift_are_refused(env, monkeypatch):
    """Editing a registered policy invalidates it — limits are not editable in place."""
    doc = _registry_doc()
    doc["entries"][0]["policy"]["max_daily_loss"] = 5000.0  # unsealed edit
    (env["registry"]).write_text(json.dumps(doc, indent=2), encoding="utf-8")

    registry = load_registry()
    assert registry.valid is False
    assert any("policy_hash mismatch" in r for r in registry.reasons)
    assert resolve_entry(registry)[0] is None

    # Re-sealing makes the same content valid again (that is how a change is
    # registered — with a new preregistration, never a silent edit).
    doc["entries"][0]["policy"]["policy_hash"] = policy_fingerprint(doc["entries"][0]["policy"])
    (env["registry"]).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    assert load_registry().valid is True

    # Config drift (parameters no longer match config_hash) is still refused.
    doc2 = _registry_doc()
    doc2["entries"][0]["params"]["sample_interval_minutes"] = 5
    (env["registry"]).write_text(json.dumps(doc2, indent=2), encoding="utf-8")
    assert any("config_hash" in r for r in load_registry().reasons)


def test_reconciliation_drift_halts_and_refuses_orders(env):
    from tests.fakes_mt5_demo import FakeTerminal as FT

    terminal = FT()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    # A venue position the journal cannot account for.
    from types import SimpleNamespace

    terminal.positions = [
        SimpleNamespace(
            ticket=555_001,
            symbol="XAUUSD@",
            volume=0.01,
            type=0,
            price_open=2000.0,
            price_current=2000.0,
            profit=-1.0,
            time=int(datetime.now(UTC).timestamp()) - 60,
            comment="",
            magic=0,
        )
    ]
    terminal.deals = []
    state = session.reconcile()
    assert state["requires_suspend"] is True

    result = session.submit(side="BUY")
    assert result.allowed is False
    assert "reconciliation_ready" in (result.verdict or {}).get("failed", [])
    assert terminal.requests == []
    # A control failure is a halt, not a retry: the stage records it.
    assert session.stage.current().stage == DemoStage.HALTED.value


def test_kill_switch_blocks_orders_and_halts_the_stage(env):
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)

    session.raise_kill_switch("audit: kill switch test")
    assert session.kill_switch_state().get("killed") is True

    result = session.submit(side="BUY")
    assert result.allowed is False
    assert "kill_switch_functional" in (result.verdict or {}).get("failed", [])
    assert terminal.requests == []
    assert session.stage.current().stage == DemoStage.HALTED.value


def test_full_lifecycle_stage1_to_close(env):
    """Stage 1 → Stage 2 → preflight → submit → reconcile → managed close."""
    from qts.execution.demo_autopilot import AutopilotConfig, run_autopilot

    # open_age_s makes the position the venue opens report an old open time, so
    # the registered max-hold exit applies to it on the next cycle.
    terminal = FakeTerminal(open_age_s=600.0)
    session = _session(env["tmp"], terminal)

    # --- Stage 1 (no orders, no broker requests) --------------------------
    report = session.connectivity_report()
    assert report["identity"]["is_demo"] is True
    assert report["symbol_mapping"]["canonical"] == "XAUUSD"
    assert report["symbol_mapping"]["broker_symbol"] == "XAUUSD@"
    assert terminal.requests == []

    _arm_to_stage_2(session, terminal)
    assert session.stage.current().stage == DemoStage.STAGE_2_MIN_SIZE_ORDER.value

    # --- preflight (submits nothing) --------------------------------------
    pre = session.preflight(side="BUY")
    assert pre["verdict"]["passed"], pre["verdict"]["failed"]
    assert terminal.requests == []

    # --- submit ------------------------------------------------------------
    entry = resolve_entry(load_registry())[0]
    result = session.submit(side="BUY", rationale="lifecycle audit", entry=entry)
    assert result.allowed, result.reasons
    assert len(terminal.requests) == 1
    assert terminal.requests[0]["symbol"] == "XAUUSD@"
    assert terminal.requests[0]["volume"] == 0.01
    assert terminal.requests[0]["sl"] is not None

    row = session.journal.list_orders()[0]
    assert row["broker_order_id"] and row["broker_position_id"]
    assert row["reconciled"] in (0, 1, True, False)
    assert session.reconcile()["requires_suspend"] is False

    # --- managed close (max hold exceeded) ---------------------------------
    # The exit policy is registered data, so it is changed in the registry (and
    # re-sealed), never patched onto a resolved object.
    (env["registry"]).write_text(
        json.dumps(_registry_doc(entry_overrides={"exit_policy": {"max_hold_seconds": 60.0}}), indent=2),
        encoding="utf-8",
    )
    run_autopilot(
        session, AutopilotConfig(symbol="XAUUSD", max_iterations=1, poll_interval_s=0, actor="audit-close")
    )
    closes = [r for r in terminal.requests if "position" in r]
    assert len(closes) == 1
    assert session.journal.list_orders()[0]["state"] == "CLOSED"
    assert session.reconcile()["requires_suspend"] is False


def test_no_test_path_can_reach_a_real_broker(env, monkeypatch):
    """Every DEMO path here runs on an injected module — never the real one.

    ``_optional_mt5_module`` is the adapter's fallback to ``import MetaTrader5``.
    If any code under test used it, this test would fail: the point is that the
    session only ever talks to the module handed to it.
    """
    import qts.adapters.mt5_adapter as adapter_module

    def _explode() -> None:
        raise AssertionError("a real MetaTrader5 module was requested — tests must inject a fake")

    monkeypatch.setattr(adapter_module, "_optional_mt5_module", _explode)

    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    out = session.preflight(side="BUY")
    assert out["verdict"]["passed"], out["verdict"]["failed"]
    assert terminal.requests == []


def test_mode_binding_still_refuses_outside_demo_execution(env, monkeypatch):
    """The lifecycle fixes must not have opened a path around the mode gate."""
    monkeypatch.setenv("QTS_MODE", "DEMO_FORWARD")
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    assert str(session.mode) == "DEMO_FORWARD"
    assert session.policy.enabled is False
    result = session.submit(side="BUY")
    assert result.allowed is False
    assert terminal.requests == []


def test_order_journal_records_the_canonical_symbol(env):
    """The journal, like the policy, keys on the canonical symbol."""
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal, symbol="XAUUSD@")
    _arm_to_stage_2(session, terminal)
    entry = resolve_entry(load_registry())[0]
    result = session.submit(side="BUY", rationale="symbol audit", entry=entry)
    assert result.allowed, result.reasons
    row = session.journal.list_orders()[0]
    assert row["symbol"] == "XAUUSD"
    assert row["broker_symbol"] == "XAUUSD@"


def test_missing_alias_table_is_refused_with_an_actionable_remedy(env):
    """No guessing: an unmapped venue alias is refused, and the message says what to declare.

    The alias table is machine-local (``data/setup/mt5_setup.json``). Without an
    entry, ``XAUUSD@`` cannot be resolved to the canonical ``XAUUSD`` the policy
    binds to — the order must be refused (never inferred from the suffix), and
    the operator must be told exactly what to declare.
    """
    terminal = FakeTerminal()
    unmapped = _session(env["tmp"], terminal, symbol="XAUUSD@")
    unmapped.config.symbol_map = {}  # no alias table declared on this host
    _arm_to_stage_2(unmapped, terminal)

    out = unmapped.preflight(side="BUY")
    assert not out["verdict"]["passed"]
    assert "symbol_allowed_by_policy" in out["verdict"]["failed"]
    detail = out["verdict"]["checks"]["symbol_allowed_by_policy"]["detail"]
    assert "symbol_map" in detail and "data/setup/mt5_setup.json" in detail
    assert '"XAUUSD": "XAUUSD@"' in detail  # the exact declaration to add
    assert terminal.requests == []


def test_declaring_the_alias_table_makes_the_same_policy_pass(env):
    """The remedy is configuration, not code: declare the table and it resolves."""
    terminal = FakeTerminal()
    mapped = _session(env["tmp"], terminal, symbol="XAUUSD@")  # SYMBOL_MAP declared
    _arm_to_stage_2(mapped, terminal)

    out = mapped.preflight(side="BUY")
    assert out["verdict"]["passed"], out["verdict"]["failed"]
    assert out["intended_order"]["symbol"] == "XAUUSD"
    assert out["intended_order"]["broker_symbol"] == "XAUUSD@"


def test_changing_the_alias_table_after_pinning_is_refused(env):
    """The pin binds symbol provenance: a mid-session re-spelling fails closed.

    The identity pin records which canonical/venue pair the owner confirmed. If
    the alias table is changed afterwards, the session resolves a different
    canonical symbol than the one that was pinned — that is refused rather than
    silently accepted, because the owner confirmed a specific instrument on a
    specific account.
    """
    terminal = FakeTerminal()
    session = _session(env["tmp"], terminal)
    _arm_to_stage_2(session, terminal)
    assert session.preflight(side="BUY")["verdict"]["passed"]

    session.config.symbol_map = {"XAUUSD": "XAUUSD#"}  # a different venue spelling
    out = session.preflight(side="BUY")
    assert not out["verdict"]["passed"]
    assert "symbol_provenance" in out["verdict"]["failed"]
    assert terminal.requests == []
