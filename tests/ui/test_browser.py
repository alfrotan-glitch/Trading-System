"""Browser-level UX tests (Playwright/Chromium).

Mission §40–41: navigation, readiness display, DEMO permission display,
blocked states, mode display, stale/error states — plus pragmatic visual
regression: full screenshots of the 9 key screens captured to
artifacts/ui_screens/ for diff/review.

Skip-guarded: requires `playwright` + a Chromium install
(`pip install playwright && playwright install chromium`).
Starts a real uvicorn server on a free port with isolated setup state.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UI_SCREENSHOTS = REPO / "artifacts" / "ui_screens"

pw = pytest.importorskip("playwright.sync_api", reason="playwright not installed")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = dict(os.environ)
    env["QTS_SETUP_FILE"] = str(Path(os.getenv("QTS_TEST_TMP", "/tmp")) / "browser-test-setup.json")
    env["QTS_API_PORT"] = str(port)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "qts.api.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import urllib.request

    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail("API server did not become healthy for browser tests")
    yield base
    proc.terminate()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=os.getenv("QTS_CHROMIUM_PATH") or None, args=["--no-sandbox"])
        except Exception as e:  # chromium not installed
            pytest.skip(f"Chromium not available: {e}")
        yield b
        b.close()


@pytest.fixture()
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.errors = errors  # type: ignore[attr-defined]
    pg.goto(server + "/#/overview")
    pg.wait_for_selector("[data-fact=broker]", timeout=20_000)
    yield pg
    ctx.close()


SCREENS = [
    ("overview", "#/overview"),
    ("research_campaigns", "#/research/campaigns"),
    ("research_validation", "#/research/validation"),
    ("market_monitor", "#/market/monitor"),
    ("market_observations", "#/market/observations"),
    ("trading_demo", "#/trading/demo"),
    ("trading_execution", "#/trading/execution"),
    ("risk", "#/risk"),
    ("evidence_audit", "#/evidence/audit"),
    ("system_setup", "#/system/setup"),
    ("governance_live", "#/governance/live"),
]


def test_navigation_and_screens(page):
    """Every primary route renders real content — no blank views, no JS errors."""
    UI_SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    for name, route in SCREENS:
        page.goto(route)
        page.wait_for_timeout(1200)
        assert page.locator(".page-title").count() >= 1, f"{route} rendered no page title"
        assert page.locator("#main").inner_text().strip(), f"{route} rendered empty content"
        page.screenshot(path=str(UI_SCREENSHOTS / f"{name}.png"), full_page=False)
    assert not page.errors, f"page errors: {page.errors}"


def test_mode_display_matches_backend_truth(page, server):
    """Header mode chip mirrors /api/health effective_mode exactly (§40)."""
    import json
    import urllib.request

    with urllib.request.urlopen(server + "/api/health") as r:
        mode = json.load(r)["effective_mode"]["effective_mode"]
    page.wait_for_selector(".fact.mode", timeout=10_000)
    shown = page.locator(".fact.mode b").inner_text().strip()
    assert shown.upper() == mode.upper(), f"header shows {shown}, backend says {mode}"


def test_live_locked_always_visible(page):
    page.wait_for_selector(".fact.live-locked", timeout=10_000)
    page.wait_for_function("document.querySelector('.fact.live-locked').textContent.includes('LIVE LOCKED')")
    assert "LIVE LOCKED" in page.locator(".fact.live-locked").inner_text()


def test_demo_permission_display_is_authoritative(page):
    """DEMO state banner mirrors /api/demo/state (§34: no false permission)."""
    import json
    import urllib.request

    with urllib.request.urlopen(server + "/api/demo/state") as r:
        state = json.load(r)["state"]
    page.goto("#/trading/demo")
    page.wait_for_selector(".banner", timeout=20_000)
    page.wait_for_timeout(2500)
    body = page.locator("#main").inner_text()
    assert f"DEMO EXECUTION: {state.upper()}" in body, f"authority state {state} not displayed verbatim"


def test_blocked_risk_state_display(page):
    page.goto("#/risk")
    page.wait_for_selector(".banner", timeout=20_000)
    page.wait_for_timeout(1500)
    body = page.locator("#main").inner_text()
    assert "TRADING IS" in body
    assert ("BLOCKED" in body) or ("PERMITTED" in body)


def test_governance_locked_calm_ui(page):
    page.goto("#/governance/live")
    page.wait_for_timeout(2500)
    body = page.locator("#main").inner_text()
    assert "LIVE — LOCKED" in body
    btn = page.locator("button", has_text="enablement").first
    assert btn.is_disabled(), "enablement must be disabled while the gate is locked"


def test_readiness_checks_rendered_as_checklist(page):
    page.goto("#/trading/demo")
    page.wait_for_selector(".check", timeout=40_000)
    assert page.locator(".check").count() >= 10, "the 14 readiness checks render as a checklist"
    assert page.locator(".check.fail, .check.pass").count() >= 1


def test_stale_indicator_when_api_down(browser, server):
    """When the API dies, the header says so — never silent staleness (§31)."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.goto(server + "/#/overview")
    pg.wait_for_selector("[data-fact=broker]", timeout=20_000)
    # block all API calls and explicitly refresh: source failure must be visible
    pg.route("**/api/*", lambda route: route.abort())
    pg.wait_for_selector(".operator-workspace button:not([disabled])")
    pg.get_by_role("button", name="Refresh sources").click()
    pg.wait_for_function("document.querySelector('#header-updated').textContent.includes('RETRYING')")
    dot_class = pg.locator(".conn-dot").get_attribute("class")
    assert "stale" in dot_class, f"connection indicator should show down, got {dot_class}"
    assert "RETRYING" in pg.locator("#header-updated").inner_text()
    ctx.close()


def test_keyboard_palette_opens_and_navigates(page):
    page.keyboard.press("Control+k")
    page.wait_for_selector(".palette-input", timeout=5_000)
    page.keyboard.type("governance")
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)
    assert "Live Trading Governance" in page.locator("#main").inner_text()


def test_responsive_narrow_window(page):
    """No horizontal overflow disasters at laptop width (§33)."""
    page.set_viewport_size({"width": 900, "height": 800})
    page.wait_for_timeout(600)
    assert page.locator(".nav-toggle").is_visible(), "collapsed nav toggle appears at narrow width"
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 2, f"horizontal overflow of {overflow}px at 900px width"
