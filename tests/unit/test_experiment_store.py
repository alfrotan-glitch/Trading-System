"""ExperimentStore regressions.

all_experiments() used to ORDER BY trial_count — a field that lives in the
payload, not as a column — so every store crashed with a raw SQLite
"no such column" error (exposed to users via /api/research/novelty, §16).
"""

from __future__ import annotations

from pathlib import Path

from qts.research.experiment import Experiment, ExperimentStore


def test_all_experiments_reads_the_canonical_schema(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "qts.db")
    a = store.put(Experiment(hypothesis_id="H-1", strategy_id="S-1", data_version="TEST-1", params={"x": 1}))
    b = store.put(Experiment(hypothesis_id="H-1", strategy_id="S-1", data_version="TEST-1", params={"x": 2}))

    exps = store.all_experiments()
    assert [e.id for e in exps] == [a.id, b.id]


def test_all_experiments_orders_by_trial_count_not_insertion(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "qts.db")
    first = store.put(Experiment(hypothesis_id="H-1", strategy_id="S-1", data_version="TEST-1"))
    second = store.put(Experiment(hypothesis_id="H-1", strategy_id="S-1", data_version="TEST-1"))
    assert second.trial_count >= first.trial_count

    exps = store.all_experiments()
    counts = [e.trial_count for e in exps]
    assert counts == sorted(counts), counts


def test_default_database_respects_anchored_override(tmp_path: Path, monkeypatch) -> None:
    """Default research state must never land in the current checkout."""
    db = tmp_path / "isolated" / "experiment.db"
    monkeypatch.setenv("QTS_DB_PATH", str(db))
    store = ExperimentStore()
    assert store.db_path == db
    item = store.put(Experiment(hypothesis_id="H-default", strategy_id="S-default", data_version="TEST"))
    assert db.is_file()
    assert store.get(item.id) is not None
