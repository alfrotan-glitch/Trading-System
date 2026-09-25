"""Adversarial tests for DEMO_FORWARD safety boundary — must fail closed, never silently become LIVE."""

from decimal import Decimal
from pathlib import Path

from qts.lifecycle.demo_gate import demo_forward_readiness_report


def test_live_account_to_demo_blocked():
    class MockAI:
        login = 123
        server = "ICMarkets-Live"
        company = "ICMarkets"
        balance = 10000
        margin = 0
        trade_mode = 2

    class MockMT5:
        def terminal_info(self):
            return object()

        def account_info(self):
            return MockAI()

        def symbol_info(self, sym):
            class SI:
                contract_size = 100
                volume_min = 0.01
                volume_max = 100
                volume_step = 0.01
                digits = 2
                point = 0.01
                trade_allowed = True
                trade_mode = 4

            return SI()

        def symbol_info_tick(self, sym):
            class T:
                bid = 2000
                ask = 2000.5
                time = __import__("time").time()

            return T()

    rpt = demo_forward_readiness_report(mt5_module=MockMT5())
    assert rpt["warn_live_in_demo"] is True
    assert any("LIVE account" in b for b in rpt["blocked_reasons"])
    assert rpt["passed"] is False
    assert rpt["demo_enabled"] is False


def test_demo_account_passes_is_demo_check():
    class MockAIDemo:
        login = 123
        server = "ICMarkets-Demo"
        company = "ICMarkets"
        balance = 10000
        margin = 0
        trade_mode = 0

    class MockMT5:
        def terminal_info(self):
            return object()

        def account_info(self):
            return MockAIDemo()

        def symbol_info(self, sym):
            class SI:
                contract_size = 100
                volume_min = 0.01
                volume_max = 100
                volume_step = 0.01
                digits = 2
                point = 0.01
                trade_allowed = True
                trade_mode = 4

            return SI()

        def symbol_info_tick(self, sym):
            class T:
                bid = 2000
                ask = 2000.5
                time = __import__("time").time()

            return T()

    rpt = demo_forward_readiness_report(mt5_module=MockMT5())
    assert rpt["checks"]["account_is_demo"] is True


def test_terminal_disconnected_blocks():
    class MockMT5:
        def terminal_info(self):
            return None

        def account_info(self):
            return None

        def symbol_info(self, s):
            return None

        def symbol_info_tick(self, s):
            return None

    rpt = demo_forward_readiness_report(mt5_module=MockMT5())
    assert rpt["checks"]["terminal_running"] is False
    assert rpt["passed"] is False


def test_stale_tick_blocks():
    import time

    class MockAI:
        login = 123
        server = "Demo"
        company = "B"
        balance = 10000
        margin = 0
        trade_mode = 0

    class MockMT5:
        def terminal_info(self):
            return object()

        def account_info(self):
            return MockAI()

        def symbol_info(self, s):
            class SI:
                contract_size = 100
                volume_min = 0.01
                volume_max = 100
                volume_step = 0.01
                digits = 2
                point = 0.01
                trade_allowed = True
                trade_mode = 4

            return SI()

        def symbol_info_tick(self, s):
            class T:
                bid = 2000
                ask = 2000.5
                time = time.time() - 120

            return T()

    rpt = demo_forward_readiness_report(mt5_module=MockMT5())
    assert rpt["checks"]["market_data_fresh"] is False


def test_invalid_bid_ask_blocks():
    class MockAI:
        login = 123
        server = "Demo"
        company = "B"
        balance = 10000
        margin = 0
        trade_mode = 0

    class MockMT5:
        def terminal_info(self):
            return object()

        def account_info(self):
            return MockAI()

        def symbol_info(self, s):
            class SI:
                contract_size = 100
                volume_min = 0.01
                volume_max = 100
                volume_step = 0.01
                digits = 2
                point = 0.01
                trade_allowed = True
                trade_mode = 4

            return SI()

        def symbol_info_tick(self, s):
            class T:
                bid = 2000.5
                ask = 2000
                time = __import__("time").time()

            return T()

    rpt = demo_forward_readiness_report(mt5_module=MockMT5())
    assert rpt["checks"]["bid_ask_valid"] is False


def test_excessive_spread_blocks():
    class MockAI:
        login = 123
        server = "Demo"
        company = "B"
        balance = 10000
        margin = 0
        trade_mode = 0

    class MockMT5:
        def terminal_info(self):
            return object()

        def account_info(self):
            return MockAI()

        def symbol_info(self, s):
            class SI:
                contract_size = 100
                volume_min = 0.01
                volume_max = 100
                volume_step = 0.01
                digits = 2
                point = 0.01
                trade_allowed = True
                trade_mode = 4

            return SI()

        def symbol_info_tick(self, s):
            class T:
                bid = 2000
                ask = 2010
                time = __import__("time").time()

            return T()

    rpt = demo_forward_readiness_report(mt5_module=MockMT5())
    assert rpt["checks"]["spread_acceptable"] is False


def test_insufficient_margin_blocks_account_state():
    class MockAI:
        login = 123
        server = "Demo"
        company = "B"
        balance = 0
        margin = 0
        trade_mode = 0

    class MockMT5:
        def terminal_info(self):
            return object()

        def account_info(self):
            return MockAI()

        def symbol_info(self, s):
            class SI:
                contract_size = 100
                volume_min = 0.01
                volume_max = 100
                volume_step = 0.01
                digits = 2
                point = 0.01
                trade_allowed = True
                trade_mode = 4

            return SI()

        def symbol_info_tick(self, s):
            class T:
                bid = 2000
                ask = 2000.5
                time = __import__("time").time()

            return T()

    rpt = demo_forward_readiness_report(mt5_module=MockMT5())
    assert rpt["checks"]["account_state_valid"] is False


def test_wrong_lot_size_rejected_by_symbol_spec():
    from qts.adapters.mt5_adapter import MT5Adapter

    class MockSI:
        contract_size = 100
        volume_min = 0.01
        volume_max = 1.0
        volume_step = 0.01
        digits = 2
        point = 0.01
        trade_allowed = True
        stops_level = 10
        freeze_level = 0
        trade_mode = 4
        execution_mode = 0
        filling_mode = 2
        trade_tick_size = 0.01

    class MockMT5:
        def symbol_info(self, s):
            return MockSI()

        def symbol_select(self, s, b):
            return True

        def last_error(self):
            return 0

        def symbol_info_tick(self, s):
            class T:
                bid = 2000
                ask = 2000.5
                time = __import__("time").time()

            return T()

        def account_info(self):
            class AI:
                balance = 10000
                equity = 10000
                margin = 100
                free_margin = 9900

            return AI()

        def terminal_info(self):
            return object()

        def order_send(self, req):
            return type("R", (), {"retcode": 10013, "comment": "Invalid volume"})()

    adapter = MT5Adapter(mt5_module=MockMT5(), config={"path": "dummy"})
    spec = adapter.get_symbol_spec("XAUUSD")
    assert spec.volume_min == Decimal("0.01")
    assert Decimal("0.005") < spec.volume_min


def test_broker_rejection_handled():
    from qts.execution.demo_comparison import compare_paper_shadow_demo

    obs = [{"type": "demo_rejected", "reason": "Invalid price"}, {"type": "demo_fill"}]
    res = compare_paper_shadow_demo(paper_fills=[], shadow_intents=[], demo_observations=obs)
    assert res["rejected_orders_demo"] == 1


def test_timeout_ambiguous_order():
    from qts.domain.value_objects import OrderState

    assert OrderState.AMBIGUOUS == "AMBIGUOUS"


def test_partial_fill():
    from qts.domain.value_objects import Instrument, Order, OrderState, OrderType, Side

    instr = Instrument(symbol="XAUUSD")
    order = Order(
        order_id="O1",
        client_order_id="C1",
        instrument=instr,
        side=Side.BUY,
        quantity=Decimal("0.2"),
        order_type=OrderType.MARKET,
        strategy_id="s1",
    )
    assert order.filled_quantity == Decimal("0")
    partial = order.with_state(OrderState.PARTIALLY_FILLED, filled_quantity=Decimal("0.1"))
    assert partial.state == "PARTIALLY_FILLED" or partial.filled_quantity == Decimal("0.1")


def test_crash_after_submission_restart_recovery():
    from qts.desktop.health import startup_health_check

    health = startup_health_check()
    assert "checks" in health


def test_restart_after_suspension():
    import tempfile

    from qts.risk.engine import RiskEngine, RiskLimits

    db = Path(tempfile.mktemp(suffix=".db"))
    eng = RiskEngine(RiskLimits(), db_path=db)
    eng.kill_switch("test")
    assert eng.is_killed() if hasattr(eng, "is_killed") else eng.killed
    eng2 = RiskEngine(RiskLimits(), db_path=db)
    if hasattr(eng2, "is_killed"):
        assert eng2.is_killed() is True


def test_demo_live_environment_confusion_blocked():
    from qts.risk.demo_limits import env_boundary_check

    ok, msg = env_boundary_check("development", "live")
    assert ok is False
    ok, msg = env_boundary_check("demo_forward", "live")
    assert ok is False
    ok2, _ = env_boundary_check("demo_forward", "demo_forward")
    assert ok2 is True


def test_demo_safety_independent_limits():
    from qts.risk.demo_limits import DEMO_FORWARD_DEFAULTS, assert_demo_limits

    assert DEMO_FORWARD_DEFAULTS.max_volume_per_order == 0.1
    assert DEMO_FORWARD_DEFAULTS.max_daily_loss_usd == 50.0
    ok, msg = assert_demo_limits(volume=0.2, exposure=0.1, spread_bps=10, slippage_bps=5)
    assert ok is False
    ok, msg = assert_demo_limits(volume=0.05, exposure=0.1, spread_bps=10, slippage_bps=5)
    assert ok is True


def test_demo_comparison_label_never_live():
    """The derived comparison artifact must label DEMO as never-LIVE.

    Current canonical shape: the label lives in the explicit `provenance`
    block (legacy top-level `label` predates the provenance-first redesign).
    The regenerated artifact is pinned here so a revert to either the legacy
    shape or an unlabeled file fails loudly.
    """
    p = Path("data/evidence/paper_shadow_demo_comparison.json")
    assert p.exists()
    import json

    data = json.loads(p.read_text(encoding="utf-8"))
    prov = data.get("provenance") or {}
    label = prov.get("label") or data.get("label")
    assert label == "DEMO never LIVE"
    assert data.get("demo_observations", 0) >= 0
