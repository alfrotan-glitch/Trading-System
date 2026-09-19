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


def test_forward_manifest_is_zero_observation_derived_state():
    manifest = json.loads(Path("data/evidence/forward_observation_manifest.json").read_text(encoding="utf-8"))

    assert manifest["active_observation_sessions"] == 0
    assert manifest["ticks_recorded"] == 0
    assert manifest["real_market_ticks"] == 0
    assert manifest["no_capital_exposure"] is True
    assert "derived" in manifest["canonical_store"] or manifest["derived_from"]


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
