"""Forward observation: the pipeline that produces evidence backtests cannot.

The properties that matter are integrity properties, not statistics:

* a registered candidate cannot be edited quietly and keep its track record;
* an observation cannot be revised once its outcome is known;
* a ledger with one row reports "insufficient", not a number.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from qts.research.edgelab import forward
from qts.research.edgelab.candidates import EASING_6M, candidates


@pytest.fixture()
def tmp_paths(tmp_path, monkeypatch):
    reg = tmp_path / "candidates.json"
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(forward, "_registry_path", lambda explicit=None: reg if explicit is None else explicit)
    monkeypatch.setattr(forward, "_ledger_path", lambda explicit=None: led if explicit is None else explicit)
    return reg, led


def test_catalogue_has_a_stated_rationale():
    for c in candidates():
        assert c.rationale and len(c.rationale) > 40
        assert c.params
        assert c.id and c.name


def test_registration_freezes_the_definition(tmp_paths):
    forward.register(EASING_6M)
    stored = forward.registered()[EASING_6M.id]
    assert stored["definition_hash"] == EASING_6M.definition_hash()


def test_editing_a_registered_candidate_is_refused(tmp_paths):
    """A candidate that changes after registration invalidates its track record."""
    forward.register(EASING_6M)

    class Impostor:
        id = EASING_6M.id
        name = EASING_6M.name
        family = EASING_6M.family
        rationale = EASING_6M.rationale
        params = EASING_6M.params

        @staticmethod
        def signal(bars):  # different bytecode -> different hash
            return bars["close"] * 0.0 + 1.0

        def definition_hash(self):
            return "deadbeefdeadbeef"

        def as_dict(self):
            return {
                "id": self.id,
                "name": self.name,
                "family": self.family,
                "rationale": self.rationale,
                "params": self.params,
                "definition_hash": self.definition_hash(),
            }

    with pytest.raises(ValueError, match="different definition"):
        forward.register(Impostor())


def test_observation_is_append_only(tmp_paths):
    forward.registry = None  # no-op guard for linters
    forward.log_observation(EASING_6M, "2026-01-05", 1.0, 2400.0)
    # Same value is idempotent.
    again = forward.log_observation(EASING_6M, "2026-01-05", 1.0, 2400.0)
    assert again["signal"] == 1.0
    # A revised value for a date already recorded is refused.
    with pytest.raises(ValueError, match="refusing to revise history"):
        forward.log_observation(EASING_6M, "2026-01-05", 0.0, 2400.0)


def test_signal_outside_unit_interval_is_rejected(tmp_paths):
    with pytest.raises(ValueError, match="outside"):
        forward.log_observation(EASING_6M, "2026-01-05", 1.5, 2400.0)
    with pytest.raises(ValueError, match="positive"):
        forward.log_observation(EASING_6M, "2026-01-05", 1.0, 0.0)


def test_single_observation_reports_insufficient_not_a_number(tmp_paths):
    forward.log_observation(EASING_6M, "2026-01-05", 1.0, 2400.0)
    out = forward.score(forward.load_ledger())
    assert len(out) == 1
    row = out.iloc[0]
    assert row["observations"] == 1
    assert row["status"] == "insufficient"
    assert pd.isna(row["alpha_t"])


def test_score_matches_a_hand_computation(tmp_paths):
    """Full exposure, no turnover: net return must equal buy-and-hold minus costs."""
    # Varying returns, so the benchmark has non-zero variance and beta is defined.
    prices = [100.0, 110.0, 105.0, 115.5]
    for i, px in enumerate(prices):
        forward.log_observation(EASING_6M, f"2026-01-0{i + 5}", 1.0, px)
    out = forward.score(forward.load_ledger()).iloc[0]
    from qts.research.edgelab import CostModel

    # Always fully invested: gross return equals buy-and-hold, less one entry cost.
    gross = (110 / 100) * (105 / 110) * (115.5 / 105)
    expected = gross - 1.0 - CostModel().per_side_bps() / 1e4
    assert out["total_return"] == pytest.approx(expected, abs=1e-3)
    # Fully invested in the benchmark means beta ~ 1; the tiny gap is the cost term.
    assert out["beta"] == pytest.approx(1.0, abs=0.05)


def test_staleness_warning_fires_only_when_stale():
    assert forward.staleness_warning(pd.Timestamp("2026-01-10"), pd.Timestamp("2026-01-09")) is None
    warn = forward.staleness_warning(pd.Timestamp("2026-03-01"), pd.Timestamp("2026-01-09"))
    assert warn is not None and "stale" in warn


def test_registry_file_is_valid_json(tmp_paths):
    forward.register(EASING_6M)
    reg, _ = tmp_paths
    doc = json.loads(reg.read_text(encoding="utf-8"))
    assert EASING_6M.id in doc["candidates"]


def test_api_reports_unvalidated_without_forward_evidence():
    """The API must never report a candidate as validated on registration alone."""
    from fastapi.testclient import TestClient

    from qts.api.server import app

    client = TestClient(app)
    resp = client.get("/api/research/edgelab-forward")
    assert resp.status_code == 200
    body = resp.json()
    assert body["live_locked"] is True
    assert body["real_capital_exposure_usd"] == 0
    assert "ASSUMED" in body["cost_basis"]
    # Both rates must be named: the harness default and the realistic ECN rate the
    # candidate is actually reported against. Naming only the optimistic one would
    # tell a reader the scores were produced under a cost they were not.
    assert "0.40" in body["cost_basis"] and "0.93" in body["cost_basis"]
    assert body["validated_any"] is False
    for cand in body["candidates"]:
        if not cand["forward"] or cand["forward"].get("observations", 0) < 3:
            assert cand["validated"] is False
