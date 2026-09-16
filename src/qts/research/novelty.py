"""Novelty / Diversity Control — cluster hypotheses, report distinct vs total trials."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any


def hypothesis_fingerprint(family: str, mechanism: str, feature_lineage: list[str], param_keys: list[str]) -> str:
    """Cluster related hypotheses — 500 tiny variations of same idea should not count as 500 independent discoveries."""
    payload = json.dumps({"family": family, "mechanism": mechanism, "features": sorted(feature_lineage), "param_keys": sorted(param_keys)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def cluster_hypotheses(trials: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trials:
        fp = hypothesis_fingerprint(t.get("family",""), t.get("mechanism",""), t.get("feature_lineage",[]), list(t.get("params",{}).keys()))
        clusters[fp].append(t)
    return clusters


def distinct_hypotheses_count(trials: list[dict[str, Any]]) -> int:
    return len(cluster_hypotheses(trials))


def report_novelty(trials: list[dict[str, Any]]) -> dict[str, Any]:
    clusters = cluster_hypotheses(trials)
    return {
        "total_trials": len(trials),
        "distinct_hypotheses": len(clusters),
        "largest_cluster_size": max(len(v) for v in clusters.values()) if clusters else 0,
        "clusters": {k: len(v) for k, v in clusters.items()},
        "honest_note": f"{len(trials)} trials but only {len(clusters)} materially distinct hypotheses — essential for honest multiple-testing"
    }
