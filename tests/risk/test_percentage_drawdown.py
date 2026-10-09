"""Percentage drawdown is a real, enforced limit — end to end.

Why these tests exist
---------------------
The owner authorization artifact states ``risk_ceiling.max_drawdown_pct: 5``,
but the canonical risk model only ever had an absolute USD drawdown cap. The
percentage was therefore either unknown (rejected by the validator, which kept
DEMO execution disabled) or, worse, silently dropped.

A fixed dollar cap is not scale invariant: a 100 USD drawdown is a rounding
error on a 100,000 USD account and a catastrophe on a 2,000 USD one. The
percentage cap is enforced IN ADDITION to the dollar cap, never instead of it,
and an unmeasurable percentage blocks rather than reads as 0%.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from qts.domain.modes import ExecutionMode
from qts.domain.value_objects import Account, Fill, Instrument, OrderIntent, Side
from qts.risk.authority import (
    BASE_LIMITS,
    apply_risk_ceiling,
    engine_limits_from,
    resolve_risk_limits,
)
from qts.risk.engine import RiskContext, RiskEngine, RiskLimits


def _ctx(
    *,
    equity: Decimal = Decimal("10000"),
    drawdown: Decimal = Decimal("0"),
    peak_equity: Decimal | None = None,
    drawdown_pct: Decimal | None = None,
    price: Decimal = Decimal("2000"),
) -> RiskContext:
    return RiskContext(
        account=Account(
            balance=equity,
            equity=equity,
            currency="USD",
            updated_at=datetime.now(UTC),
        ),
        positions={},
        open_orders_count=0,
        daily_pnl=Decimal("0"),
        drawdown=drawdown,
        peak_equity=peak_equity,
        drawdown_pct=drawdown_pct,
        instrument_suspended=set(),
        reference_prices={"XAUUSD": price},
    )


def _intent(qty: str = "0.1") -> OrderIntent:
    return OrderIntent(
        instrument=Instrument(symbol="XAUUSD"),
        side=Side.BUY,
        quantity=Decimal(qty),
        client_order_id="pct-dd-1",
        strategy_id="pct-dd",
    )


def _engine(**overrides: object) -> RiskEngine:
    tmp = tempfile.mkdtemp()
    limits = RiskLimits(**overrides)  # type: ignore[arg-type]
    return RiskEngine(limits, db_path=Path(tmp) / "risk.sqlite", persist_kill=True)


# --------------------------------------------------------------- canonical


def test_canonical_base_defines_a_percentage_cap():
    """The canonical limit set states a percentage cap, not just dollars."""
    pct = BASE_LIMITS.max_drawdown_pct
    assert pct > 0
    assert pct <= 100


def test_canonical_percentage_cap_rejects_non_percentages():
    """0 or >100 is a unit mistake, not a limit — fail closed at construction."""
    from pydantic import ValidationError

    for bad in (Decimal("0"), Decimal("-5"), Decimal("101"), Decimal("5000")):
        with pytest.raises(ValidationError):
            RiskLimits(max_drawdown_pct=bad)
        with pytest.raises(ValidationError):
            from qts.risk.authority import CanonicalRiskLimits

            CanonicalRiskLimits(max_drawdown_pct=bad)


# ------------------------------------------------------------- measurement


def test_zero_dollar_drawdown_is_zero_percent_even_without_a_peak():
    """drawdown == 0 is 0% at any positive peak — arithmetic, not an assumption."""
    ctx = _ctx(drawdown=Decimal("0"), peak_equity=None)
    assert ctx.measured_drawdown_pct() == Decimal("0")


def test_nonzero_drawdown_without_a_peak_is_unmeasurable():
    """UNKNOWN must stay UNKNOWN — never silently reported as 0%."""
    ctx = _ctx(drawdown=Decimal("250"), peak_equity=None)
    assert ctx.measured_drawdown_pct() is None


def test_drawdown_pct_is_derived_from_peak_when_not_supplied():
    ctx = _ctx(drawdown=Decimal("250"), peak_equity=Decimal("10000"))
    assert ctx.measured_drawdown_pct() == Decimal("2.5")


def test_explicit_drawdown_pct_wins_over_derivation():
    """A caller that measured the percentage itself is not second-guessed."""
    ctx = _ctx(
        drawdown=Decimal("250"),
        peak_equity=Decimal("10000"),
        drawdown_pct=Decimal("4"),
    )
    assert ctx.measured_drawdown_pct() == Decimal("4")


# -------------------------------------------------------------- pre-trade


def test_pre_trade_vetoes_a_percentage_breach():
    # Dollar cap raised so the percentage cap is the binding constraint.
    eng = _engine(max_drawdown=Decimal("1000"), max_drawdown_pct=Decimal("5"))
    try:
        # 600 of 10,000 = 6% — under the 500 USD default cap, over the 5% cap.
        ctx = _ctx(drawdown=Decimal("600"), peak_equity=Decimal("10000"))
        decision = eng.pre_trade(_intent(), ctx)
        assert not decision.allowed
        assert decision.veto_reason is not None
        assert decision.veto_reason.value == "DRAWDOWN_PCT_BREACH"
    finally:
        eng.close()


def test_pre_trade_allows_a_drawdown_inside_both_caps():
    eng = _engine(max_drawdown_pct=Decimal("5"))
    try:
        ctx = _ctx(drawdown=Decimal("400"), peak_equity=Decimal("10000"))  # 4%
        assert eng.pre_trade(_intent(), ctx).allowed
    finally:
        eng.close()


def test_percentage_cap_is_additional_not_alternative():
    """A drawdown under the percentage cap still loses to the USD cap."""
    eng = _engine(max_drawdown=Decimal("100"), max_drawdown_pct=Decimal("50"))
    try:
        # 200 of 10,000 = 2% (well inside 50%) but over the 100 USD cap.
        ctx = _ctx(drawdown=Decimal("200"), peak_equity=Decimal("10000"))
        decision = eng.pre_trade(_intent(), ctx)
        assert not decision.allowed
        assert decision.veto_reason is not None
        assert decision.veto_reason.value == "DRAWDOWN_BREACH"
    finally:
        eng.close()


def test_unmeasurable_percentage_blocks_instead_of_assuming_zero():
    """UNKNOWN -> BLOCK. This is the whole point of the fail-closed rule."""
    eng = _engine(max_drawdown=Decimal("1000"), max_drawdown_pct=Decimal("5"))
    try:
        ctx = _ctx(drawdown=Decimal("600"), peak_equity=None)
        decision = eng.pre_trade(_intent(), ctx)
        assert not decision.allowed
        assert decision.veto_reason is not None
        assert decision.veto_reason.value == "DRAWDOWN_PCT_UNMEASURABLE"
    finally:
        eng.close()


def test_no_percentage_cap_configured_does_not_block_on_unmeasurable():
    """A cap that is not configured cannot be breached. Be explicit, not lucky."""
    eng = _engine(max_drawdown_pct=None)
    try:
        ctx = _ctx(drawdown=Decimal("10"), peak_equity=None)
        assert eng.pre_trade(_intent(), ctx).allowed
    finally:
        eng.close()


def test_percentage_breach_raises_the_durable_kill_switch_post_trade():
    eng = _engine(max_drawdown=Decimal("1000"), max_drawdown_pct=Decimal("5"))
    try:
        ctx = _ctx(drawdown=Decimal("600"), peak_equity=Decimal("10000"))
        fill = Fill(
            fill_id="f1",
            order_id="o1",
            client_order_id="pct-dd-1",
            instrument=Instrument(symbol="XAUUSD"),
            quantity=Decimal("0.1"),
            price=Decimal("2000"),
            side=Side.BUY,
        )
        eng.post_trade(fill, ctx)
        assert eng.killed
        state = eng.kill_state()
        assert state["killed"]
        assert "5" in (state.get("reason") or "")
    finally:
        eng.close()


def test_check_portfolio_reports_the_percentage_breach():
    eng = _engine(max_drawdown=Decimal("1000"), max_drawdown_pct=Decimal("5"))
    try:
        ctx = _ctx(drawdown=Decimal("600"), peak_equity=Decimal("10000"))
        reasons = {d.veto_reason.value for d in eng.check_portfolio(ctx) if d.veto_reason}
        assert "DRAWDOWN_PCT_BREACH" in reasons
    finally:
        eng.close()


# ------------------------------------------------------------- authority


def test_engine_limits_carry_the_percentage_through():
    snap = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    limits = engine_limits_from(snap)
    assert limits.max_drawdown_pct == snap.limits.max_drawdown_pct


def test_ceiling_tightens_and_records_provenance():
    snap = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    tightened = apply_risk_ceiling(snap, {"max_drawdown_pct": 5}, origin="owner_authorization")
    assert Decimal(str(tightened.limits.max_drawdown_pct)) == Decimal("5")
    assert tightened.sources["max_drawdown_pct"] == "owner_authorization"


def test_ceiling_can_never_widen_a_limit():
    snap = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    widened = apply_risk_ceiling(
        snap,
        {"max_drawdown_pct": 99, "max_quantity": 99, "daily_loss_limit": 99999},
        origin="owner_authorization",
    )
    for field in ("max_drawdown_pct", "max_quantity", "daily_loss_limit"):
        assert getattr(widened.limits, field) == getattr(snap.limits, field)
        assert widened.sources[field] == snap.sources[field]
    assert any("NOT applied" in w for w in widened.warnings)


def test_ceiling_ignores_unknown_and_non_numeric_values():
    snap = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    out = apply_risk_ceiling(
        snap, {"max_drawdown_pct": "not-a-number", "not_a_limit": 1}, origin="owner_authorization"
    )
    assert out.limits.max_drawdown_pct == snap.limits.max_drawdown_pct
    assert any("not numeric" in w for w in out.warnings)


def test_empty_ceiling_is_a_no_op():
    snap = resolve_risk_limits(ExecutionMode.DEMO_EXECUTION)
    assert apply_risk_ceiling(snap, None).config_hash == snap.config_hash
