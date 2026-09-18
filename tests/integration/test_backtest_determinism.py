"""Determinism and integration tests."""

import tempfile
from pathlib import Path

from qts.backtest.engine import BacktestEngine
from qts.data.store import SqliteParquetDataStore
from qts.data.synthetic import generate_trending_bars
from qts.domain.value_objects import AssetClass, Instrument


def test_backtest_determinism():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteParquetDataStore(root=Path(tmp) / "data", db_path=Path(tmp) / "qts.db")
        instr = Instrument(symbol="XAUUSD", venue="MT5", asset_class=AssetClass.METAL)
        bars = generate_trending_bars(instrument=instr, periods=1000, seed=42)
        manifest = store.write_bars(bars)
        engine = BacktestEngine(store)
        r1 = engine.run(instr, manifest.timeframe, manifest.version, seed=42)
        r2 = engine.run(instr, manifest.timeframe, manifest.version, seed=42)
        assert r1.hash() == r2.hash()
        assert r1.equity_curve == r2.equity_curve
        assert r1.trades == r2.trades


def test_backtest_different_seed_same_data_same_result():
    # seed does not affect deterministic bar generation in backtest (only RNG for MC)
    # So two runs with same data_version but different seed should be same if strategy deterministic
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteParquetDataStore(root=Path(tmp) / "data", db_path=Path(tmp) / "qts.db")
        instr = Instrument(symbol="XAUUSD")
        bars = generate_trending_bars(instrument=instr, periods=800, seed=7)
        manifest = store.write_bars(bars)
        engine = BacktestEngine(store)
        r1 = engine.run(instr, manifest.timeframe, manifest.version, seed=1)
        r2 = engine.run(instr, manifest.timeframe, manifest.version, seed=999)
        assert r1.hash() == r2.hash()


def test_data_version_pinned():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteParquetDataStore(root=Path(tmp) / "data", db_path=Path(tmp) / "qts.db")
        instr = Instrument(symbol="XAUUSD")
        bars_v1 = generate_trending_bars(instrument=instr, periods=500, seed=1)
        bars_v2 = generate_trending_bars(instrument=instr, periods=500, seed=2)
        m1 = store.write_bars(bars_v1)
        m2 = store.write_bars(bars_v2)
        assert m1.version != m2.version
        engine = BacktestEngine(store)
        r1 = engine.run(instr, m1.timeframe, m1.version)
        r2 = engine.run(instr, m2.timeframe, m2.version)
        assert r1.hash() != r2.hash()


def test_backtest_preserves_durable_risk_and_reconcile_state():
    """Research replay cannot clear production safety state in the shared DB."""
    from qts.db import connect as db_connect
    from qts.risk.engine import RiskEngine, RiskLimits

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = SqliteParquetDataStore(root=root / "data", db_path=root / "qts.db")
        instr = Instrument(symbol="XAUUSD")
        manifest = store.write_bars(generate_trending_bars(instrument=instr, periods=100, seed=11))

        durable_risk = RiskEngine(RiskLimits(), db_path=store.db_path)
        durable_risk.kill_switch("operator test stop")

        result = BacktestEngine(store).run(instr, manifest.timeframe, manifest.version)
        assert result.bars == 100
        assert RiskEngine(RiskLimits(), db_path=store.db_path).killed is True

        with db_connect(store.db_path) as con:
            reconcile_table = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='reconcile_state'"
            ).fetchone()
        assert reconcile_table is None


def test_backtest_result_binds_dataset_and_full_run_lineage():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = SqliteParquetDataStore(root=root / "data", db_path=root / "qts.db")
        instr = Instrument(symbol="XAUUSD")
        manifest = store.write_bars(generate_trending_bars(instrument=instr, periods=100, seed=12))
        engine = BacktestEngine(store)

        result = engine.run(instr, manifest.timeframe, manifest.version, seed=7)
        changed_seed = engine.run(instr, manifest.timeframe, manifest.version, seed=8)

        assert result.manifest_hash == manifest.checksum
        assert result.code_version
        assert result.config_hash
        assert changed_seed.config_hash != result.config_hash


def test_domain_event_defaults_to_resolved_code_lineage():
    from qts.domain.events import DomainEvent, EventType
    from qts.observability.lineage import code_version

    event = DomainEvent(event_type=EventType.NO_TRADE)
    assert event.code_version == code_version()
    assert event.code_version != "0.1.0"
