"""The acceptance gate is the only thing standing between research and money.

These tests exist because a gate that silently passes everything is
indistinguishable from no gate at all — which is exactly what the deflated-Sharpe
implementation did before it was fixed (``norm.ppf(0)`` made every input score 1.0).
"""

from __future__ import annotations

import pandas as pd
import pytest

from qts.research.edgelab.gate import (
    MIN_ALPHA_T_DEV,
    MIN_DSR,
    survivors,
    val_confirms,
)


def _row(**kw) -> dict:
    base = {"name": "s", "alpha_t": 3.0, "dsr": 0.99, "alpha_ann": 0.05, "alpha_ann_stress": 0.04}
    base.update(kw)
    return base


def test_gate_passes_a_strong_candidate():
    assert len(survivors(pd.DataFrame([_row()]))) == 1


def test_gate_rejects_low_alpha_t():
    """A Sharpe-only winner with no alpha is beta, and beta is not an edge."""
    df = pd.DataFrame([_row(alpha_t=MIN_ALPHA_T_DEV - 0.01)])
    assert survivors(df).empty


def test_gate_rejects_failed_deflated_sharpe():
    df = pd.DataFrame([_row(dsr=MIN_DSR - 0.01)])
    assert survivors(df).empty


def test_gate_rejects_alpha_that_dies_under_cost_stress():
    """If doubling assumed costs removes the alpha, it was a cost-model artefact."""
    df = pd.DataFrame([_row(alpha_ann_stress=-0.001)])
    assert survivors(df).empty


def test_gate_raises_on_missing_columns():
    """Degrading to 'everything passes' when a column is absent is unacceptable."""
    df = pd.DataFrame([{"name": "s", "alpha_t": 9.0}])
    with pytest.raises(ValueError, match="alpha_ann_stress"):
        survivors(df)


def test_val_requires_same_sign_not_same_size():
    """A decayed but still positive alpha confirms; a reversed one does not."""
    ok = pd.DataFrame([_row(alpha_t=0.2, alpha_ann=0.002)])
    flipped = pd.DataFrame([_row(alpha_t=-0.9, alpha_ann=-0.07)])
    assert len(val_confirms(ok)) == 1
    assert val_confirms(flipped).empty


def test_val_confirms_raises_on_missing_columns():
    with pytest.raises(ValueError):
        val_confirms(pd.DataFrame([{"name": "s"}]))
