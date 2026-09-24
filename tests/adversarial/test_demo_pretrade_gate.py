"""Adversarial tests for the DEMO pre-trade safety gate.

The single property under test: **the gate passes only when every safeguard
resolves to a definite PASS**. Any missing fact becomes ``UNKNOWN`` and fails;
any violated limit fails with a legible reason. One test per safeguard,
starting from a known-good context and breaking exactly one thing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes_demo_provider import policy_block

from qts.execution.demo_identity import BrokerIdentity, identity_fingerprint
from qts.execution.demo_pretrade import (
    CHECK_PASS,
    DemoPretradeContext,
    run_pretrade_gate,
)
from qts.lifecycle.demo_authorization import document_fingerprint, load_authorization
from qts.lifecycle.demo_policy import validate_policy
from qts.lifecycle.demo_registry import StrategyRegistration, params_fingerprint
from qts.lifecycle.demo_stage import DemoStage

# --------------------------------------------------------------------- helpers


def _identity(**overrides) -> BrokerIdentity:
    base = {
        "login":123456,
        "server":"Broker-Demo",
        "company":"Example Brokers Ltd",
        "account_name":"Research Demo",
        "trade_mode":0,  # DEMO
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


def _spec(**overrides) -> SimpleNamespace:
    base = {
        "symbol":"XAUUSD",
        "contract_size":Decimal("100"),
        "volume_min":Decimal("0.01"),
        "volume_max":Decimal("100"),
        "volume_step":Decimal("0.01"),
        "digits":2,
        "point":Decimal("0.01"),
        "tick_size":Decimal("0.01"),
        "trade_mode":4,
        "trade_allowed":True,
        "filling_mode":1,
        "execution_mode":2,
        "stops_level":0,
        "freeze_level":0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _pin(identity: BrokerIdentity, status: str = "CONFIRMED") -> dict:
    return {
        "schema": "qts.demo_broker_identity_pin.v1",
        "status": status,
        "identity": identity.as_dict(),
        "fingerprint": identity_fingerprint(identity),
    }


def _research_policy(params: dict | None = None, **overrides):
    """A complete, valid research/execution policy for the fixture entry."""
    body = dict(params or {"lookback": 16, "threshold": 0.5})
    pol, problems = validate_policy(
        policy_block(strategy_id="TEST-STRATEGY", params=body, **overrides), body
    )
    assert not problems, problems
    return pol


def _entry(**overrides) -> StrategyRegistration:
    params = {"lookback": 16, "threshold": 0.5}
    base = {
        "strategy_id":"TEST-STRATEGY",
        "status":"ELIGIBLE",
        "hypothesis_id":"H-TEST-01",
        "preregistration_artifact":"docs/preregistration_test.json",
        "signal_provider":"tests.fakes_demo_provider:StaticProvider",
        "params":params,
        "params_hash":params_fingerprint(params),
        "size_policy":{"mode": "broker_minimum"},
        "stop_policy":{"required": True},
        "exit_policy":{"max_hold_seconds": 0},
        "allowed_symbols":["XAUUSD"],
        "max_orders_per_day":2,
        "policy": _research_policy(params),
    }
    base.update(overrides)
    return StrategyRegistration(**base)


def _policy(enabled: bool = True, authorization=None):
    return SimpleNamespace(
        enabled=enabled,
        state="ENABLED_AUTHORIZED" if enabled else "DISABLED BY POLICY",
        reasons=() if enabled else ("no owner authorization",),
        authorization=authorization,
        authorization_id="DEMO-AUTH-TEST" if enabled else None,
    )


def _authorization(tmp_path: Path, **scope_overrides):
    doc = {
        "schema": "qts.demo_execution_authorization.v1",
        "authorization_id": "DEMO-AUTH-TEST",
        "authorized_at": datetime.now(UTC).isoformat(),
        "authorized_by": "test harness",
        "statement": "test",
        "scope": {
            "account_type": "demo",
            "modes_allowed": ["DEMO_EXECUTION"],
            "symbols_allowed": ["XAUUSD"],
            "live_locked": True,
            "real_capital_exposure_usd": 0,
            "funds_transfer_permitted": False,
            "broker_switch_permitted": False,
            "autonomous_order_management": True,
        },
        "expires_at": None,
    }
    doc["scope"].update(scope_overrides)
    doc["integrity"] = {"content_sha256": document_fingerprint(doc)}
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return load_authorization(path)[0]


def _limits() -> SimpleNamespace:
    return SimpleNamespace(
        limits=SimpleNamespace(
            max_quantity=Decimal("0.1"),
            max_exposure_lots=Decimal("0.3"),
            max_notional=Decimal("50000"),
            max_open_orders=3,
            daily_loss_limit=Decimal("50"),
            max_spread_bps=Decimal("30"),
        )
    )


def healthy_ctx(tmp_path: Path, **overrides) -> DemoPretradeContext:
    identity = overrides.pop("identity", _identity())
    entry = overrides.pop("entry", _entry())
    auth = overrides.pop("authorization", _authorization(tmp_path))
    pin = overrides.pop("pin", _pin(identity) if identity is not None else None)
    base = {
        "policy":_policy(authorization=auth),
        "authorization":auth,
        "authority_permitted":True,
        "mode":"DEMO_EXECUTION",
        "stage":DemoStage.STAGE_3_FORWARD_OBSERVATION.value,
        "identity":identity,
        "pin":pin,
        "symbol":"XAUUSD",
        "broker_symbol":"XAUUSD@",
        "symbol_visible":True,
        "symbol_tradable":True,
        "spec":_spec(),
        "order_check_ok":True,
        "order_check_detail":"order_check passed (not execution guarantee)",
        "tick":SimpleNamespace(event_time=datetime.now(UTC)),
        "tick_age_s":1.0,
        "max_tick_age_s":60.0,
        "bid":Decimal("2000.00"),
        "ask":Decimal("2000.20"),
        "spread_bps":1.0,
        "account":SimpleNamespace(equity=Decimal("10000")),
        "open_positions":[],
        "open_orders":[],
        "daily_realized_pnl":Decimal("0"),
        "side":"BUY",
        "intended_lots":Decimal("0.01"),
        "stop_loss":Decimal("1995.00"),
        "stop_required":True,
        "client_order_id":"demo-test-1",
        "idempotency_status":None,
        "kill_switch_active":False,
        "kill_switch_readable":True,
        "kill_switch_self_test":True,
        "reconcile_suspended":False,
        "reconcile_drift":None,
        "last_reconcile_age_s":5.0,
        "adapter_captures_broker_ids":True,
        "journal_ready":True,
        "record_fields_available":dict.fromkeys(_required_fields(), True),
        "entry":entry,
        "strategy_config_hash":(entry.params_hash if entry is not None else None),
        "research_policy":(entry.policy if entry is not None else None),
        "orders_today":0,
        "cumulative_pnl":Decimal("0"),
        "peak_cumulative_pnl":Decimal("0"),
        "now":datetime.now(UTC),
        "limits":_limits(),
    }
    base.update(overrides)
    return DemoPretradeContext(**base)


def _required_fields():
    from qts.execution.demo_pretrade import REQUIRED_RECORD_FIELDS

    return REQUIRED_RECORD_FIELDS


# ----------------------------------------------------------------------- tests


def test_gate_passes_when_every_safeguard_resolves(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path))
    assert verdict.passed, verdict.reasons
    assert not verdict.unknown


def test_missing_identity_is_unknown_and_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, identity=None))
    assert not verdict.passed
    assert "account_is_demo" in verdict.unknown


def test_real_account_is_blocked(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, identity=_identity(trade_mode=2)))
    assert not verdict.passed
    assert "account_is_demo" in verdict.failed
    assert "REAL" in verdict.checks["account_is_demo"].detail


def test_unknown_trade_mode_is_blocked(tmp_path: Path):
    """Absent trade_mode is UNKNOWN — never coerced into 'probably demo'."""
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, identity=_identity(trade_mode=None)))
    assert not verdict.passed
    assert "account_is_demo" in verdict.unknown


def test_contest_account_is_blocked(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, identity=_identity(trade_mode=1)))
    assert not verdict.passed
    assert "CONTEST" in verdict.checks["account_is_demo"].detail


def test_expert_disabled_account_is_blocked(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, identity=_identity(trade_expert=False)))
    assert not verdict.passed
    assert "account_is_demo" in verdict.failed


def test_unpinned_identity_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, pin=None))
    assert not verdict.passed
    assert "broker_identity_verified" in verdict.failed


def test_pin_pending_owner_review_blocks(tmp_path: Path):
    identity = _identity()
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, pin=_pin(identity, status="PENDING_REVIEW")))
    assert not verdict.passed
    assert "broker_identity_verified" in verdict.failed
    assert "confirmation required" in verdict.checks["broker_identity_verified"].detail


def test_pin_mismatch_blocks_account_switch(tmp_path: Path):
    """Terminal pointed at another account: the pin no longer matches."""
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, identity=_identity(login=999999), pin=_pin(_identity())))
    assert not verdict.passed
    assert "broker_identity_verified" in verdict.failed


def test_missing_symbol_mapping_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, broker_symbol=None))
    assert not verdict.passed
    assert "symbol_mapping_canonical" in verdict.failed


def test_stale_tick_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, tick_age_s=300.0))
    assert not verdict.passed
    assert "market_data_fresh" in verdict.failed


def test_unknown_tick_age_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, tick_age_s=None))
    assert not verdict.passed
    assert "market_data_fresh" in verdict.unknown


def test_wide_spread_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, spread_bps=95.0))
    assert not verdict.passed
    assert "spread_available" in verdict.failed


def test_oversize_order_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, intended_lots=Decimal("5.0")))
    assert not verdict.passed
    assert "order_size_within_hard_max" in verdict.failed


def test_off_step_size_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, intended_lots=Decimal("0.015")))
    assert not verdict.passed
    assert "order_size_within_hard_max" in verdict.failed


def test_missing_stop_loss_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, stop_loss=None))
    assert not verdict.passed
    assert "stop_loss_present" in verdict.failed


def test_stop_on_wrong_side_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, stop_loss=Decimal("2010.00")))
    assert not verdict.passed
    assert "stop_loss_present" in verdict.failed


def test_stop_too_close_to_price_blocks(tmp_path: Path):
    spec = _spec(stops_level=100)  # 100 points * 0.01 = $1.00 minimum distance
    verdict = run_pretrade_gate(
        healthy_ctx(tmp_path, spec=spec, stop_loss=Decimal("1999.90"), bid=Decimal("2000.00"), ask=Decimal("2000.20"))
    )
    assert not verdict.passed
    assert "stop_loss_present" in verdict.failed
    assert "stops_level" in verdict.checks["stop_loss_present"].detail


def test_daily_loss_limit_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, daily_realized_pnl=Decimal("-75")))
    assert not verdict.passed
    assert "max_daily_loss" in verdict.failed


def test_unknown_daily_pnl_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, daily_realized_pnl=None))
    assert not verdict.passed
    assert "max_daily_loss" in verdict.unknown


def test_exposure_cap_blocks(tmp_path: Path):
    open_positions = [SimpleNamespace(quantity=Decimal("0.30"), instrument=SimpleNamespace(symbol="XAUUSD"))]
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, open_positions=open_positions))
    assert not verdict.passed
    assert "max_total_exposure" in verdict.failed


def test_position_cap_blocks(tmp_path: Path):
    open_positions = [
        SimpleNamespace(quantity=Decimal("0.01"), instrument=SimpleNamespace(symbol="XAUUSD")) for _ in range(3)
    ]
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, open_positions=open_positions))
    assert not verdict.passed
    assert "max_simultaneous_positions" in verdict.failed


def test_duplicate_client_order_id_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, idempotency_status="FILLED"))
    assert not verdict.passed
    assert "duplicate_order_protection" in verdict.failed


def test_recent_order_rate_blocks(tmp_path: Path):
    import time

    verdict = run_pretrade_gate(healthy_ctx(tmp_path, recent_order_epochs=[time.time() - 1.0]))
    assert not verdict.passed
    assert "duplicate_order_protection" in verdict.failed


def test_active_kill_switch_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, kill_switch_active=True, kill_switch_detail="operator"))
    assert not verdict.passed
    assert "kill_switch_functional" in verdict.failed


def test_unreadable_kill_switch_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, kill_switch_readable=False))
    assert not verdict.passed
    assert "kill_switch_functional" in verdict.unknown


def test_unproven_kill_switch_blocks(tmp_path: Path):
    """A switch that has not been exercised this cycle cannot be trusted."""
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, kill_switch_self_test=None))
    assert not verdict.passed
    assert "kill_switch_functional" in verdict.unknown


def test_reconciliation_suspension_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, reconcile_suspended=True, reconcile_drift="POSITION_MISMATCH"))
    assert not verdict.passed
    assert "reconciliation_ready" in verdict.failed


def test_missing_reconciliation_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, last_reconcile_age_s=None))
    assert not verdict.passed
    assert "reconciliation_ready" in verdict.unknown


def test_stale_reconciliation_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, last_reconcile_age_s=5000.0))
    assert not verdict.passed
    assert "reconciliation_ready" in verdict.failed


def test_missing_broker_id_capture_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, adapter_captures_broker_ids=False))
    assert not verdict.passed
    assert "broker_reference_capture" in verdict.failed


def test_incomplete_recorder_blocks(tmp_path: Path):
    fields = dict.fromkeys(_required_fields(), True)
    fields["slippage_bps"] = False
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, record_fields_available=fields))
    assert not verdict.passed
    assert "execution_record_fields" in verdict.failed


def test_unregistered_strategy_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, entry=None))
    assert not verdict.passed
    assert "strategy_registered_frozen" in verdict.failed
    assert "NO_TRADE" in verdict.checks["strategy_registered_frozen"].detail


def test_parameter_drift_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, strategy_config_hash="deadbeefcafe"))
    assert not verdict.passed
    assert "strategy_registered_frozen" in verdict.failed
    assert "drift" in verdict.checks["strategy_registered_frozen"].detail


def test_stage_disabled_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, stage=DemoStage.STAGE_1_CONNECTIVITY.value))
    assert not verdict.passed
    assert "stage_allows_order" in verdict.failed


def test_halted_stage_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, stage=DemoStage.HALTED.value))
    assert not verdict.passed
    assert "stage_allows_order" in verdict.failed


def test_unauthorized_policy_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, policy=_policy(enabled=False), authorization=None))
    assert not verdict.passed
    assert "authorization_valid" in verdict.failed


def test_authority_refusal_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(
        healthy_ctx(tmp_path, authority_permitted=False, authority_reasons=["readiness expired"])
    )
    assert not verdict.passed
    assert "execution_permission" in verdict.failed


def test_live_mode_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, mode="LIVE"))
    assert not verdict.passed
    assert "mode_is_demo_execution" in verdict.failed


def test_autonomous_without_scope_blocks(tmp_path: Path):
    auth = _authorization(tmp_path, autonomous_order_management=False)
    verdict = run_pretrade_gate(
        healthy_ctx(tmp_path, authorization=auth, policy=_policy(authorization=auth), autonomous=True)
    )
    assert not verdict.passed
    assert "autonomous_allowed" in verdict.failed


def test_unknown_checks_are_reported_as_a_blocking_failure(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, kill_switch_self_test=None))
    assert "no_unknown_checks" in verdict.failed
    assert "kill_switch_functional" in verdict.checks["no_unknown_checks"].detail


def test_verdict_reports_every_check_status(tmp_path: Path):
    verdict = run_pretrade_gate(healthy_ctx(tmp_path))
    assert all(c.status == CHECK_PASS for c in verdict.checks.values())
    # 21 safeguards + contract checks; the count is asserted so an accidental
    # removal of a check cannot pass silently.
    assert len(verdict.checks) >= 21


@pytest.mark.parametrize("field", ["identity", "spec", "limits", "entry"])
def test_no_silent_defaults_for_critical_facts(tmp_path: Path, field: str):
    """Dropping a critical fact must refuse, never fall back to a guess."""
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, **{field: None}))
    assert not verdict.passed
    assert verdict.unknown or verdict.failed


# ------------------------------------------------- registered-policy enforcement


def _policy_ctx(tmp_path: Path, **policy_overrides) -> DemoPretradeContext:
    """Healthy context whose entry carries a policy built with ``**overrides``."""
    entry = _entry(policy=_research_policy({"lookback": 16, "threshold": 0.5}, **policy_overrides))
    return healthy_ctx(tmp_path, entry=entry)


def test_policy_tightens_the_canonical_spread_cap(tmp_path: Path):
    # The canonical DEMO cap is 30 bps; the policy declares 2 bps. A 1 bps
    # spread passes a 4 bps spread must fail against the POLICY cap, not the
    # canonical one. Registration may only tighten, never loosen.
    verdict = run_pretrade_gate(_policy_ctx(tmp_path, max_spread_bps=2.0))
    assert verdict.passed, verdict.reasons

    wider = healthy_ctx(
        tmp_path,
        entry=_entry(policy=_research_policy({"lookback": 16}, max_spread_bps=2.0)),
        bid=Decimal("2000.00"),
        ask=Decimal("2000.80"),
        spread_bps=4.0,
    )
    verdict = run_pretrade_gate(wider)
    assert not verdict.passed
    assert "spread_available" in verdict.failed
    assert "2.0bps" in verdict.checks["spread_available"].detail


def test_policy_symbol_restriction_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(_policy_ctx(tmp_path, allowed_symbols=["EURUSD"]))
    assert not verdict.passed
    assert "symbol_allowed_by_policy" in verdict.failed


def test_policy_trading_hours_block_outside_the_declared_window(tmp_path: Path):
    # Exclude today AND the next two days: a midnight crossing during the run
    # still lands on an excluded day, so the test never depends on the clock.
    now = datetime.now(UTC)
    excluded = {now.strftime("%a").upper()}
    for offset in (1, 2):
        excluded.add(datetime.fromtimestamp(now.timestamp() + offset * 86400, UTC).strftime("%a").upper())
    days = [d for d in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN") if d not in excluded]
    verdict = run_pretrade_gate(
        _policy_ctx(
            tmp_path,
            allowed_trading_hours={
                "timezone": "UTC",
                "sessions": [{"days": days, "start": "00:00", "end": "23:59"}],
            },
        )
    )
    assert not verdict.passed
    assert "trading_hours_allowed" in verdict.failed


def test_policy_trading_hours_pass_inside_the_declared_window(tmp_path: Path):
    # 2026-09-24 is a Thursday; the fixture entry's policy is all-week, so this
    # asserts the positive path with an explicit moment inside a narrow window.
    verdict = run_pretrade_gate(
        healthy_ctx(
            tmp_path,
            entry=_entry(
                policy=_research_policy(
                    {"lookback": 16},
                    allowed_trading_hours={
                        "timezone": "UTC",
                        "sessions": [{"days": ["THU"], "start": "08:00", "end": "16:00"}],
                    },
                )
            ),
            now=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )
    )
    assert verdict.passed, verdict.reasons


def test_policy_daily_order_budget_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(_policy_ctx(tmp_path, max_orders_per_day=1))
    assert verdict.passed  # 0 of 1 used
    used = healthy_ctx(
        tmp_path,
        entry=_entry(policy=_research_policy({"lookback": 16}, max_orders_per_day=1)),
        orders_today=1,
    )
    verdict = run_pretrade_gate(used)
    assert not verdict.passed
    assert "order_frequency_within_policy" in verdict.failed


def test_policy_drawdown_blocks(tmp_path: Path):
    verdict = run_pretrade_gate(
        healthy_ctx(
            tmp_path,
            entry=_entry(policy=_research_policy({"lookback": 16}, max_drawdown=10.0)),
            peak_cumulative_pnl=Decimal("5"),
            cumulative_pnl=Decimal("-6"),
        )
    )
    assert not verdict.passed
    assert "max_drawdown_within_policy" in verdict.failed


def test_policy_drawdown_passes_within_the_limit(tmp_path: Path):
    verdict = run_pretrade_gate(
        healthy_ctx(
            tmp_path,
            entry=_entry(policy=_research_policy({"lookback": 16}, max_drawdown=10.0)),
            peak_cumulative_pnl=Decimal("5"),
            cumulative_pnl=Decimal("-1"),
        )
    )
    assert verdict.passed, verdict.reasons


def test_policy_stale_data_cap_tightens_the_tick_age(tmp_path: Path):
    verdict = run_pretrade_gate(
        healthy_ctx(
            tmp_path,
            entry=_entry(policy=_research_policy({"lookback": 16}, stale_data_protection={"max_tick_age_s": 2.0, "on_stale": "NO_TRADE"})),
            tick_age_s=3.0,
            max_tick_age_s=60.0,
        )
    )
    assert not verdict.passed
    assert "market_data_fresh" in verdict.failed


def test_policy_min_order_interval_tightens_the_duplicate_guard(tmp_path: Path):
    from datetime import timedelta

    recent = (datetime.now(UTC) - timedelta(seconds=30)).timestamp()
    verdict = run_pretrade_gate(
        healthy_ctx(
            tmp_path,
            entry=_entry(policy=_research_policy({"lookback": 16}, min_order_interval_s=900)),
            recent_order_epochs=[recent],
        )
    )
    assert not verdict.passed
    assert "duplicate_order_protection" in verdict.failed


def test_policy_required_checks_must_actually_pass(tmp_path: Path):
    """A policy may declare extra mandatory checks; they must resolve to PASS."""
    verdict = run_pretrade_gate(
        healthy_ctx(
            tmp_path,
            entry=_entry(
                policy=_research_policy(
                    {"lookback": 16},
                    min_data_requirements={
                        "requires_historical_dataset": False,
                        "required_checks": ["broker_reference_capture"],
                    },
                )
            ),
            journal_ready=False,
        )
    )
    assert not verdict.passed
    assert "policy_execution_assumptions" in verdict.failed


def test_entry_without_a_policy_is_refused_by_the_gate(tmp_path: Path):
    entry = _entry(policy=None)
    assert entry.policy is None
    verdict = run_pretrade_gate(healthy_ctx(tmp_path, entry=entry))
    assert not verdict.passed
    assert "policy_complete" in verdict.failed
