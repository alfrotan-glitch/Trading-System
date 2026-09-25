from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from qts.data.audit import audit_data_sources
from qts.domain.value_objects import Instrument, Tick
from qts.execution.reality import ExecutionObservation


def test_audit_machine_artifact_preserves_current_boundaries():
    audit = json.loads(Path("data/evidence/research_integrity_audit.json").read_text(encoding="utf-8"))

    assert audit["status"] == "AUDIT_COMPLETE_NO_RESEARCH_RERUN"
    assert audit["registered_real_snapshot"]["frozen_inventory_snapshot"]["unexpected_missing_intervals"] == 1493
    assert audit["registered_real_snapshot"]["frozen_inventory_snapshot"]["active_span_missing_pct"] == 5.42
    assert audit["safety"]["DEMO_EXECUTION"] == "DISABLED BY POLICY"
    assert audit["safety"]["LIVE"] == "LOCKED"
    assert audit["safety"]["trial_ledger_reset"] is False
    assert audit["safety"]["locked_partition_modified"] is False


def test_real_and_synthetic_artifacts_cannot_be_collapsed():
    real = json.loads(Path("data/evidence/impulse_research_xauusd_dukascopy_15m.json").read_text(encoding="utf-8"))
    synthetic = json.loads(Path("data/evidence/impulse_research.json").read_text(encoding="utf-8"))

    assert real["provenance"]["data_class"] == "REAL"
    assert synthetic["provenance"]["data_class"] == "SYNTHETIC"
    assert real["provenance"]["source_label"].startswith("REAL:dukascopy:")
    assert synthetic["provenance"]["source_label"].startswith("SYNTHETIC:")
    assert real["conclusion"]["go_block"] == "BLOCK"
    assert synthetic["conclusion"]["go_block"] == "BLOCK"


def test_forward_manifest_exporter_reports_zero_observations_from_an_empty_store(tmp_path, monkeypatch):
    """A manifest derived from an EMPTY canonical store must claim zero
    observations and no capital exposure — never inherited or invented ones.

    This used to read the COMMITTED
    ``data/evidence/forward_observation_manifest.json``. That file is a
    different exporter's artifact (the OBSERVE-ONLY ``ObservationCollector``
    schema: ``derived_export``/``class``/``mode``/``pipeline``/``session``/
    ``state``) and does not even contain the fields asserted here, so the test
    could only pass because an EARLIER test in the same run had overwritten the
    committed file with a freshly derived all-zero manifest from an empty local
    store. The suite therefore passed by destroying the only surviving record of
    a real MT5 DEMO observation session (FS-f374b6, 13222 ticks,
    ENDED_ON_ERRORS) and then asserting on the wreckage.

    Both tests now derive into ``tmp_path``, and a session-scoped guard in
    ``tests/conftest.py`` fails the run if any tracked file is modified.
    """
    from qts.observability.forward_observatory import ForwardObservatory

    monkeypatch.chdir(tmp_path)
    store = tmp_path / "data" / "sqlite" / "forward_observatory.db"
    derived = tmp_path / "data" / "evidence" / "forward_observation_manifest.json"
    manifest = ForwardObservatory(db_path=store).to_manifest(derived)

    assert manifest["active_observation_sessions"] == 0
    assert manifest["ticks_recorded"] == 0
    assert manifest["real_market_ticks"] == 0
    assert manifest["signals_recorded"] == 0
    assert manifest["no_capital_exposure"] is True
    assert "derived" in manifest["canonical_store"] or manifest["derived_from"]
    assert manifest["derived_from"] == str(store)
    assert derived.exists()


def test_committed_forward_manifest_claims_observation_only_and_preserves_its_failure():
    """Integrity of the COMMITTED collector export, asserted against ITS schema.

    It records a real MT5 DEMO OBSERVE_ONLY session. It must never be readable
    as execution evidence, and the inconvenient outcome (the session ended on a
    stale-tick error) must still be present in the file rather than smoothed
    into a clean summary.
    """
    manifest = json.loads(Path("data/evidence/forward_observation_manifest.json").read_text(encoding="utf-8"))

    # observe-only, demo-class, no order was ever sent
    assert manifest["mode"] == "OBSERVE_ONLY"
    assert manifest["class"] == "DEMO"
    assert manifest["derived_export"] is True
    assert manifest["orders_submitted"] == 0
    assert manifest["order_send_called"] is False
    note = manifest["data_class_note"]
    assert "no synthetic" in note and "LIVE/REAL" in note, "the DEMO/OBSERVE_ONLY disclaimer must stay in the export"

    # real observations were recorded, and the failure that ended the session is
    # preserved rather than hidden
    assert manifest["ticks_recorded"] > 0
    assert manifest["session"]["status"] == "ENDED_ON_ERRORS"
    assert manifest["state"] == "STOPPED_ON_ERRORS"
    assert manifest["last_error"], "the error that stopped the session must remain visible in the evidence"
    assert manifest["session"]["meta"]["orders_possible"] is False

    # this is the collector schema, NOT a ForwardObservatory.to_manifest() export
    assert "active_observation_sessions" not in manifest
    assert "no_capital_exposure" not in manifest


def test_forward_manifest_path_has_two_exporters_with_incompatible_schemas():
    """KNOWN DEFECT, locked so it cannot hide behind test ordering.

    Two exporters default to the SAME audit-trail path with different,
    non-overlapping schemas:

    * ``ObservationCollector.write_manifest()`` — session/provenance schema
      (``derived_export``, ``class``, ``mode``, ``pipeline``, ``session``,
      ``state``, ``last_error``);
    * ``ForwardObservatory.to_manifest()`` — store-summary schema
      (``active_observation_sessions``, ``ticks_by_provenance``,
      ``no_capital_exposure``, ``derived_from``, ``sample_ticks``).

    Neither is a superset of the other, so whichever runs last silently replaces
    the other's export and a reader or gate cannot tell which schema it holds.
    That is exactly how the committed real-session export got overwritten with
    an all-zero one.

    Picking the canonical owner of this path (or splitting it into two
    filenames) is an evidence-layout decision with doc, API and gate
    consequences, so it is documented here rather than resolved unilaterally.
    If the conflict is ever fixed, DELETE this test; if it fails, the defaults
    changed and the docs referencing the path must be updated in the same
    change.
    """
    import inspect

    from qts.observability.demo_collector import ObservationCollector
    from qts.observability.forward_observatory import ForwardObservatory

    collector_default = inspect.signature(ObservationCollector.__init__).parameters["manifest_path"].default
    observatory_default = inspect.signature(ForwardObservatory.to_manifest).parameters["path"].default
    assert Path(str(collector_default)) == Path(str(observatory_default)), (
        "the two forward-manifest exporters no longer share a default path — the schema conflict "
        "was resolved; delete this characterization test and update every doc/gate that reads the path"
    )


def test_audit_projection_exposes_roles_and_gap_semantics_for_registered_inventory():
    result = audit_data_sources()
    row = result["available_sources"][0]

    assert row["venue_semantics"] == "legacy_dataset_namespace_only"
    assert row["execution_target"] is None
    assert row["execution_venue"] is None
    assert "gap_semantics" in row["timestamp_quality"]


def test_ambiguous_domain_ticks_and_execution_records_are_not_real_by_default():
    tick = Tick(
        instrument=Instrument(symbol="XAUUSD"),
        bid=Decimal("2000"),
        ask=Decimal("2000.5"),
        event_time=datetime.now(UTC),
    )
    assert tick.source == "UNVERIFIED"
    assert ExecutionObservation.model_fields["source"].default == "UNVERIFIED"
