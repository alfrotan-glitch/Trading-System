"""Transaction costs are what decide whether an edge exists.

An uncosted backtest cannot distinguish "this rule finds an inefficiency" from
"this rule trades a lot on a wide spread". These tests pin the cost model that
makes gross/net decidable, and pin the failure modes that would let a gross
number masquerade as a net one.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from qts.research.costs import (
    CostBasis,
    CostComponent,
    CostModel,
    TradeRecord,
    cost_summary_line,
    decompose_costs,
)


def _model(**kwargs: object) -> CostModel:
    """An ASSUMED model — a valid sensitivity result, never a claim."""
    kwargs.setdefault("spread_price_units", 0.30)
    kwargs.setdefault("slippage_price_units", 0.10)
    kwargs.setdefault("swap_per_night_per_lot_usd", 0.0)
    kwargs.setdefault("basis", CostBasis.ASSUMED)
    return CostModel.xauusd_default(**kwargs)  # type: ignore[arg-type]


def _measured_model(**kwargs: object) -> CostModel:
    """A MEASURED model — the only kind an edge claim may rest on."""
    kwargs.setdefault("basis", CostBasis.MEASURED)
    kwargs.setdefault("source", "broker quote / commission schedule (test fixture)")
    return _model(**kwargs)


# --------------------------------------------------------------- components


def test_component_cost_in_price_units_uses_contract_size():
    # 0.30 USD/oz spread x 100 oz/lot x 0.1 lots = 3.00 USD
    c = CostComponent(name="spread", basis=CostBasis.MEASURED, price_units_per_lot=0.30, fills=1)
    assert math.isclose(c.cost_usd(lots=0.1, contract_size=100.0), 3.0)


def test_component_cost_in_usd_per_lot_is_charged_per_fill():
    c = CostComponent(name="commission", basis=CostBasis.MEASURED, usd_per_lot=7.0, fills=2)
    assert math.isclose(c.cost_usd(lots=0.5, contract_size=100.0), 7.0)  # 7*2*0.5


def test_financing_scales_with_nights_held():
    c = CostComponent(name="financing", basis=CostBasis.MEASURED, usd_per_lot_per_night=2.0)
    assert math.isclose(c.cost_usd(lots=1.0, contract_size=100.0, nights_held=3), 6.0)
    assert math.isclose(c.cost_usd(lots=1.0, contract_size=100.0, nights_held=0), 0.0)


def test_financing_never_earns_money_on_negative_nights():
    """A malformed negative holding period must not become a credit."""
    c = CostComponent(name="financing", basis=CostBasis.MEASURED, usd_per_lot_per_night=2.0)
    assert c.cost_usd(lots=1.0, contract_size=100.0, nights_held=-5) == 0.0


def test_a_silently_free_component_is_refused():
    """A zeroed cost with a confident basis is a bug, not a free lunch."""
    with pytest.raises(ValueError):
        CostComponent(name="spread", basis=CostBasis.MEASURED)


def test_an_explicitly_declared_zero_is_allowed():
    c = CostComponent(name="commission", basis=CostBasis.MEASURED, usd_per_lot=0.0, zero_is_known=True)
    assert c.cost_usd(lots=1.0, contract_size=100.0) == 0.0


def test_unknown_basis_components_are_allowed_and_visible():
    c = CostComponent(name="financing", basis=CostBasis.UNKNOWN)
    assert c.basis is CostBasis.UNKNOWN
    assert c.as_dict()["basis"] == "UNKNOWN"


# -------------------------------------------------------------------- model


def test_model_rejects_duplicate_component_names():
    with pytest.raises(ValueError):
        CostModel(
            components=(
                CostComponent(name="spread", basis=CostBasis.MEASURED, price_units_per_lot=0.2),
                CostComponent(name="spread", basis=CostBasis.MEASURED, price_units_per_lot=0.4),
            )
        )


def test_model_rejects_a_non_positive_contract_size():
    with pytest.raises(ValueError):
        CostModel(contract_size=0)


def test_claim_eligibility_requires_measured_costs():
    """Gross minus a number somebody chose is not an economic edge."""
    assert _measured_model(swap_per_night_per_lot_usd=0.0).claim_eligible() is True
    assert _model(swap_per_night_per_lot_usd=0.0).claim_eligible() is False
    assert _measured_model(swap_per_night_per_lot_usd=None).claim_eligible() is False


def test_default_constructor_marks_unsupplied_financing_as_unknown():
    """Not supplying a swap is not the same as knowing it is zero."""
    m = _model(swap_per_night_per_lot_usd=None)
    assert m.basis_summary()["financing"] == CostBasis.UNKNOWN.value
    assert m.claim_eligible() is False


def test_assumed_costs_are_reported_visibly():
    m = _model()
    assert sorted(m.assumed_components()) == ["commission", "financing", "slippage", "spread"]
    dec = decompose_costs([TradeRecord(lots=0.1, gross_pnl_usd=50.0)], m)
    assert any("ASSUMED" in r and "requires measured costs" in r for r in dec.reasons)
    assert dec.claim_eligible is False


# ----------------------------------------------------------- decomposition


def test_round_turn_cost_is_the_sum_of_components():
    m = _model(spread_price_units=0.30, slippage_price_units=0.10)
    t = TradeRecord(lots=0.1, gross_pnl_usd=0.0)
    breakdown = m.round_turn_cost(t)
    # spread 0.30*100*0.1 = 3.00 ; slippage 0.10*100*0.1*2 = 2.00
    assert math.isclose(breakdown["spread"], 3.0)
    assert math.isclose(breakdown["slippage"], 2.0)
    assert math.isclose(breakdown["total"], 5.0)


def test_gross_minus_cost_equals_net():
    m = _model(spread_price_units=0.30, slippage_price_units=0.10)
    trades = [
        TradeRecord(lots=0.1, gross_pnl_usd=50.0),
        TradeRecord(lots=0.1, gross_pnl_usd=-20.0),
    ]
    d = decompose_costs(trades, m)
    assert math.isclose(d.gross_pnl_usd, 30.0)
    assert math.isclose(d.cost_usd, 10.0)
    assert math.isclose(d.net_pnl_usd, 20.0)
    assert math.isclose(d.net_expectancy_per_trade, 10.0)


def test_equity_curves_cumulate_gross_and_net_per_trade():
    m = _model(spread_price_units=0.30, slippage_price_units=0.10)
    trades = [TradeRecord(lots=0.1, gross_pnl_usd=10.0), TradeRecord(lots=0.1, gross_pnl_usd=10.0)]
    d = decompose_costs(trades, m)
    assert d.equity_gross == pytest.approx([10.0, 20.0])
    assert d.equity_net == pytest.approx([5.0, 10.0])


def test_a_profitable_gross_strategy_can_lose_net_of_cost():
    """The single most important number in the system."""
    # 8 USD of gross edge per trade against a 10 USD round-turn cost.
    m = _model(spread_price_units=0.60, slippage_price_units=0.20)  # 6 + 4 = 10 USD at 0.1 lot
    trades = [TradeRecord(lots=0.1, gross_pnl_usd=8.0) for _ in range(10)]
    d = decompose_costs(trades, m)
    assert d.gross_pnl_usd > 0
    assert d.net_pnl_usd < 0
    assert d.break_even_cost_multiple < 1.0


def test_break_even_multiple_quantifies_robustness():
    m = _model(spread_price_units=0.30, slippage_price_units=0.10)
    trades = [TradeRecord(lots=0.1, gross_pnl_usd=50.0)]
    d = decompose_costs(trades, m)
    # gross 50, cost 5 -> costs could rise 10x before this stops working
    assert math.isclose(d.break_even_cost_multiple, 10.0)


def test_cost_drag_is_the_share_of_gross_consumed_by_costs():
    m = _model(spread_price_units=0.30, slippage_price_units=0.10)
    d = decompose_costs([TradeRecord(lots=0.1, gross_pnl_usd=50.0)], m)
    assert math.isclose(d.cost_drag, 0.1)


def test_cost_drag_is_not_invented_when_gross_is_negative():
    """A negative gross has no 'share consumed by costs' — say so, don't fake it."""
    m = _model(spread_price_units=0.30, slippage_price_units=0.10)
    d = decompose_costs([TradeRecord(lots=0.1, gross_pnl_usd=-50.0)], m)
    assert math.isnan(d.cost_drag)


def test_empty_trade_list_is_not_a_favourable_result():
    m = _model()
    d = decompose_costs([], m)
    assert d.trades == 0
    assert d.claim_eligible is False
    assert any("no trades" in r for r in d.reasons)


def test_unincurred_unknown_cost_does_not_block_the_claim():
    """No overnight hold means unmeasured financing never touched the number."""
    m = _measured_model(swap_per_night_per_lot_usd=None)
    intraday = decompose_costs([TradeRecord(lots=0.1, gross_pnl_usd=50.0, nights_held=0)], m)
    assert intraday.claim_eligible is True
    assert any("never incurred" in r for r in intraday.reasons)

    overnight = decompose_costs([TradeRecord(lots=0.1, gross_pnl_usd=50.0, nights_held=1)], m)
    assert overnight.claim_eligible is False


def test_a_model_with_no_components_is_refused_as_evidence():
    d = decompose_costs([TradeRecord(lots=0.1, gross_pnl_usd=50.0)], CostModel())
    assert d.claim_eligible is False
    assert any("no components" in r for r in d.reasons)


def test_trade_records_reject_non_finite_and_negative_inputs():
    with pytest.raises(ValueError):
        TradeRecord(lots=0.1, gross_pnl_usd=float("nan"))
    with pytest.raises(ValueError):
        TradeRecord(lots=-0.1, gross_pnl_usd=1.0)


def test_summary_line_states_gross_cost_and_net():
    m = _model(spread_price_units=0.30, slippage_price_units=0.10)
    line = cost_summary_line(decompose_costs([TradeRecord(lots=0.1, gross_pnl_usd=50.0)], m))
    assert "gross" in line and "costs" in line and "net" in line
    assert "break-even" in line


# ------------------------------------------------- wiring into the edge gate


def _survival_kwargs(**over: object) -> dict:
    base = {
        "strategy_id": "COST-TEST",
        "data_version": "test",
        "equity_is": np.linspace(100, 110, 40),
        "equity_oos": np.linspace(110, 115, 30),
        "equity_gross": None,
        "equity_net": None,
        "walk_forward_folds": [],
        "cpcv_folds": [],
        "perturbed_sharpes": [],
        "stress_results": {},
        "num_trials": 1,
        "control_sharpes": [],
        "placebo_sharpes": [],
        "bars": [],
        "trades_pnl": [],
    }
    base.update(over)
    return base


def test_expectancy_is_not_reported_as_net_when_no_cost_is_modelled():
    """Regression: this used to call compute_expectancy(costs_per_trade=0.0)
    and label gross expectancy 'net'."""
    from qts.validation.edge_validation import validate_edge_survival

    res = validate_edge_survival(
        **_survival_kwargs(trades_pnl=[10.0, 10.0, 10.0])  # clearly positive gross
    )
    assert res.checks["expectancy"] is False
    assert "NOT measured" in res.details["expectancy"]
    assert "GROSS" in res.details["expectancy"]


def test_a_cost_model_makes_the_cost_gate_decidable():
    from qts.validation.edge_validation import validate_edge_survival

    m = _measured_model(spread_price_units=0.30, slippage_price_units=0.10, swap_per_night_per_lot_usd=0.0)
    trades = [TradeRecord(lots=0.1, gross_pnl_usd=60.0) for _ in range(12)]
    res = validate_edge_survival(
        **_survival_kwargs(cost_model=m, trade_records=trades),
    )
    assert res.cost_decomposition is not None
    assert res.cost_decomposition.trades == 12
    # The gate may still fail on other grounds (walk-forward, CPCV, controls) —
    # what must NOT happen is that it reports "NOT_IMPLEMENTED".
    assert "NOT_IMPLEMENTED" not in res.details["cost"]
    assert res.checks["expectancy"] is True


def test_expectancy_subtracts_the_modelled_cost():
    from qts.validation.edge_validation import validate_edge_survival

    # gross 10 USD/trade, round-turn cost 5 USD/trade -> net 5 USD/trade
    m = _measured_model(spread_price_units=0.30, slippage_price_units=0.10, swap_per_night_per_lot_usd=0.0)
    trades = [TradeRecord(lots=0.1, gross_pnl_usd=10.0) for _ in range(10)]
    res = validate_edge_survival(**_survival_kwargs(cost_model=m, trade_records=trades))
    assert res.cost_decomposition is not None
    assert res.cost_decomposition.net_expectancy_per_trade == pytest.approx(5.0)
    assert "cost 5.0000/trade" in res.details["expectancy"]


def test_a_cost_that_exceeds_the_gross_edge_fails_the_expectancy_gate():
    from qts.validation.edge_validation import validate_edge_survival

    m = _measured_model(spread_price_units=1.50, slippage_price_units=0.50)  # 25 USD at 0.1 lot
    trades = [TradeRecord(lots=0.1, gross_pnl_usd=10.0) for _ in range(10)]
    res = validate_edge_survival(**_survival_kwargs(cost_model=m, trade_records=trades))
    assert res.checks["expectancy"] is False
    assert res.checks["economic_edge"] is False


def test_an_assumed_cost_never_unlocks_the_economic_edge_gate():
    """Regression: an ASSUMED cost model made this gate pass on a synthetic
    fixture. Gross minus a chosen number is not evidence of an edge."""
    from qts.validation.edge_validation import validate_edge_survival

    m = _model(spread_price_units=0.30, slippage_price_units=0.10, swap_per_night_per_lot_usd=0.0)
    trades = [TradeRecord(lots=0.1, gross_pnl_usd=60.0) for _ in range(12)]
    res = validate_edge_survival(**_survival_kwargs(cost_model=m, trade_records=trades))
    # The decomposition is still computed and reported — it just cannot pass.
    assert res.cost_decomposition is not None
    assert res.cost_decomposition.net_expectancy_per_trade > 0
    assert res.checks["economic_edge"] is False
    assert res.checks["expectancy"] is False
    assert "not MEASURED" in res.details["economic_edge"]
    assert "ASSUMED" in res.details["expectancy"]
