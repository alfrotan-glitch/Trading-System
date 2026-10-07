"""Regression guards for the broker-capable micro execution boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from qts.config.paths import artifact_path
from qts.risk.authority import engine_limits_from, resolve_risk_limits_from_settings
from qts.risk.engine import RiskEngine

REPO = Path(__file__).resolve().parents[1]
OPS = REPO / "src" / "qts" / "cli" / "ops.py"


def test_micro_uses_canonical_risk_authority_without_temp_database() -> None:
    """The micro path must not create an isolated safety database."""
    source = OPS.read_text(encoding="utf-8")
    tree = ast.parse(source)

    micro_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "run_cmd"
    ]
    assert micro_nodes, "run_cmd must remain the canonical CLI entry point"

    assert 'if mode == "micro":' in source
    assert "tempfile" not in source[source.index('if mode == "micro":') :]
    assert "mkstemp" not in source[source.index('if mode == "micro":') :]
    assert "resolve_risk_limits_from_settings" in source
    assert "engine_limits_from" in source
    assert "load_reconcile_suspension" in source


def test_canonical_risk_engine_uses_the_canonical_safety_database() -> None:
    """A default RiskEngine must resolve to the canonical artifact database."""
    engine = RiskEngine(engine_limits_from(resolve_risk_limits_from_settings("LIVE")))
    assert Path(engine.db_path).resolve() == artifact_path("db").resolve()
