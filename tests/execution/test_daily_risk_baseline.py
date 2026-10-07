from decimal import Decimal

from qts.execution.engine import ExecutionEngine


def _engine(db_path):
    engine = object.__new__(ExecutionEngine)
    engine._db_path = db_path
    engine.persist_reconcile_state = True
    engine._day_start_equity = Decimal("0")
    engine._init_reconcile_db()
    return engine


def test_daily_equity_baseline_survives_restart(tmp_path):
    db = tmp_path / "risk.db"

    first = _engine(db)
    assert first._load_day_start_equity(Decimal("1000")) == Decimal("1000")

    restarted = _engine(db)
    assert restarted._load_day_start_equity(Decimal("800")) == Decimal("1000")


def test_drawdown_peak_survives_restart(tmp_path):
    db = tmp_path / "risk.db"

    first = _engine(db)
    assert first._load_peak_equity(Decimal("1200")) == Decimal("1200")

    restarted = _engine(db)
    assert restarted._load_peak_equity(Decimal("900")) == Decimal("1200")
