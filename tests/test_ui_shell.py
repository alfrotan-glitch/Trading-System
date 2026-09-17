"""UI shell integrity — served-contract tests (TestClient, always run).

Asserts the structural product decisions that must never silently regress:
* the shell serves with the new design system and grouped IA
* every referenced asset exists (no dead links)
* accessibility scaffolding (skip link, aria landmarks, focus styles)
* truthfulness primitives are in the UI layer (UNAVAILABLE handling)
* the UI is self-contained: no CDN/external dependencies (offline desktop)
* the old flat 28-tab navigation is gone
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "src" / "qts" / "desktop" / "ui"
JS = UI / "js"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient as TC

    from qts.api.server import app

    with TC(app) as c:
        yield c


def _get(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    return r


def test_shell_serves_with_design_system(client):
    html = _get(client, "/").text
    assert "css/tokens.css" in html
    assert "js/main.js" in html
    assert 'type="module"' in html
    assert "skip-link" in html  # a11y


def test_all_shell_assets_exist(client):
    html = _get(client, "/").text
    assets = re.findall(r'(?:href|src)="([^"]+)"', html)
    assets = [a for a in assets if not a.startswith(("data:", "http"))]
    assert assets, "shell references assets"
    for a in assets:
        _get(client, a)


def test_no_external_cdn_dependencies(client):
    """Offline desktop product — no external origins anywhere in the UI."""
    for p in list(UI.rglob("*.html")) + list(JS.rglob("*.js")) + list((UI / "css").glob("*.css")):
        src = p.read_text(encoding="utf-8")
        external = re.findall(r'https?://[a-z0-9.-]+\.[a-z]{2,}', src, re.I)
        external = [u for u in external if "www.w3.org" not in u]  # SVG namespace only
        assert not external, f"{p.name} references external origin(s): {external}"


def test_flat_tab_navigation_is_gone(client):
    html = _get(client, "/").text
    assert "data-view=" not in html, "old flat nav markup still present"
    src = (JS / "main.js").read_text(encoding="utf-8")
    top_level_groups = re.findall(r'^  \{', src, re.M)
    assert len(top_level_groups) == 8, "IA must have exactly 8 primary areas"


def test_semantic_state_system_exists():
    tokens = (UI / "css" / "tokens.css").read_text(encoding="utf-8")
    for var in ["--ok:", "--warn:", "--err:", "--neutral:", "--research:", "--locked:", "--run:", "--info:"]:
        assert var in tokens, f"semantic token {var} missing"
    # every semantic color must have a redundant encoding in components (dot shapes)
    comps = (UI / "css" / "components.css").read_text(encoding="utf-8")
    assert ".dot.square" in comps and ".dot.tri" in comps, "status marks must not rely on color alone"


def test_truthfulness_primitives_present():
    fmt = (JS / "format.js").read_text(encoding="utf-8")
    assert "UNAVAILABLE" in fmt
    # the renderer formats numbers only inside the MEASURED branch
    assert "fmtNum(m.value, digits)" in fmt
    measured_idx = fmt.index('m.status === "MEASURED"')
    fmtcall_idx = fmt.index("fmtNum(m.value, digits)")
    assert fmt.index("UNAVAILABLE") > 0 and measured_idx < fmtcall_idx < fmt.index("return humanStatus")
    status = (JS / "status.js").read_text(encoding="utf-8")
    assert "NOT EVALUATED" in status  # null gates render explicitly


def test_raw_evidence_layer_present():
    comps = (JS / "components.js").read_text(encoding="utf-8")
    assert "Technical details" in comps, "raw evidence toggle must exist"
    overview = (JS / "views" / "overview.js").read_text(encoding="utf-8")
    assert "Raw overview snapshot" in overview


def test_views_cover_all_legacy_functionality():
    """Every legacy page's data has a home in the new IA (nothing dropped)."""
    endpoints_used = set()
    for p in JS.rglob("*.js"):
        endpoints_used |= set(re.findall(r'"/api/[^"]+"', p.read_text(encoding="utf-8")))
    required = [
        "/api/health", "/api/dashboard", "/api/risk", "/api/mt5", "/api/audit",
        "/api/live/status", "/api/paper", "/api/shadow", "/api/execution/orders",
        "/api/demo/readiness", "/api/demo/state", "/api/demo/safety", "/api/demo/config",
        "/api/demo/observations", "/api/demo/comparison",
        "/api/observe/status", "/api/observe/start", "/api/observe/stop",
        "/api/setup/mt5", "/api/env/boundary", "/api/notifications",
        "/api/research/campaigns", "/api/research/hypotheses", "/api/research/memory",
        "/api/research/novelty", "/api/research/statistical", "/api/research/data-audit",
        "/api/research/data-inventory", "/api/research/data-quality-adversarial",
        "/api/research/data-source-catalog", "/api/research/forward-manifest",
        "/api/research/execution-reality", "/api/research/regime-observations",
    ]
    missing = [e for e in required if f'"{e}' not in " ".join(endpoints_used)]
    assert not missing, f"legacy endpoints with no UI home: {missing}"


def test_validation_and_strategies_views_present():
    assert (JS / "views" / "research.js").read_text(encoding="utf-8").count("export async function") >= 7
