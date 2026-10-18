"""Read-only broker symbol cost terms: directional swap must be measurable
BEFORE a position exists, and unavailable must never read as zero."""

from types import SimpleNamespace

from qts.adapters.mt5_adapter import MT5Adapter


def _mt5(info, tick):
    class FakeMT5:
        def symbol_info(self, _s):
            return info

        def symbol_info_tick(self, _s):
            return tick

    return FakeMT5()


def _info(**over):
    base = {
        "swap_long": -55.3,
        "swap_short": 12.1,
        "swap_mode": 1,
        "swap_rollover3days": 3,
        "trade_contract_size": 100.0,
        "trade_tick_value": 1.0,
        "trade_tick_size": 0.01,
        "point": 0.01,
        "digits": 2,
        "currency_profit": "USD",
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_points_mode_swap_converts_to_usd_per_lot_night():
    terms = MT5Adapter._symbol_cost_terms(_mt5(_info(), SimpleNamespace(bid=2650.10, ask=2650.45)), "XAUUSD")
    # -55.3 points x $0.01 x (1.0 / 0.01) USD-per-price-unit = -$55.30 / lot / night
    assert terms["swap_long_usd_per_lot_night"] == "-55.3000"
    assert terms["swap_short_usd_per_lot_night"] == "12.1000"
    assert terms["swap_mode_name"] == "by_points"
    assert terms["spread_price_units"] == "0.35"
    assert terms["unavailable"] is False


def test_missing_terminal_is_unavailable_not_zero():
    terms = MT5Adapter._symbol_cost_terms(None, "XAUUSD")
    assert terms["unavailable"] is True
    assert terms["swap_long_usd_per_lot_night"] is None
    assert terms["unavailable_fields"] == ["terminal"]


def test_missing_swap_fields_are_named_not_zeroed():
    info = _info()
    del info.swap_long
    terms = MT5Adapter._symbol_cost_terms(_mt5(info, SimpleNamespace(bid=1.0, ask=1.1)), "XAUUSD")
    assert terms["swap_long_points"] is None
    assert "swap_long" in terms["unavailable_fields"]


def test_interest_swap_mode_is_reported_raw_never_converted():
    terms = MT5Adapter._symbol_cost_terms(
        _mt5(_info(swap_mode=3), SimpleNamespace(bid=2650.0, ask=2650.3)), "XAUUSD"
    )
    assert terms["swap_mode_name"] == "by_interest_current"
    assert terms["swap_long_usd_per_lot_night"] is None
    assert "swap_derived_usd" in terms["unavailable_fields"]


def test_non_usd_profit_currency_blocks_derivation():
    terms = MT5Adapter._symbol_cost_terms(
        _mt5(_info(currency_profit="EUR"), SimpleNamespace(bid=2650.0, ask=2650.3)), "XAUUSD"
    )
    assert terms["swap_long_usd_per_lot_night"] is None
    assert "swap_derived_usd" in terms["unavailable_fields"]


def test_swap_bps_per_day_and_optional_symbol_spec_details():
    info = _info(
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        trade_stops_level=20,
        filling_mode=1,
        margin_initial=0.0,
        currency_margin="USD",
    )
    terms = MT5Adapter._symbol_cost_terms(_mt5(info, SimpleNamespace(bid=2650.10, ask=2650.45)), "XAUUSD")
    # -55.30 USD/lot/night on 100 oz * 2650.275 mid = +2.0866 bps/day cost
    assert terms["swap_long_bps_per_day_of_notional"] == "2.0866"
    # +12.10 USD/lot/night on 100 oz * 2650.275 mid = -0.4566 bps/day (credit)
    assert terms["swap_short_bps_per_day_of_notional"] == "-0.4566"
    spec = terms.get("symbol_spec_details") or {}
    assert spec["volume_min"] == "0.01"
    assert spec["volume_step"] == "0.01"
    assert spec["stops_level"] == 20
    assert spec["filling_mode"] == 1
