"""Regression: numpy scalar outcomes must not corrupt the durable trial ledger."""
import json

import numpy as np

from qts.research.experiment import Experiment, ExperimentStore


def test_numpy_bool_and_nested_scalar_outcomes_are_json_serializable(tmp_path):
    e = Experiment(hypothesis_id="H-test", strategy_id="test", data_version="test")
    out = e.with_outcome(results={
        "checks": {"economic_edge": np.bool_(False)},
        "numbers": [np.int64(3), np.float64(2.5)],
        "array": np.array([True, False], dtype=np.bool_),
    })
    parsed = json.loads(out.model_dump_json())
    assert parsed["results"]["checks"]["economic_edge"] is False
    assert parsed["results"]["numbers"] == [3, 2.5]
    assert parsed["results"]["array"] == [True, False]
    assert e.results == {}


def test_persistent_experiment_write_can_roundtrip_numpy_outcomes(tmp_path):
    store = ExperimentStore(db_path=tmp_path / "trial.db")
    e = Experiment(hypothesis_id="H-test", strategy_id="test", data_version="test")
    store.put(e)
    store.complete(e.id, results={"passed": np.bool_(False),
                                  "gross": np.float64(1.5),
                                  "trials": np.int64(304)})
    stored = store.get(e.id)
    assert stored is not None
    assert stored.results["passed"] is False
    assert stored.results["gross"] == 1.5
    assert stored.results["trials"] == 304
