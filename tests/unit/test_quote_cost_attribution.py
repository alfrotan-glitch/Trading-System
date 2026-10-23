"""Unit tests for non-executable-mid versus executable-quote attribution."""

import numpy as np
import pytest

from qts.research.quote_cost_attribution import attribute_quote_costs


def test_decomposes_long_and_short_without_inventing_mid_fills():
    result = attribute_quote_costs(
        np.array([100.0, 100.0]),
        np.array([1.8, -1.2]),
        np.array([-2.2, 0.8]),
        np.array([1, -1]),
    )
    assert result["mean_mid_move_bps"] == pytest.approx(150.0)
    assert result["mean_quote_cost_bps"] == pytest.approx(20.0)
    assert result["mean_executable_quote_net_bps"] == pytest.approx(130.0)
    assert result["mid_is_executable"] is False


def test_invalid_quote_geometry_is_rejected():
    with pytest.raises(ValueError, match="nonnegative"):
        attribute_quote_costs(np.array([100.0]), np.array([1.0]), np.array([1.0]), np.array([1]))


def test_no_samples_has_no_positive_edge_claim():
    result = attribute_quote_costs(*(np.array([]) for _ in range(4)))
    assert result["n"] == 0
    assert result["mean_executable_quote_net_bps"] is None
