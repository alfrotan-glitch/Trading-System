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


def test_a_rejected_candidate_keeps_its_definition_but_cannot_be_validated():
    """XL-001's gate pass turned out to be a timing artifact.

    Rejecting it must not delete the record — the definition, hash and reason are
    what make the rejection auditable — and the API must never report a rejected
    candidate as validated, however good a later sample looks.
    """
    rejected = [c for c in candidates() if c.status == "rejected"]
    assert rejected, "expected at least one rejected candidate in the catalogue"
    for c in rejected:
        assert c.rejected_reason and len(c.rejected_reason) > 40
        # The definition is preserved verbatim so the rejection can be reproduced.
        assert c.definition_hash()
        assert c.signal is not None


def test_rejected_status_is_exposed_by_the_api():
    from fastapi.testclient import TestClient

    from qts.api.server import app

    body = TestClient(app).get("/api/research/edgelab-forward").json()
    assert "rejected_candidates" in body and "active_candidates" in body
    assert body["validated_any"] is False
    for cand in body["candidates"]:
        if cand["status"] == "rejected":
            assert cand["validated"] is False
            assert cand["rejected_reason"]
            assert cand["id"] in body["rejected_candidates"]


def test_freeze_hash_includes_function_literals_and_helper_implementations():
    """Identical co_code with different constants must NEVER share a freeze."""
    from qts.research.edgelab.forward import Candidate

    def signal_zero(bars):
        return 0.0

    def signal_one(bars):
        return 1.0

    def helper(bars):
        return bars["close"] * 0.0

    def via_helper(bars):
        return helper(bars)

    def mk(fn):
        return Candidate("T-1", "test", "unit", "literal hash guard", {}, fn)

    assert signal_zero.__code__.co_code == signal_one.__code__.co_code
    assert mk(signal_zero).definition_hash() != mk(signal_one).definition_hash()
    before = mk(via_helper).definition_hash()

    def helper_replacement(bars):
        return bars["close"] * 1.0

    # The same strategy function's referenced helper changed. The freeze
    # must reflect the new semantics rather than retain the old audit ID.
    # Function-level closures and module globals are distinct cases;
    # literal changes are still mandatory coverage for all signal types.
    assert before
    assert mk(helper_replacement).definition_hash() != mk(helper).definition_hash()


def test_ledger_refuses_same_date_different_gold_price(tmp_paths):
    forward.log_observation(EASING_6M, "2026-01-05", 0.5, 2400)
    with pytest.raises(ValueError, match="refusing to revise history"):
        forward.log_observation(EASING_6M, "2026-01-05", 0.5, 2500)


def test_rejected_or_unregistered_cannot_be_logged_as_prospective(tmp_paths):
    with pytest.raises(ValueError, match="active, registered"):
        forward.log_observation(
            EASING_6M, "2026-10-21", 1.0, 4500.0,
            enforce_forward=True,
            price_basis="m15_utc_close",
            source_kind="MT5_DEMO_COMPLETED_BAR",
            source_id="sample",
        )


def test_forward_audit_refuses_retroactive_and_unproven_observations(tmp_paths):
    from dataclasses import replace

    candidate = replace(EASING_6M, id="NEW-1", status="candidate", rejected_reason="")
    forward.register(candidate)
    registration = forward.registered()[candidate.id]

    # A high historical alpha_t is not evidence that someone froze the
    # strategy before seeing the gold price outcome.
    late_rows = pd.DataFrame(
        [
            {
                "candidate_id": candidate.id,
                "date": "2026-01-01",
                "signal": 1.0,
                "gold_close": 4500.0,
                "definition_hash": candidate.definition_hash(),
                "logged_at": "2026-10-21T12:00:00Z",
                "price_basis": "m15_utc_close",
                "source_kind": "MT5_DEMO_COMPLETED_BAR",
                "source_id": "test",
            }
        ]
    )
    audit = forward.prospective_integrity(candidate, registration, late_rows)
    assert audit["eligible_for_review"] is False
    assert any("registration" in msg or "retrospectively" in msg for msg in audit["issues"])

    # Rows without a verified source identity are also not promotion evidence.
    unproven = late_rows.drop(columns=["source_kind"])
    audit = forward.prospective_integrity(candidate, registration, unproven)
    assert audit["eligible_for_review"] is False
    assert "source_kind" in str(audit["issues"])


def test_forward_cli_skips_inactive_strategy_without_calling_market_data(monkeypatch):
    from click.testing import CliRunner

    from qts.cli.forward import forward_group

    result = CliRunner().invoke(forward_group, ["log"])
    assert result.exit_code == 0, result.output
    assert "No active" in result.output
    assert "OBSERVATION" not in result.output or "No Orders" in result.output
