"""Productization, UI/UX Unification & Executive Interface Regression Tests.

Asserts:
1. Product Information Architecture:
   - Four primary pages (Home / Market / Trading / Reports) for a normal
     user; every engineering surface under one quiet Advanced area.
   - Legacy product URLs redirect into the new IA.
   - All legacy endpoints accounted for.
2. Plain-Language Home (command center):
   - System status, demo account, gold price, opportunity and money-safety
     answered in plain language from the guided API — nothing invented.
   - Internal state names (STAGE_, HALTED, readiness IDs, pins) never leak
     into primary pages.
3. Execution & Safety Clarity:
   - DEMO environment clearly distinguished from simulation and live.
   - LIVE trading gate is permanently locked with zero capital exposure.
4. Data Quality & Completeness:
   - Truthful non-interpolated accounting reported honestly.
5. Design System & CSS Invariants:
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
    """Four product pages for a normal user. ALL engineering under one quiet Advanced."""
    main_src = (JS_DIR / "main.js").read_text(encoding="utf-8")

    # Exactly four primary pages, in product order.
    primary = re.findall(r'id: "([a-z]+)", label: "[^"]+", section: "Product"', main_src)
    assert primary == ["home", "market", "trading", "reports"], primary

    # One Advanced group — collapsed by default, holding every engineering page.
    assert 'id: "advanced", label: "Advanced"' in main_src
    advanced_children = re.findall(r'\{ id: "([a-z0-9-]+)", label: "[^"]+", sub: "[^"]+", render:', main_src)
    assert len(advanced_children) == 20, advanced_children
    for page_id in ["research-campaigns", "data-observations", "trading-history", "risk", "audit", "governance", "system-diagnostics"]:
        assert page_id in advanced_children, f"engineering page {page_id} must live under Advanced"

    # Engineering vocabulary must NOT be primary navigation.
    for forbidden in ["Opportunities", "Risk controls", "Diagnostics", "Governance", "Campaigns", "Lineage"]:
        assert f'label: "{forbidden}", section: "Product"' not in main_src

    # Legacy product URLs keep working through redirects.
    assert '"#/overview": "#/home"' in main_src
    assert '"#/trading/demo": "#/trading"' in main_src
    assert '"#/governance/live": "#/advanced/governance"' in main_src


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
# 2. Product Home — plain answers, no invented data
# ---------------------------------------------------------------------------


def test_home_answers_the_product_questions_in_plain_language():
    """Home must answer: status, account, gold, opportunity, money — plainly."""
    home_src = (JS_DIR / "views" / "overview.js").read_text(encoding="utf-8")
    assert "System status" in home_src
    assert "Demo account" in home_src
    assert "Gold — XAUUSD" in home_src
    assert "Trading opportunity" in home_src
    assert "No validated trading opportunity right now." in home_src
    assert "Not at risk" in home_src
    assert "Live trading stays locked" in home_src
    # honesty contract: a missing price is a sentence, never a number
    assert "Current price unavailable" in home_src


def test_home_never_shows_internal_state_names():
    """Stage/gate/authority internals must not appear in the product home."""
    home_src = (JS_DIR / "views" / "overview.js").read_text(encoding="utf-8")
    for forbidden in ["STAGE_1", "STAGE_2", "STAGE_3", "HALTED", "readiness_passed", "identity_pin", "preflight"]:
        assert forbidden not in home_src, f"internal name {forbidden} leaked into the product home"
    # the single allowed disclosure is behind an explicit Technical details toggle
    assert "Technical details" in home_src


# ---------------------------------------------------------------------------
# 3. Execution & Safety Posture
# ---------------------------------------------------------------------------


def test_trading_view_renders_execution_cockpit():
    """Trading view must present the unmistakable Execution Cockpit card."""
    trading_src = (JS_DIR / "views" / "trading.js").read_text(encoding="utf-8")
    assert "Trading status" in trading_src
    assert "Real money stays locked" in trading_src
    assert "DEMO EXECUTION: DISABLED BY POLICY" in trading_src
    assert "LIVE LOCKED" in trading_src
    assert "Safety checks are on" in trading_src
    assert "Not at risk" in trading_src
    assert "REAL CAPITAL: OFF" in (JS_DIR / "views" / "risk.js").read_text(encoding="utf-8")


def test_header_stop_calls_the_kill_endpoint_and_does_not_invent_success():
    """The header stop must hit the real kill route and admit a failed request."""
    main_src = (JS_DIR / "main.js").read_text(encoding="utf-8")
    assert 'api.post("/api/demo/kill"' in main_src
    assert "Stop was not confirmed" in main_src
    assert "does not close an open position" in main_src
    assert "Request recorded" not in main_src


def test_live_trading_is_unmistakably_locked():
    """Live trading must remain structurally locked and calm."""
    gov_src = (JS_DIR / "views" / "governance.js").read_text(encoding="utf-8")
    assert "LIVE — " in gov_src
    assert "LOCKED" in gov_src
    assert "Live trading stays locked" in gov_src
    assert "This page cannot open it" in gov_src
    assert "demo results cannot open it" in gov_src


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
