"""End-to-end impulse research pipeline tests (tmp workspaces only).

Covers: fail-closed data handling, mechanism-validation mode on synthetic
data, trial-ledger accounting, determinism, evidence schema, placebo/null
behavior on GBM (no manufactured edge), and safety invariants.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from qts.data.bootstrap import bootstrap_data
from qts.data.store import SqliteParquetDataStore
from qts.data.synthetic import generate_gbm_bars
from qts.domain.value_objects import Instrument
from qts.research.experiment import ExperimentStore
from qts.research.impulse import (
    ImpulseResearchConfig,
    render_markdown_report,
    run_impulse_research,
)
from qts.research.impulse.analysis import run_impulse_analysis
from qts.research.impulse.definitions import PRE_REGISTERED_FAMILIES

FIXTURE = Path("data/fixtures/XAUUSD_1H_500.csv")


def _tmp_store(tmp_path: Path) -> SqliteParquetDataStore:
    root = tmp_path / "data"
    (root / "fixtures").mkdir(parents=True)
    shutil.copy(FIXTURE, root / "fixtures" / FIXTURE.name)
    store = SqliteParquetDataStore(root=root)
    res = bootstrap_data(store=store, root=root)
    assert res.ok, res.messages
    return store


FAST = ImpulseResearchConfig(n_boot=400)


class TestFailClosed:
    def test_no_usable_data_raises_with_honest_message(self, tmp_path):
        store = SqliteParquetDataStore(root=tmp_path / "empty")
        try:
            with pytest.raises(ValueError) as ei:
                run_impulse_research(store, ledger_db_path=tmp_path / "l.db", partition_db_path=tmp_path / "l.db")
            msg = str(ei.value)
            assert "no usable data version" in msg
            assert "No data was fabricated" in msg
        finally:
            store.close()

    def test_missing_fixture_fails_closed(self, tmp_path):
        store = SqliteParquetDataStore(root=tmp_path / "nofixture")
        try:
            res = bootstrap_data(store=store, root=tmp_path / "nofixture")
            assert res.status == "FAILED" and not res.ok
            assert store.list_versions() == []  # nothing invented
            with pytest.raises(ValueError) as ei:
                run_impulse_research(store, ledger_db_path=tmp_path / "l.db", partition_db_path=tmp_path / "l.db")
            assert "no usable data version" in str(ei.value)
        finally:
            store.close()


class TestMechanismValidationMode:
    def test_synthetic_fixture_blocks_real_claims(self, tmp_path):
        store = _tmp_store(tmp_path)
        try:
            ev = run_impulse_research(
                store,
                cfg=FAST,
                ledger_db_path=tmp_path / "ledger.db",
                partition_db_path=tmp_path / "ledger.db",
                evidence_dir=tmp_path / "data" / "evidence",
            )
        finally:
            store.close()
        assert ev["mode"] == "MECHANISM_VALIDATION"
        assert ev["provenance"]["data_class"] == "SYNTHETIC"
        assert ev["data_adequacy"]["adequate_for_real_claims"] is False
        assert ev["conclusion"]["conclusion"] == "BLOCKED_INSUFFICIENT_DATA"
        assert ev["conclusion"]["go_block"] == "BLOCK"
        assert ev["conclusion"]["real_market_claims_permitted"] is False

    def test_trial_ledger_accounts_every_trial(self, tmp_path):
        store = _tmp_store(tmp_path)
        ledger = tmp_path / "ledger.db"
        try:
            ev = run_impulse_research(
                store,
                cfg=FAST,
                ledger_db_path=ledger,
                partition_db_path=ledger,
                evidence_dir=tmp_path / "data" / "evidence",
            )
        finally:
            store.close()
        expected = len(PRE_REGISTERED_FAMILIES) * len(FAST.horizons) * 2  # splits: discovery+validation
        assert ev["analysis"]["totals"]["trials_recorded"] == expected
        es = ExperimentStore(db_path=ledger)
        assert es.count_trials() == expected
        # re-running appends — the ledger is cumulative and never reset
        store2 = _tmp_store(tmp_path / "second")
        try:
            ev2 = run_impulse_research(
                store2,
                cfg=FAST,
                ledger_db_path=ledger,
                partition_db_path=ledger,
                evidence_dir=tmp_path / "second" / "data" / "evidence",
            )
        finally:
            store2.close()
        assert ev2["analysis"]["ledger"]["ledger_trials_total"] == 2 * expected

    def test_locked_partition_untouched(self, tmp_path):
        store = _tmp_store(tmp_path)
        try:
            ev = run_impulse_research(
                store,
                cfg=FAST,
                ledger_db_path=tmp_path / "l.db",
                partition_db_path=tmp_path / "l.db",
                evidence_dir=tmp_path / "data" / "evidence",
            )
        finally:
            store.close()
        assert ev["analysis"]["locked_untouched"] is True
        assert ev["safety"]["locked_test_partition_accessed"] is False

    def test_events_carry_detection_time_and_decision_state(self, tmp_path):
        store = _tmp_store(tmp_path)
        try:
            ev = run_impulse_research(
                store,
                cfg=FAST,
                ledger_db_path=tmp_path / "l.db",
                partition_db_path=tmp_path / "l.db",
                evidence_dir=tmp_path / "data" / "evidence",
            )
        finally:
            store.close()
        pooled_primary = [
            r for r in ev["analysis"]["results"] if r["horizon"] == FAST.primary_horizon and r["split"] == "pooled"
        ]
        any_event = next(e for r in pooled_primary for e in r["events"])
        assert any_event["detection_time"]  # exact ISO detection timestamp
        assert any_event["decision_state"] in ("DETECTED_MEASURED", "DETECTED_EXCLUDED")
        assert any_event["direction"] in ("LONG", "SHORT")

    def test_sensitivity_present_for_every_family(self, tmp_path):
        store = _tmp_store(tmp_path)
        try:
            ev = run_impulse_research(
                store,
                cfg=FAST,
                ledger_db_path=tmp_path / "l.db",
                partition_db_path=tmp_path / "l.db",
                evidence_dir=tmp_path / "data" / "evidence",
            )
        finally:
            store.close()
        sens = ev["analysis"]["sensitivity"]
        ids = {f.family_id for f in PRE_REGISTERED_FAMILIES}
        assert set(sens["cost_multiplier"]) == ids
        assert set(sens["spread_multiplier"]) == ids
        assert set(sens["latency_bars"]) == ids


class TestDeterminism:
    def test_same_seed_identical_results(self, tmp_path):
        store_a = _tmp_store(tmp_path / "a")
        store_b = _tmp_store(tmp_path / "b")
        try:
            ev_a = run_impulse_research(
                store_a,
                cfg=FAST,
                ledger_db_path=tmp_path / "a.db",
                partition_db_path=tmp_path / "a.db",
                evidence_dir=tmp_path / "a" / "data" / "evidence",
            )
            ev_b = run_impulse_research(
                store_b,
                cfg=FAST,
                ledger_db_path=tmp_path / "b.db",
                partition_db_path=tmp_path / "b.db",
                evidence_dir=tmp_path / "b" / "data" / "evidence",
            )
        finally:
            store_a.close()
            store_b.close()
        strip = lambda ev: {k: ev["analysis"][k] for k in ("results", "sensitivity", "totals")}  # noqa: E731
        a, b = strip(ev_a), strip(ev_b)
        assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


class TestNullBehaviorOnGBM:
    def test_pure_gbm_produces_no_significant_edge(self, tmp_path):
        """On momentumless GBM the corrected p-values must not manufacture
        significance anywhere in the pre-registered family space."""
        bars = generate_gbm_bars(instrument=Instrument(symbol="XAUUSD"), periods=1500, seed=777)
        res = run_impulse_analysis(
            bars,
            data_version="GBM-NULL",
            provenance={"source_label": "synthetic:gbm"},
            cfg=ImpulseResearchConfig(seed=42, n_boot=400),
            ledger_db_path=None,
            data_root_db_path=tmp_path / "part.db",
        )
        primary_pooled = [
            r for r in res.results if r.horizon == res.config_snapshot["primary_horizon"] and r.split == "pooled"
        ]
        assert primary_pooled
        sig = [r for r in primary_pooled if r.p_holm < 0.05 and r.net_ci[0] > 0]
        assert sig == [], f"manufactured significance on null data: {[r.family_id for r in sig]}"

    def test_markdown_report_renders_from_evidence(self, tmp_path):
        store = _tmp_store(tmp_path)
        try:
            ev = run_impulse_research(
                store,
                cfg=FAST,
                ledger_db_path=tmp_path / "l.db",
                partition_db_path=tmp_path / "l.db",
                evidence_dir=tmp_path / "data" / "evidence",
            )
        finally:
            store.close()
        md = render_markdown_report(ev)
        assert "BLOCKED_INSUFFICIENT_DATA" in md
        assert "MECHANISM_VALIDATION" in md
        assert "Pre-registered design" in md
        assert "locked" in md.lower()
