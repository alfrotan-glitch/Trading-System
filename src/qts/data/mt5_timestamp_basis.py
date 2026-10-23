"""Validation of independently measured MT5 timestamp-basis evidence.

Raw MT5 acquisition manifests remain conservative and immutable after capture.
This module validates a separate evidence document before any time-of-day or
calendar research is allowed to use the raw timestamps as UTC.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

EVIDENCE_SCHEMA = "qts.mt5_timestamp_basis.v1"
ACQUISITION_SCHEMA = "qts.mt5_raw_tick_acquisition.v1"


def validate_timestamp_basis_evidence(
    evidence: Mapping[str, Any] | None,
    manifest: Mapping[str, Any],
) -> tuple[bool, str]:
    """Return whether *evidence* authorizes UTC interpretation for *manifest*.

    The check is deliberately strict: the evidence must be measured, read-only,
    produced by the same historical API, and explicitly bind the dataset digest
    to the observation. A free-form note or an unbound boolean never unlocks a
    dataset.
    """

    if evidence is None:
        return False, "no independent timestamp-basis evidence was supplied"
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        return False, "unsupported timestamp-basis evidence schema"
    if evidence.get("status") != "MEASURED_SAME_SESSION":
        return False, "timestamp-basis evidence is not a measured same-session result"
    if evidence.get("read_only") is not True:
        return False, "timestamp-basis evidence is not marked read-only"
    if evidence.get("orders_submitted") != 0 or evidence.get("order_send_called") is not False:
        return False, "timestamp-basis evidence does not prove the order path was unused"
    if evidence.get("historical_api") != "copy_ticks_range":
        return False, "timestamp-basis evidence does not cover copy_ticks_range"
    if evidence.get("historical_time_basis") != "UTC":
        return False, "timestamp-basis evidence does not establish UTC historical fields"
    if evidence.get("live_time_basis") != "SERVER_LOCAL":
        return False, "timestamp-basis evidence does not establish the live-bar basis"
    if manifest.get("schema") != ACQUISITION_SCHEMA:
        return False, "dataset is not a QTS raw MT5 acquisition manifest"
    digest = manifest.get("dataset_sha256")
    bound = evidence.get("dataset_sha256s")
    if not isinstance(digest, str) or not digest:
        return False, "dataset has no digest to bind"
    if not isinstance(bound, list) or digest not in bound:
        return False, "evidence is not bound to this dataset digest"
    return True, "same-session MT5 evidence binds copy_ticks_range raw time_msc to UTC"


def timestamp_basis_assessment(
    manifest: Mapping[str, Any],
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe whether the manifest's clock-dependent research is unlocked."""

    manifest_confirmed = manifest.get("timestamp_interpretation_confirmed") is True
    evidence_confirmed, reason = validate_timestamp_basis_evidence(evidence, manifest)
    confirmed = manifest_confirmed or evidence_confirmed
    if manifest_confirmed:
        reason = "manifest explicitly confirms the timestamp interpretation"
    return {
        "timestamp_interpretation_confirmed": confirmed,
        "manifest_confirmation": manifest_confirmed,
        "independent_evidence_confirmation": evidence_confirmed,
        "session_hour_weekday": "UNBLOCKED" if confirmed else "BLOCKED",
        "raw_interarrival_milliseconds": "USABLE_WITHOUT_TIMEZONE",
        "evidence": reason,
        "status": "CONFIRMED" if confirmed else "BLOCKED",
    }
