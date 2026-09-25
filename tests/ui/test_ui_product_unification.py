"""Productization, UI/UX Unification & Executive Interface Regression Tests.

Asserts:
1. Product Information Architecture:
   - Product navigation first, engineering pages under Advanced.
   - All legacy endpoints accounted for.
2. Decision-First Executive Dashboard:
   - Telemetry cards addressing the 6 core product questions:
     * Market Status
     * Opportunity Status
     * Execution Permission
     * Capital Exposure
     * Safety Controls
     * Attention Required
3. Plain-Language Humanization:
   - Technical codes translated into clear, professional operator language.
   - No raw, frightening, or unexplained machine states.
4. Execution & Safety Clarity:
   - DEMO environment clearly distinguished from simulation and live.
   - LIVE trading gate is permanently locked with zero capital exposure.
5. Data Quality & Completeness:
   - Truthful non-interpolated accounting reported honestly.
6. Design System & CSS Invariants:
   - Calm, restrained institutional design tokens without gaming clutter.
   - Semantic color system with redundant status glyphs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qts.api.server import app

UI_DIR = Path(__file__).resolve().parents[2] / "src" / "qts" / "desktop" / "ui"
JS_DIR = UI_DIR / "js"
CSS_DIR = UI_DIR / "css"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Product Navigation & Information Architecture
# ---------------------------------------------------------------------------


def test_ia_has_product_navigation_and_advanced_disclosure():
    """Product tasks come first. Engineering pages stay available under Advanced."""
    main_src = (JS_DIR / "main.js").read_text(encoding="utf-8")
    top_level_groups = re.findall(r"^  \{", main_src, re.M)
    assert len(top_level_groups) == 9, f"Expected 9 primary groups, found {len(top_level_groups)}"

    expected_groups = [
        "Home",
        "Market",
        "Opportunities",
        "Trading",
        "Risk",
        "Reports",
        "Research",
        "System",
        "Governance",
    ]
    for grp in expected_groups:
        assert f'label: "{grp}"' in main_src, f"Primary group {grp} missing in IA"
    assert 'section: "Advanced"' in main_src
    assert "restricted: true" in main_src


def test_all_legacy_endpoints_have_ui_representation():
    """All 33 system endpoints must be actively represented across the product views."""
    endpoints_used = set()
    for p in JS_DIR.rglob("*.js"):
        endpoints_used |= set(re.findall(r'"/api/[^"]+"', p.read_text(encoding="utf-8")))

    mandatory_endpoints = [
        "/api/health",
        "/api/dashboard",
        "/api/risk",
        "/api/mt5",
        "/api/audit",
        "/api/live/status",
        "/api/paper",
        "/api/shadow",
        "/api/execution/orders",
        "/api/demo/readiness",
        "/api/demo/state",
        "/api/demo/safety",
        "/api/demo/config",
        "/api/demo/observations",
        "/api/demo/comparison",
        "/api/observe/status",
        "/api/observe/start",
        "/api/observe/stop",
        "/api/setup/mt5",
        "/api/env/boundary",
        "/api/notifications",
        "/api/research/campaigns",
        "/api/research/hypotheses",
        "/api/research/memory",
        "/api/research/novelty",
        "/api/research/statistical",
        "/api/research/data-audit",
        "/api/research/data-inventory",
        "/api/research/data-quality-adversarial",
        "/api/research/data-source-catalog",
        "/api/research/forward-manifest",
        "/api/research/execution-reality",
        "/api/research/regime-observations",
        "/api/research/data-completeness",
    ]

    joined_src = " ".join(endpoints_used)
    for ep in mandatory_endpoints:
        assert f'"{ep}' in joined_src, f"Mandatory endpoint {ep} missing in UI views"


# ---------------------------------------------------------------------------
# 2. Executive Dashboard & Decision-First Design
# ---------------------------------------------------------------------------


def test_executive_dashboard_features_6_telemetry_pillars():
    """Dashboard must structure telemetry answering the 6 core product questions."""
    overview_src = (JS_DIR / "views" / "overview.js").read_text(encoding="utf-8")
    assert "No validated opportunity" in overview_src
    assert "Live trading locked" in overview_src
    assert "Not at risk" in overview_src

    # The home cards answer the operator questions in plain language:
    assert 'label: "Gold"' in overview_src
    assert 'label: "Opportunity"' in overview_src
    assert 'label: "Trading"' in overview_src
    assert 'label: "Your money"' in overview_src
    assert 'label: "Safety"' in overview_src
    assert 'label: "Next"' in overview_src

    # Operating facts table with mandatory data-fact attributes
    for fact in ["mode", "broker", "market", "quoteAge", "observation", "permission", "liveLabel"]:
        assert f'fact: "{fact}"' in overview_src or f"fact: '{fact}'" in overview_src or f'fact === "{fact}"' in overview_src or f'["{fact}"' in overview_src, f"Operating fact {fact} missing in dashboard"


def test_dashboard_humanizes_machine_state_codes():
    """Technical state codes like STAGE_1_CONNECTIVITY_ONLY must be humanized."""
    overview_src = (JS_DIR / "views" / "overview.js").read_text(encoding="utf-8")
    assert "Connection Test Mode — Orders Disabled" in overview_src
    assert "Trading Disabled by Safety Policy" in overview_src
    assert "System Ready — Research Blocked" in overview_src


# ---------------------------------------------------------------------------
# 3. Execution & Safety Posture
# ---------------------------------------------------------------------------


def test_trading_view_renders_execution_cockpit():
    """Trading view must present the unmistakable Execution Cockpit card."""
    trading_src = (JS_DIR / "views" / "trading.js").read_text(encoding="utf-8")
    assert "Execution Cockpit — Decision & Safety Posture" in trading_src
    assert "DEMO EXECUTION: DISABLED BY POLICY" in trading_src
    assert "LIVE LOCKED" in trading_src
    assert "Safety checks are on" in trading_src
    assert "Not at risk" in trading_src
    assert "REAL CAPITAL: OFF" in (JS_DIR / "views" / "risk.js").read_text(encoding="utf-8")


def test_live_trading_is_unmistakably_locked():
    """Live trading must remain structurally locked and calm."""
    gov_src = (JS_DIR / "views" / "governance.js").read_text(encoding="utf-8")
    assert "LIVE — " in gov_src
    assert "LOCKED" in gov_src
    assert "Real capital lives behind this gate" in gov_src


# ---------------------------------------------------------------------------
# 4. Opportunity & Research Presentation
# ---------------------------------------------------------------------------


def test_research_validation_translates_opportunity_disposition():
    """Validation view must classify opportunities in human terms rather than raw math."""
    research_src = (JS_DIR / "views" / "research.js").read_text(encoding="utf-8")
    assert "Opportunity Evaluation — Plain Language Disposition" in research_src
    assert "NO VALIDATED EDGE" in research_src
    assert "A file pass does not permit an order" in research_src
    assert "VALIDATED CANDIDATE" not in research_src
    assert "READY FOR DEMO" not in research_src


# ---------------------------------------------------------------------------
# 5. Data Completeness & Quality UX
# ---------------------------------------------------------------------------


def test_market_quality_presents_honest_completeness():
    """Data quality screen must honestly display completeness without synthetic interpolation."""
    market_src = (JS_DIR / "views" / "market.js").read_text(encoding="utf-8")
    assert "Historical Data Quality & Integrity" in market_src
    assert "ZERO SYNTHESIS" in market_src
    assert "No data was fabricated or interpolated" in market_src
    assert "/api/research/data-completeness" in market_src


# ---------------------------------------------------------------------------
# 6. Design System & Accessibility
# ---------------------------------------------------------------------------


def test_design_tokens_adhere_to_professional_restraint():
    """Design system must be calm and professional, retaining semantic status tokens."""
    tokens_src = (CSS_DIR / "tokens.css").read_text(encoding="utf-8")
    for token in ["--bg-0:", "--bg-1:", "--bg-2:", "--line:", "--text-1:", "--accent:"]:
        assert token in tokens_src

    for status_token in ["--ok:", "--warn:", "--err:", "--neutral:", "--research:", "--locked:", "--run:", "--info:"]:
        assert status_token in tokens_src, f"Mandatory status token {status_token} missing"


def test_components_retain_redundant_non_color_glyphs():
    """Component styles must include dot shapes for non-color dependent accessibility."""
    comps_src = (CSS_DIR / "components.css").read_text(encoding="utf-8")
    assert ".badge .dot.square" in comps_src
    assert ".badge .dot.tri" in comps_src


def test_shell_serves_cleanly_via_fastapi(client):
    """The root application shell must serve with 200 OK and no broken assets."""
    res = client.get("/")
    assert res.status_code == 200
    assert "QTS Trading System" in res.text
    assert 'href="css/tokens.css"' in res.text
    assert 'src="js/main.js"' in res.text
