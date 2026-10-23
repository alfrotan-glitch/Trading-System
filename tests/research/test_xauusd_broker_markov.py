"""Tests for the fixed return-sign Markov broker assay."""

import numpy as np

from qts.research.xauusd_broker_markov import MarkovSamples, fit_markov, predict_direction


def _samples() -> MarkovSamples:
    state = np.tile(np.array([1, 1, 1, -1, -1, -1], dtype=np.int8), 100)
    target = np.tile(np.array([1, 1, 0, 0, 0, 1], dtype=np.int8), 100)
    size = len(state)
    return MarkovSamples(
        signal_index=np.arange(size, dtype=np.int64),
        exit_index=np.arange(size, dtype=np.int64) + 3,
        state=state,
        target=target,
        entry_mid=np.full(size, 2_000.0),
        pnl_long=np.ones(size),
        pnl_short=np.ones(size),
    )


def test_markov_uses_laplace_smoothed_state_probabilities() -> None:
    samples = _samples()
    model = fit_markov(samples, np.ones(len(samples.state), dtype=bool))
    assert np.isclose(model.probability_by_state[1], 201 / 302)
    assert np.isclose(model.probability_by_state[-1], 101 / 302)
    prediction = predict_direction(samples, model)
    assert np.all(prediction[:3] == 1)
    assert np.all(prediction[3:6] == -1)
