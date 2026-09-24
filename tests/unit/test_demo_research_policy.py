"""The registered DEMO research/execution policy is complete or it is refused.

The property under test: a policy is only accepted when every mandated field
is present, well-formed, and internally consistent. A half-specified policy is
not tightened up with defaults — it is refused, because a policy finished after
the first result is not a preregistered experiment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes_demo_provider import policy_block

from qts.lifecycle.demo_policy import (
    KILL_CONDITION_VOCABULARY,
    POLICY_CLASS,
    ResearchPolicy,
    validate_policy,
)
from qts.lifecycle.demo_registry import params_fingerprint

PARAMS = {"lookback": 16}


def _policy(**overrides) -> tuple[ResearchPolicy | None, list[str]]:
    block = policy_block(params=PARAMS)
    block.update(overrides)
    return validate_policy(block, PARAMS)


def _valid(**overrides) -> ResearchPolicy:
    pol, problems = _policy(**overrides)
    assert pol is not None, problems
    return pol


# ------------------------------------------------------------------ acceptance


def test_complete_policy_is_accepted():
    pol, problems = _policy()
    assert pol is not None, problems
    assert problems == []
    assert pol.policy_class == POLICY_CLASS
    assert pol.validated_edge is False


def test_every_required_field_is_present_in_the_fixture():
    from qts.lifecycle.demo_policy import REQUIRED_POLICY_FIELDS

    block = policy_block(params=PARAMS)
    for name in REQUIRED_POLICY_FIELDS:
        if name == "data_hash":
            continue  # legitimately absent when no historical dataset is used
        assert name in block, name
        assert block[name] not in (None, "", [], {}), name


# ------------------------------------------------------------------- refusal


@pytest.mark.parametrize(
    "field",
    [
        "policy_id",
        "version",
        "created_at",
        "signal_logic",
        "entry_conditions",
        "exit_conditions",
        "stop_loss_logic",
        "position_sizing",
        "max_daily_loss",
        "max_drawdown",
        "max_orders_per_day",
        "allowed_symbols",
        "allowed_trading_hours",
        "max_spread_bps",
        "execution_delay_assumption_ms",
        "min_data_requirements",
        "stale_data_protection",
        "duplicate_order_protection",
        "kill_conditions",
        "reconciliation_requirements",
        "code_hash",
        "config_hash",
        "edge_statement",
    ],
)
def test_missing_required_field_is_refused(field: str):
    block = policy_block(params=PARAMS)
    block.pop(field)
    pol, problems = validate_policy(block, PARAMS)
    assert pol is None
    assert any(field in p for p in problems)


def test_validated_edge_requires_an_existing_artifact():
    pol, problems = _policy(validated_edge=True)
    assert pol is None
    assert any("validation_artifact" in p for p in problems)

    pol, problems = _policy(validated_edge=True, validation_artifact="docs/does-not-exist.md")
    assert pol is None
    assert any("does not exist" in p for p in problems)


def test_validated_edge_with_a_real_artifact_is_accepted(tmp_path: Path):
    artifact = tmp_path / "validation.md"
    artifact.write_text("# validation evidence\n", encoding="utf-8")
    pol = _valid(validated_edge=True, validation_artifact=str(artifact))
    assert pol.validated_edge is True


def test_edge_statement_must_disclaim_an_edge():
    pol, problems = _policy(edge_statement="this policy is profitable in DEMO and should be scaled")
    assert pol is None
    assert any("disclaimer" in p for p in problems)


def test_edge_statement_must_be_more_than_a_soundbite():
    pol, problems = _policy(edge_statement="no edge")
    assert pol is None
    assert any("too short" in p for p in problems)


def test_unknown_kill_condition_is_refused_rather_than_ignored():
    pol, problems = _policy(kill_conditions=["daily_loss_limit", "stp_loss_typo"])
    assert pol is None
    assert any("unknown kill condition" in p for p in problems)
    assert "stp_loss_typo" not in KILL_CONDITION_VOCABULARY


def test_non_positive_limits_are_refused():
    for field in ("max_daily_loss", "max_drawdown", "max_simultaneous_exposure_lots", "max_spread_bps"):
        pol, problems = _policy(**{field: 0})
        assert pol is None, field
        assert any(field in p for p in problems)


def test_position_sizing_above_the_exposure_cap_is_refused():
    pol, problems = _policy(position_sizing={"mode": "fixed", "lots": 5.0}, max_simultaneous_exposure_lots=0.01)
    assert pol is None
    assert any("max_simultaneous_exposure_lots" in p for p in problems)


def test_stop_without_a_computable_distance_is_refused():
    pol, problems = _policy(stop_loss_logic={"required": True})
    assert pol is None
    assert any("distance_price" in p for p in problems)


def test_time_exit_is_mandatory():
    pol, problems = _policy(exit_conditions={"max_hold_seconds": 0})
    assert pol is None
    assert any("max_hold_seconds" in p for p in problems)


def test_config_hash_must_match_the_registered_params():
    pol, problems = validate_policy(policy_block(params=PARAMS), {"lookback": 32})
    assert pol is None
    assert any("config_hash" in p for p in problems)


def test_hashes_must_be_sha256_hex():
    pol, problems = _policy(code_hash="not-a-hash")
    assert pol is None
    assert any("code_hash" in p for p in problems)


def test_historical_dataset_requires_a_data_hash():
    pol, problems = _policy(
        min_data_requirements={"requires_historical_dataset": True, "required_checks": ["market_data_fresh"]}
    )
    assert pol is None
    assert any("data_hash" in p for p in problems)


def test_malformed_trading_hours_are_refused():
    pol, problems = _policy(
        allowed_trading_hours={"timezone": "UTC", "sessions": [{"days": ["FUNDAY"], "start": "08:00", "end": "16:00"}]}
    )
    assert pol is None
    assert any("days" in p for p in problems)

    pol, problems = _policy(
        allowed_trading_hours={"timezone": "UTC", "sessions": [{"days": ["MON"], "start": "16:00", "end": "08:00"}]}
    )
    assert pol is None
    assert any("start must be before end" in p for p in problems)

    pol, problems = _policy(allowed_trading_hours={"timezone": "America/New_York", "sessions": [{"days": ["MON"], "start": "08:00", "end": "16:00"}]})
    assert pol is None
    assert any("timezone" in p for p in problems)


def test_reconciliation_and_idempotency_covenants_are_mandatory():
    pol, problems = _policy(reconciliation_requirements={"after_every_order": False, "max_age_s": 60, "on_drift": "HALT"})
    assert pol is None
    assert any("after_every_order" in p for p in problems)

    pol, problems = _policy(duplicate_order_protection={"idempotency_required": False, "min_order_interval_s": 0})
    assert pol is None
    assert any("idempotency_required" in p for p in problems)


def test_wrong_policy_class_is_refused():
    pol, problems = _policy(policy_class="VALIDATED_LIVE_STRATEGY")
    assert pol is None
    assert any("policy_class" in p for p in problems)


def test_a_policy_missing_several_fields_reports_every_problem():
    block = policy_block(params=PARAMS)
    block.pop("max_daily_loss")
    block.pop("kill_conditions")
    block["version"] = "v1"
    pol, problems = validate_policy(block, PARAMS)
    assert pol is None
    assert len(problems) >= 3


# -------------------------------------------------------------- runtime helpers


def test_symbol_authorisation():
    pol = _valid(allowed_symbols=["XAUUSD"])
    assert pol.allows_symbol("XAUUSD")
    assert pol.allows_symbol("xauusd")
    assert not pol.allows_symbol("EURUSD")
    assert not pol.allows_symbol(None)


def test_trading_hours_window(tmp_path: Path):
    pol = _valid(
        allowed_trading_hours={
            "timezone": "UTC",
            "sessions": [{"days": ["MON", "TUE", "WED", "THU", "FRI"], "start": "08:00", "end": "16:00"}],
        }
    )
    inside = datetime(2026, 9, 24, 12, 30, tzinfo=UTC)  # Thursday
    assert pol.within_trading_hours(inside)
    assert not pol.within_trading_hours(datetime(2026, 9, 24, 7, 59, tzinfo=UTC))
    assert not pol.within_trading_hours(datetime(2026, 9, 24, 16, 0, tzinfo=UTC))
    # Saturday: not in the declared days even though the time would fit
    assert not pol.within_trading_hours(datetime(2026, 9, 26, 12, 0, tzinfo=UTC))


def test_kill_conditions_map_to_failed_gate_checks():
    pol = _valid(kill_conditions=["daily_loss_limit", "max_drawdown", "market_data_stale"])
    assert pol.must_kill_on(["max_daily_loss"]) == ("daily_loss_limit",)
    assert pol.must_kill_on(["market_data_fresh", "max_daily_loss"]) == ("daily_loss_limit", "market_data_stale")
    # A routine limit the policy did not list as a kill condition must NOT kill
    assert pol.must_kill_on(["spread_available"]) == ()


def test_code_drift_is_detected(tmp_path: Path):
    pol = _valid()
    source = tmp_path / "provider.py"
    source.write_text("# original registered source\n", encoding="utf-8")
    ok, detail = pol.verify_code_hash(source)
    assert not ok

    import hashlib

    pol2 = _valid(code_hash=hashlib.sha256(source.read_bytes()).hexdigest())
    ok, detail = pol2.verify_code_hash(source)
    assert ok, detail


def test_policy_contents_cannot_be_retuned_after_registration():
    """A frozen dataclass wrapping a mutable dict is not frozen.

    The hash covers what was *registered*; if the object stayed mutable a
    caller could retune a limit in memory and the gate would read the edited
    value while the hash still matched. The policy must be read-only.
    """
    pol = _valid()
    snapshot = dict(pol.raw)
    with pytest.raises(TypeError):
        pol.raw["max_daily_loss"] = 100000  # type: ignore[index]
    with pytest.raises(TypeError):
        pol.raw["stop_loss_logic"]["distance_price"] = 0.01  # type: ignore[index]
    assert dict(pol.raw) == snapshot
    assert pol.config_hash == params_fingerprint(PARAMS)
