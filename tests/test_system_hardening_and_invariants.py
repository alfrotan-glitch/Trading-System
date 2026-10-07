"""Comprehensive System Hardening and Invariant Regression Tests.

Covers:
1. API Security & Local Operator Boundary:
   - External browser origins are blocked from mutating system state (CSRF / malicious web page attack).
   - Local origins (localhost, 127.0.0.1, preview proxy, webview) and local tools are allowed.
   - Read-only queries remain accessible.
2. Working Directory Independence:
   - Running from arbitrary CWD outside the repository root resolves machine-local state to repo root.
   - An isolated test folder containing its own data/ tree is respected without leaking.
3. Data Completeness Transparency:
   - /api/research/data-completeness reports exact expected vs observed rows, missing percentage,
     recognized closures, and fail-closed quality gate without interpolation or synthesis.
4. Execution Safety Invariants:
   - LIVE remains LOCKED under all mutation payloads.
   - Orders cannot bypass pre-trade gates or reconciliation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qts.api import server
from qts.config.paths import (
    paths_report,
    resolve_state_path,
    state_root,
)

# ---------------------------------------------------------------------------
# 1. API Security & Local Operator Boundary
# ---------------------------------------------------------------------------


def test_malicious_cross_origin_mutation_is_rejected():
    """An external website visited by the operator cannot mutate workstation state."""
    client = TestClient(server.app)

    malicious_origins = [
        "https://evil.com",
        "http://attacker.example.org",
        "https://malicious-script.xyz:8080",
    ]

    mutation_endpoints = [
        ("/api/setup/mt5", {"symbol": "XAUUSD"}),
        ("/api/observe/start", {}),
        ("/api/observe/stop", {}),
        ("/api/demo/enable", {"confirmed": True, "risk_ack": True}),
        ("/api/demo/disable", {}),
        ("/api/demo/kill", {}),
        ("/api/research/autonomous", {"max_trials": 2}),
    ]

    for origin in malicious_origins:
        for path, payload in mutation_endpoints:
            response = client.post(path, json=payload, headers={"Origin": origin})
            assert response.status_code == 403, f"Expected 403 for {path} from {origin}, got {response.status_code}"
            data = response.json()
            assert data["error"] == "FORBIDDEN_MUTATION"
            assert "untrusted origin" in data["detail"].lower()


def test_malicious_referer_mutation_is_rejected():
    """An external referer header without origin is also rejected for mutations."""
    client = TestClient(server.app)
    response = client.post(
        "/api/setup/mt5",
        json={"symbol": "XAUUSD"},
        headers={"Referer": "https://malicious-site.com/exploit.html"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "FORBIDDEN_MUTATION"


def test_trusted_origins_and_local_ui_can_mutate():
    """Localhost, 127.0.0.1, preview proxies and tools can safely mutate state."""
    client = TestClient(server.app)

    trusted_origins = [
        "http://localhost:8000",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "https://127.0.0.1:8000",
        "https://12345-sandbox.e2b.app",
        "tauri://localhost",
        "vscode-webview://",
    ]

    for origin in trusted_origins:
        # A trusted origin should pass the boundary middleware (it may fail validation, but not 403 FORBIDDEN_MUTATION)
        response = client.post(
            "/api/setup/mt5",
            json={"symbol": "XAUUSD", "symbol_map": {"XAUUSD": "XAUUSD@"}},
            headers={"Origin": origin, "X-QTS-Operator": "local-ui"},
        )
        assert response.status_code != 403, f"Trusted origin {origin} was unexpectedly blocked with 403"


def test_read_only_get_endpoints_are_not_blocked_by_origin():
    """Read-only GET endpoints are safe for monitoring from external dashboards/dashboards if allowed."""
    client = TestClient(server.app)
    # GET /api/health should not be rejected with 403
    response = client.get("/api/health", headers={"Origin": "https://dashboard.example.com"})
    assert response.status_code in (200, 503)  # Returns health, not 403 forbidden mutation


# ---------------------------------------------------------------------------
# 2. State Path & Working Directory Hardening
# ---------------------------------------------------------------------------


def test_paths_report_and_state_root_are_cwd_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Running from /tmp or any outside folder anchors to the repository root."""
    repo_root = state_root()
    assert (repo_root / "pyproject.toml").exists()

    # Change working directory to a random empty folder without a data/ directory
    outside_dir = tmp_path / "somewhere_else"
    outside_dir.mkdir()
    monkeypatch.chdir(outside_dir)

    # State root must still resolve to the real repository root, NOT to outside_dir!
    resolved_root = state_root()
    assert resolved_root == repo_root

    report = paths_report()
    assert report["cwd_independent"] is True
    assert report["state_root"] == str(repo_root)
    assert report["working_directory"] == str(outside_dir)

    # All default artifact paths are anchored to repo_root
    for _name, item in report["artifacts"].items():
        assert item["path"].startswith(str(repo_root))


def test_isolated_test_workspace_with_local_data_is_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When a test explicitly sets up a temporary data/ directory, state_root honours that isolation."""
    test_data = tmp_path / "data"
    test_data.mkdir()

    monkeypatch.chdir(tmp_path)
    isolated_root = state_root()
    assert isolated_root == tmp_path


def test_resolve_state_path_handles_relative_and_absolute():
    """resolve_state_path correctly expands relative paths against state root."""
    rel = resolve_state_path("data/evidence/test.json")
    assert rel.is_absolute()
    assert str(rel).endswith("data/evidence/test.json")

    abs_path = Path("/tmp/absolute_test.json")
    assert resolve_state_path(abs_path) == abs_path


# ---------------------------------------------------------------------------
# 3. Data Completeness Transparency
# ---------------------------------------------------------------------------


def test_data_completeness_endpoint_reports_authoritative_accounting():
    """The /api/research/data-completeness endpoint returns truthful, non-interpolated metrics."""
    client = TestClient(server.app)
    response = client.get("/api/research/data-completeness")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "AUDIT_COMPLETE_NO_RESEARCH_RERUN"
    assert data["recovery_outcome"] == "RECOVERABLE ONLY BY NEW ACQUISITION"

    recomp = data["independent_recomputation"]
    assert recomp["quality_gate"] == "FAIL"
    assert recomp["active_span_missing_pct"] > 2.0  # Must exceed 2% gate
    assert recomp["source_rows"] == 26038
    assert recomp["unexpected_missing_intervals"] == 1785
    assert recomp["recognized_closure_events"] == 57

    # Verify scope controls: no data was interpolated or synthesized
    scope = data["scope_controls"]
    assert scope["bars_interpolated_or_synthesized"] is False
    assert scope["trial_accounting_reset"] is False
    assert scope["research_rerun"] is False


# ---------------------------------------------------------------------------
# 4. Critical Safety Invariants
# ---------------------------------------------------------------------------


def test_live_trading_is_locked_against_all_wizard_and_api_payloads():
    """No payload to the API or wizard can ever declare or unlock LIVE trading."""
    from qts.config.wizard import save_setup

    client = TestClient(server.app)

    # 1. API refusal
    for forbidden in ["live", "LIVE", "micro", "MICRO", "production"]:
        res = client.post("/api/setup/mt5", json={"mode": forbidden})
        assert res.status_code == 400

    # 2. Wizard function refusal
    for forbidden in ["live", "LIVE", "micro"]:
        with pytest.raises(ValueError, match="LIVE is never declarable|cannot be declared"):
            save_setup({"mode": forbidden})


def test_kill_switch_vetoes_all_demo_orders():
    """When kill switch is active, orders are immediately refused without reaching broker."""
    from qts.risk.engine import RiskEngine, RiskLimits

    engine = RiskEngine(RiskLimits())
    engine.kill_switch(reason="invariant test halt")

    client = TestClient(server.app)
    r = client.post("/api/demo/order", json={"side": "BUY", "quantity": 0.01})
    assert r.status_code in (400, 403, 409, 422)
    # Cleans up kill switch
    engine.reset_kill()
