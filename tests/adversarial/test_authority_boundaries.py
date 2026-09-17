"""Adversarial: mode authority + unified risk authority boundaries.

* Unknown/ambiguous mode selections fail closed (never default to DEVELOPMENT
  silently).
* Mode restrictions can only TIGHTEN the canonical base.
* Loosening overrides are rejected without explicit risk approval.
* DEMO_FORWARD is structurally incapable of broker order submission.
* The demo boundary table and env transitions are coherent.
"""

from __future__ import annotations

import pytest

from qts.domain.modes import ExecutionMode, ModeResolutionError, resolve_mode
from qts.risk.authority import MODE_RESTRICTIONS, resolve_risk_limits
from qts.risk.demo_limits import DEMO_FORWARD_DEFAULTS, SAFETY_BOUNDARY, assert_demo_limits, env_boundary_check

# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------


def test_unknown_explicit_mode_fails_closed(monkeypatch):
    monkeypatch.delenv("QTS_MODE", raising=False)
    monkeypatch.delenv("QTS_ENV", raising=False)
    with pytest.raises(ModeResolutionError):
        resolve_mode("banana-mode")


def test_unknown_env_var_fails_closed(monkeypatch):
    monkeypatch.setenv("QTS_ENV", "staging")  # a plausible typo — must NOT silently resolve
    monkeypatch.delenv("QTS_MODE", raising=False)
    with pytest.raises(ModeResolutionError):
        resolve_mode()


def test_no_selection_defaults_to_development(monkeypatch):
    monkeypatch.delenv("QTS_MODE", raising=False)
    monkeypatch.delenv("QTS_ENV", raising=False)
    assert resolve_mode() is ExecutionMode.DEVELOPMENT


def test_legacy_env_aliases_map_to_exactly_one_mode(monkeypatch):
    monkeypatch.delenv("QTS_MODE", raising=False)
    for env_value, expected in [
        ("dev", ExecutionMode.DEVELOPMENT),
        ("development", ExecutionMode.DEVELOPMENT),
        ("paper", ExecutionMode.PAPER),
        ("shadow", ExecutionMode.SHADOW),
        ("demo_forward", ExecutionMode.DEMO_FORWARD),
        ("demo", ExecutionMode.DEMO_FORWARD),
        ("live", ExecutionMode.LIVE),
    ]:
        monkeypatch.setenv("QTS_ENV", env_value)
        assert resolve_mode() is expected, env_value


def test_mode_capability_matrix():
    # The structural capability matrix: only DEMO_EXECUTION and LIVE may
    # reach broker order submission; DEMO_FORWARD never can.
    assert not ExecutionMode.DEVELOPMENT.can_submit_broker_orders
    assert not ExecutionMode.PAPER.can_submit_broker_orders
    assert not ExecutionMode.SHADOW.can_submit_broker_orders
    assert not ExecutionMode.DEMO_FORWARD.can_submit_broker_orders
    assert ExecutionMode.DEMO_EXECUTION.can_submit_broker_orders
    assert ExecutionMode.LIVE.can_submit_broker_orders
    assert not ExecutionMode.DEMO_FORWARD.is_money_at_risk
    assert ExecutionMode.LIVE.is_money_at_risk


def test_mode_report_surfaces_resolution_error(monkeypatch):
    from qts.domain.modes import effective_mode_report

    monkeypatch.setenv("QTS_ENV", "nonsense")
    rpt = effective_mode_report()
    assert rpt["effective_mode"] == "DEVELOPMENT"  # fail-safe capability
    assert rpt["resolution_error"]  # ...but the error is LOUD, not silent


# ---------------------------------------------------------------------------
# Risk authority unity
# ---------------------------------------------------------------------------


def test_mode_restrictions_never_loosen_base():
    from decimal import Decimal

    base = resolve_risk_limits(ExecutionMode.DEVELOPMENT).limits
    for mode, overrides in MODE_RESTRICTIONS.items():
        snap = resolve_risk_limits(mode)
        for key in overrides:
            base_v = getattr(base, key)
            got_v = getattr(snap.limits, key)
            if isinstance(base_v, (int, Decimal)) and not isinstance(base_v, bool):
                assert Decimal(str(got_v)) <= Decimal(str(base_v)), f"{mode.value}.{key}={got_v} loosens base {base_v}"


def test_demo_limits_match_the_risk_authority():
    """The demo boundary must be DERIVED from, and equal to, the authority."""
    demo_snap = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    assert DEMO_FORWARD_DEFAULTS.max_volume_per_order == float(demo_snap.limits.max_quantity)
    assert DEMO_FORWARD_DEFAULTS.max_simultaneous_exposure == float(demo_snap.limits.max_exposure_lots)
    assert DEMO_FORWARD_DEFAULTS.max_spread_bps == float(demo_snap.limits.max_spread_bps)
    assert DEMO_FORWARD_DEFAULTS.max_daily_loss_usd == float(demo_snap.limits.daily_loss_limit)
    assert DEMO_FORWARD_DEFAULTS.max_open_orders == demo_snap.limits.max_open_orders
    assert DEMO_FORWARD_DEFAULTS.kill_switch_enabled is True


def test_demo_limits_are_conservative_vs_base():
    base = resolve_risk_limits(ExecutionMode.DEVELOPMENT).limits
    demo = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION).limits
    assert demo.max_quantity < base.max_quantity
    assert demo.max_exposure_lots < base.max_exposure_lots
    assert demo.daily_loss_limit < base.daily_loss_limit
    assert demo.max_spread_bps < base.max_spread_bps


def test_loosening_override_rejected_without_approval(monkeypatch):
    monkeypatch.delenv("QTS_RISK_LOOSEN_ACK", raising=False)
    snap = resolve_risk_limits(
        ExecutionMode.DEMO_EXECUTION,
        config_overrides={"max_quantity": 10.0},  # attempts to loosen 0.1 -> 10
    )
    assert snap.limits.max_quantity == demo_default_max_qty()
    assert any("REJECTED" in w for w in snap.warnings)


def demo_default_max_qty():
    from decimal import Decimal

    return Decimal("0.1")


def test_tightening_override_always_allowed():
    snap = resolve_risk_limits(
        ExecutionMode.DEMO_EXECUTION,
        config_overrides={"max_quantity": 0.01},  # tighter
    )
    assert str(snap.limits.max_quantity) == "0.01"
    assert snap.sources["max_quantity"] == "config_override"


def test_unknown_override_key_is_ignored_with_warning():
    snap = resolve_risk_limits(ExecutionMode.PAPER, config_overrides={"make_me_rich": True})
    assert any("unknown" in w for w in snap.warnings)
    assert "make_me_rich" not in snap.overrides_applied


def test_resolved_snapshot_is_stable_and_hashed():
    a = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    b = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    assert a.config_hash == b.config_hash  # deterministic
    c = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION, config_overrides={"max_quantity": 0.05})
    assert c.config_hash != a.config_hash  # different effective config -> different lineage


# ---------------------------------------------------------------------------
# Demo boundary helpers
# ---------------------------------------------------------------------------


def test_assert_demo_limits_enforces_authority_values():
    ok, _ = assert_demo_limits(volume=0.1, exposure=0.3, spread_bps=30, slippage_bps=20)
    assert ok
    bad, why = assert_demo_limits(volume=0.2, exposure=0.0, spread_bps=0, slippage_bps=0)
    assert not bad and "volume" in why
    bad2, why2 = assert_demo_limits(volume=0.0, exposure=0.0, spread_bps=31, slippage_bps=0)
    assert not bad2 and "spread" in why2


def test_env_boundary_blocks_silent_mode_transitions():
    ok, _ = env_boundary_check("development", "live")
    assert not ok
    ok2, _ = env_boundary_check("demo_forward", "live")
    assert not ok2
    ok3, _ = env_boundary_check("demo_forward", "DEMO_FORWARD")
    assert ok3
    ok4, why4 = env_boundary_check("totally-unknown-env", "paper")
    assert not ok4 and "unknown" in why4


def test_safety_boundary_documented_modes_are_complete():
    for mode in ("DEVELOPMENT", "PAPER", "SHADOW", "DEMO_FORWARD", "DEMO_EXECUTION", "LIVE"):
        assert mode in SAFETY_BOUNDARY, f"boundary table missing {mode}"
    assert "never LIVE" in SAFETY_BOUNDARY["DEMO_EXECUTION"] or "LIVE" in SAFETY_BOUNDARY["DEMO_EXECUTION"]


# ---------------------------------------------------------------------------
# Live gate proof tiers (finding #20): mock evidence is not connectivity proof
# ---------------------------------------------------------------------------


def test_live_gate_connectivity_never_passes_on_mocks(monkeypatch, tmp_path):
    """Without a real terminal, connectivity must FAIL with an honest reason —
    the old MagicMock-based check (which returned PASS in every dev
    environment) is banned as live-gate evidence."""
    # Simulate a dev environment without MetaTrader5 installed
    import builtins

    from qts.lifecycle import live_gate

    real_import = builtins.__import__

    def _no_mt5(name, *a, **k):
        if name == "MetaTrader5":
            raise ImportError("MetaTrader5 not installed (simulated dev env)")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_mt5)
    ok, detail = live_gate.check_mt5_connectivity()
    assert ok is False
    assert "UNAVAILABLE" in detail or "not installed" in detail


def test_live_report_exposes_proof_tiers():
    from qts.lifecycle.live_gate import live_readiness_report

    rpt = live_readiness_report()
    assert "proof_tiers" in rpt
    assert rpt["proof_tiers"]["mt5_connectivity"] == "real_environment"
    assert "mock" in rpt["tier_note"].lower()
    # connectivity is a hard blocker unless a REAL terminal answered
    if not rpt["mt5_connectivity"]["passed"]:
        assert "mt5_connectivity" in rpt["blocked_reasons"]
