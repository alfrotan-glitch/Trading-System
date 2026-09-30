"""Adversarial tests for DEMO identity verification and the strategy registry.

Covers the two questions that decide whether DEMO execution may touch a
broker at all:

1. is the connected account **provably** DEMO, on the **pinned** broker/server?
2. is there a **registered, frozen** strategy allowed to generate orders?

Both must fail closed: an unprovable fact is a refusal, never a default.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes_demo_provider import policy_block

from qts.execution.demo_identity import (
    BrokerIdentity,
    BrokerIdentityError,
    assert_demo_account,
    confirm_pin,
    identity_fingerprint,
    load_pin,
    probe_broker_identity,
    verify_pin,
    write_pin,
)
from qts.lifecycle.demo_policy import POLICY_CLASS
from qts.lifecycle.demo_registry import (
    load_registry,
    params_fingerprint,
    registry_status,
    resolve_entry,
)

# ------------------------------------------------------------------ fakes


def _mt5(
    *,
    login=123456,
    server="Broker-Demo",
    company="Example Brokers Ltd",
    trade_mode=0,
    trade_allowed=True,
    trade_expert=True,
    account_missing=False,
    initialize_ok=True,
):
    account = None
    if not account_missing:
        account = SimpleNamespace(
            login=login,
            server=server,
            company=company,
            name="Research Demo",
            trade_mode=trade_mode,
            trade_allowed=trade_allowed,
            trade_expert=trade_expert,
            currency="USD",
            leverage=100,
            balance=10000.0,
            equity=10000.0,
        )
    return SimpleNamespace(
        initialize=lambda **kwargs: initialize_ok,
        last_error=lambda: (1, "ok"),
        account_info=lambda: account,
        terminal_info=lambda: SimpleNamespace(connected=True, company=company, build=4000),
    )


def _identity(**overrides) -> BrokerIdentity:
    base = {
        "login":123456,
        "server":"Broker-Demo",
        "company":"Example Brokers Ltd",
        "account_name":"Research Demo",
        "trade_mode":0,
        "trade_allowed":True,
        "trade_expert":True,
        "currency":"USD",
        "leverage":100,
        "balance":10000.0,
        "equity":10000.0,
        "terminal_connected":True,
        "terminal_company":"Example Brokers Ltd",
        "terminal_build":4000,
        "receipt_at":datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return BrokerIdentity(**base)


# ----------------------------------------------------------------- identity


def test_probe_identifies_demo_account():
    identity = probe_broker_identity(_mt5(trade_mode=0))
    assert identity.is_demo is True
    assert identity.account_type == "DEMO"
    assert identity.login == 123456
    assert identity.server == "Broker-Demo"


def test_probe_identifies_real_account():
    identity = probe_broker_identity(_mt5(trade_mode=2))
    assert identity.is_demo is False
    ok, reasons = assert_demo_account(identity)
    assert ok is False
    assert "REAL" in reasons[0]


def test_probe_reports_unknown_when_trade_mode_missing():
    missing = SimpleNamespace(
        initialize=lambda **kwargs: True,
        last_error=lambda: (1, "ok"),
        account_info=lambda: SimpleNamespace(login=1, server="S", company="C"),
        terminal_info=lambda: SimpleNamespace(connected=True, company="C", build=1),
    )
    identity = probe_broker_identity(missing)
    assert identity.is_demo is None
    ok, reasons = assert_demo_account(identity)
    assert ok is False
    assert "UNPROVABLE" in reasons[0]


def test_probe_fails_closed_when_account_info_unavailable():
    with pytest.raises(BrokerIdentityError):
        probe_broker_identity(_mt5(account_missing=True))


def test_probe_fails_closed_when_initialize_fails():
    with pytest.raises(BrokerIdentityError):
        probe_broker_identity(_mt5(initialize_ok=False))


def test_assert_demo_refuses_when_expert_trading_disabled():
    ok, reasons = assert_demo_account(_identity(trade_expert=False))
    assert ok is False
    assert "trade_expert" in reasons[0]


def test_identity_fingerprint_changes_with_account():
    a = _identity()
    b = _identity(login=999999)
    assert identity_fingerprint(a) != identity_fingerprint(b)
    assert identity_fingerprint(a) == identity_fingerprint(_identity())


# ---------------------------------------------------------------------- pin


def test_pin_lifecycle_write_confirm_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    identity = _identity()

    assert load_pin()[0] is None
    path = write_pin(identity, actor="cli")
    assert path.exists()

    pin, _ = load_pin()
    assert pin["status"] == "PENDING_REVIEW"

    # An unconfirmed pin must not satisfy the order path.
    ok, reasons = verify_pin(identity, pin)
    assert ok is False
    assert "confirmation required" in reasons[0]

    ok, detail = confirm_pin(actor="owner")
    assert ok is True
    pin, _ = load_pin()
    ok, reasons = verify_pin(identity, pin)
    assert ok is True


def test_pin_rejects_account_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    write_pin(_identity())
    confirm_pin(actor="owner")

    pin, _ = load_pin()
    other = _identity(login=777777, server="Other-Demo")
    ok, reasons = verify_pin(other, pin)
    assert ok is False
    assert any("login mismatch" in r for r in reasons)
    assert any("fingerprint mismatch" in r for r in reasons)


def test_pin_rejects_server_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(tmp_path / "pin.json"))
    write_pin(_identity())
    confirm_pin(actor="owner")
    pin, _ = load_pin()
    ok, reasons = verify_pin(_identity(server="Broker-Live"), pin)
    assert ok is False
    assert any("server mismatch" in r for r in reasons)


def test_unreadable_pin_fails_closed(tmp_path, monkeypatch):
    target = tmp_path / "pin.json"
    target.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_IDENTITY_PIN", str(target))
    pin, reasons = load_pin()
    assert pin is None
    assert "unreadable" in reasons[0]


# ----------------------------------------------------------------- registry


def _registry_doc(entries, **overrides) -> dict:
    doc = {
        "schema": "qts.demo_forward_registry.v1",
        "updated_at": datetime.now(UTC).isoformat(),
        "research_integrity": {
            "optimization_allowed": False,
            "no_forward_fitting": True,
        },
        "entries": entries,
    }
    doc.update(overrides)
    return doc


def _entry_doc(strategy_id: str, status: str = "ELIGIBLE", **overrides) -> dict:
    params = {"lookback": 16}
    doc = {
        "strategy_id": strategy_id,
        "status": status,
        "hypothesis_id": "H-TEST-01",
        "preregistration_artifact": "docs/preregistration_test.json",
        "signal_provider": "tests.fakes_demo_provider:StaticProvider",
        "params": params,
        "params_hash": params_fingerprint(params),
        "size_policy": {"mode": "broker_minimum"},
        "stop_policy": {"required": True},
        "exit_policy": {"max_hold_seconds": 0},
        "allowed_symbols": ["XAUUSD"],
        "broker_symbol": "XAUUSD@",
        "max_orders_per_day": 2,
    }
    doc.update(overrides)
    # Every tradeable entry must carry a complete research/execution policy:
    # registration without a specification is not a registered experiment.
    if doc.get("policy") is None:
        doc["policy"] = policy_block(
            strategy_id=strategy_id,
            params=dict(doc.get("params") or params),
            max_orders_per_day=int(doc.get("max_orders_per_day") or 1),
            allowed_symbols=list(doc.get("allowed_symbols") or ["XAUUSD"]),
        )
    return doc


def test_missing_registry_resolves_to_no_trade(tmp_path, monkeypatch):
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(tmp_path / "missing.json"))
    registry = load_registry()
    entry, reasons = resolve_entry(registry)
    assert entry is None
    assert any("NO_TRADE" in r for r in reasons)


def test_empty_registry_is_no_trade(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(_registry_doc([])), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    status = registry_status()
    assert status["trading_state"] == "NO_TRADE"
    assert status["resolved_strategy"] is None


def test_eligible_entry_resolves(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(_registry_doc([_entry_doc("S1")])), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    registry = load_registry()
    entry, reasons = resolve_entry(registry)
    assert entry is not None and entry.strategy_id == "S1"
    assert reasons == []


def test_non_eligible_status_blocks(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(_registry_doc([_entry_doc("S1", status="NO_TRADE")])), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    registry = load_registry()
    entry, reasons = resolve_entry(registry, "S1")
    assert entry is None
    assert any("not eligible" in r for r in reasons)
    # Without an explicit selection the answer is the same refusal route.
    assert resolve_entry(registry)[0] is None


def test_parameter_drift_in_registry_blocks(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    entry = _entry_doc("S1")
    entry["params"]["lookback"] = 64  # edited after registration, hash not recomputed
    path.write_text(json.dumps(_registry_doc([entry])), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    registry = load_registry()
    resolved, reasons = resolve_entry(registry)
    assert resolved is None
    assert any("params_hash mismatch" in r or "PARAMETER_DRIFT" in r for r in reasons)


def test_multiple_eligible_entries_require_explicit_selection(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(_registry_doc([_entry_doc("S1"), _entry_doc("S2")])), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    registry = load_registry()
    entry, reasons = resolve_entry(registry)
    assert entry is None
    assert any("multiple eligible" in r for r in reasons)
    chosen, _ = resolve_entry(registry, "S2")
    assert chosen is not None and chosen.strategy_id == "S2"


def test_optimization_allowed_registry_is_invalid(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    doc = _registry_doc([_entry_doc("S1")])
    doc["research_integrity"]["optimization_allowed"] = True
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    registry = load_registry()
    assert registry.valid is False
    assert resolve_entry(registry)[0] is None


def test_entry_without_preregistration_blocks(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    entry = _entry_doc("S1")
    entry["preregistration_artifact"] = None
    path.write_text(json.dumps(_registry_doc([entry])), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    entry_resolved, reasons = resolve_entry(load_registry())
    assert entry_resolved is None
    assert any("preregistration" in r for r in reasons)


def test_stop_policy_without_justification_blocks(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    entry = _entry_doc("S1", stop_policy={"required": False})
    path.write_text(json.dumps(_registry_doc([entry])), encoding="utf-8")
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    entry_resolved, reasons = resolve_entry(load_registry())
    assert entry_resolved is None
    assert any("justification" in r for r in reasons)


def test_registry_status_reports_demo_execution_without_a_strategy(tmp_path, monkeypatch):
    """DEMO_EXECUTION may be ENABLED while the trading state stays NO_TRADE."""
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(_registry_doc([_entry_doc("S1", status="RESEARCH")], current_status="NO_TRADE")),
        encoding="utf-8",
    )
    monkeypatch.setenv("QTS_DEMO_REGISTRY", str(path))
    status = registry_status()
    assert status["trading_state"] == "NO_TRADE"
    assert status["registry"]["statuses"] == {"S1": "RESEARCH"}


def test_shipped_registry_ships_no_invented_strategy():
    """The repository's own registry must not ship an unpreregistered edge claim.

    A registered DEMO_FORWARD_RESEARCH_POLICY is allowed (that is how an
    explicitly specified forward experiment is authorised), but only as
    ``ELIGIBLE_DIAGNOSTIC``: fully specified, preregistered, and carrying no
    validated-edge claim. Anything else — an ``ELIGIBLE`` entry without a
    validation artifact, a policy-less entry, a partial policy — is an invented
    strategy and must not ship.
    """
    registry = load_registry()
    assert registry.path.exists()
    assert registry.valid, registry.reasons
    for entry in registry.entries:
        assert entry.hypothesis_id, f"{entry.strategy_id}: no hypothesis — unpreregistered"
        assert entry.preregistration_artifact, f"{entry.strategy_id}: no preregistration artifact"
        artifact = str(entry.preregistration_artifact).split("#", 1)[0]
        assert Path(artifact).exists(), f"{entry.strategy_id}: preregistration artifact {artifact} missing"
        assert entry.policy is not None, f"{entry.strategy_id}: no complete research/execution policy"
        assert entry.policy.policy_class == POLICY_CLASS
        if entry.status == "ELIGIBLE":
            pytest.fail(f"{entry.strategy_id}: registered as ELIGIBLE without a validated edge")
        assert entry.status == "ELIGIBLE_DIAGNOSTIC"
        assert entry.policy.validated_edge is False

    entry, reasons = resolve_entry(registry)
    status = registry_status()
    if registry.entries:
        assert entry is not None, reasons
        assert status["trading_state"] == "TRADING_ELIGIBLE_DIAGNOSTIC"
        assert status["validated_edge"] is False
    else:
        assert entry is None
        assert status["trading_state"] == "NO_TRADE"
        assert any("NO_TRADE" in r for r in reasons)


def test_registered_policy_pins_the_provider_source():
    """The shipped policy's ``code_hash`` must match the provider file on disk.

    The policy is only as immutable as the hash that pins it: if the registered
    hash does not match the source, ``code drift`` detection is decorative.
    """
    import importlib

    registry = load_registry()
    for entry in registry.entries:
        if entry.policy is None or not entry.signal_provider:
            continue
        module_path, _, attr = entry.signal_provider.partition(":")
        module = importlib.import_module(module_path)
        provider_cls = getattr(module, attr)
        import inspect

        source = inspect.getsourcefile(provider_cls)
        assert source is not None
        ok, detail = entry.policy.verify_code_hash(source)
        assert ok, f"{entry.strategy_id}: {detail}"


def test_params_fingerprint_is_deterministic():
    a = params_fingerprint({"b": 1, "a": Decimal("2")})
    b = params_fingerprint({"a": Decimal("2"), "b": 1})
    assert a == b
    assert a != params_fingerprint({"a": Decimal("3"), "b": 1})
