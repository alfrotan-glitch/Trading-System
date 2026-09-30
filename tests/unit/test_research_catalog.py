"""The hypothesis catalog is an index, not a second research implementation."""

import pytest

from qts.research.catalog import CURRENT_EDGE_STATUS, dispatch_hypothesis, list_hypotheses, resolve_hypothesis


def test_catalog_does_not_promote_any_hypothesis():
    rows = list_hypotheses()
    assert rows
    assert {row["edge_status"] for row in rows} == {CURRENT_EDGE_STATUS}
    assert {row["trading_authorization"] for row in rows} == {"NONE"}
    assert CURRENT_EDGE_STATUS == "NO_VALIDATED_EDGE"


def test_unknown_hypothesis_fails_closed_without_running_research():
    assert resolve_hypothesis("H-NOT-A-REAL-EDGE") is None
    with pytest.raises(SystemExit, match="unknown hypothesis"):
        dispatch_hypothesis("H-NOT-A-REAL-EDGE", [])


def test_known_ids_resolve_to_existing_runners():
    spec = resolve_hypothesis("h-temp-01")
    assert spec is not None
    assert spec["id"] == "H-TEMP-01"
    assert spec["module"] == "scripts.run_xauusd_temporal"
