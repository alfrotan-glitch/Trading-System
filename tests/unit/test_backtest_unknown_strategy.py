"""Unknown strategy ids must fail closed, not silently run SMA.

Regression for the strategist review at c7f22b4: BacktestEngine.run()
fell through to SmaBreakoutStrategy for any unknown strategy_id, while
the result, fills and config hash still carried the unknown id -- SMA
evidence stamped with a name that was never run. Campaigns pass an
explicit _family and are unaffected; a direct caller that wants SMA
must ask for "sma_breakout" by name.
"""

import tempfile
from pathlib import Path

import pytest

from qts.backtest.engine import BacktestEngine
from qts.data.store import SqliteParquetDataStore
from qts.data.synthetic import generate_trending_bars
from qts.domain.value_objects import Instrument


def _engine_with_bars():
    tmp = tempfile.TemporaryDirectory()
    store = SqliteParquetDataStore(root=Path(tmp.name) / "data", db_path=Path(tmp.name) / "qts.db")
    instr = Instrument(symbol="XAUUSD")
    manifest = store.write_bars(generate_trending_bars(instrument=instr, periods=100, seed=11))
    return tmp, store, instr, manifest


def test_unknown_strategy_id_raises_instead_of_running_sma():
    tmp, store, instr, manifest = _engine_with_bars()
    with tmp:
        engine = BacktestEngine(store)
        with pytest.raises(ValueError, match="unknown strategy"):
            engine.run(instr, manifest.timeframe, manifest.version, strategy_id="my_secret_edge_v9")


def test_named_sma_breakout_still_runs():
    tmp, store, instr, manifest = _engine_with_bars()
    with tmp:
        engine = BacktestEngine(store)
        result = engine.run(instr, manifest.timeframe, manifest.version, strategy_id="sma_breakout")
        assert result.strategy_id == "sma_breakout"
        assert result.bars == 100
