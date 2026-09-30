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
    pg.goto(server + "/#/home")
    pg.wait_for_selector(".home-hero .hero-headline", timeout=30_000)
    yield pg
    ctx.close()


SCREENS = [
    ("home", "#/home"),
    ("market", "#/market"),
    ("trading", "#/trading"),
    ("reports", "#/reports"),
    ("advanced_research", "#/advanced/research-campaigns"),
    ("advanced_observations", "#/advanced/data-observations"),
    ("advanced_trading_history", "#/advanced/trading-history"),
    ("advanced_risk", "#/advanced/risk"),
    ("advanced_audit", "#/advanced/audit"),
    ("advanced_system_setup", "#/advanced/system-setup"),
    ("advanced_governance", "#/advanced/governance"),
]


def test_navigation_and_screens(page):
    """Every primary route renders real content — no blank views, no JS errors."""
    UI_SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    for name, route in SCREENS:
        page.goto(route)
        page.wait_for_timeout(1200)
        # Product pages use the standard page head; Home uses its hero headline.
        has_title = page.locator(".page-title").count() >= 1 or page.locator(".home-hero .hero-headline").count() >= 1
        assert has_title, f"{route} rendered no page title"
        assert page.locator("#main").inner_text().strip(), f"{route} rendered empty content"
        page.screenshot(path=str(UI_SCREENSHOTS / f"{name}.png"), full_page=False)
    assert not page.errors, f"page errors: {page.errors}"


def test_header_account_state_matches_backend_truth(page, server):
    """The header account chip mirrors /api/health mt5 state exactly (§40)."""
    import json
    import urllib.request

    with urllib.request.urlopen(server + "/api/health") as r:
        mt5 = str(json.load(r).get("mt5", "")).lower()
    page.wait_for_selector("#header-account", timeout=10_000)
    shown = page.locator("#header-account").inner_text()
    expected = "Demo account: Connected" if mt5 == "connected" else "Demo account: Not connected"
    assert expected in shown, f"header shows {shown!r}, backend mt5 says {mt5!r}"


def test_live_locked_always_visible(page):
    """Live lock stays visible in the product shell — quietly, but always."""
    page.wait_for_selector(".header-lock", timeout=10_000)
    assert "Live locked" in page.locator(".header-lock").inner_text()


def test_demo_permission_display_is_authoritative(page, server):
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
    banner = page.locator(".banner").first.inner_text()
    assert "TRADING IS" in banner
    assert ("BLOCKED" in banner) or ("NOT AUTHORIZED" in banner)
    assert "PERMITTED" not in banner
    assert "22 GATES" not in body


def test_governance_locked_calm_ui(page):
    page.goto("#/governance/live")
    page.wait_for_timeout(2500)
    body = page.locator("#main").inner_text()
    assert "LIVE — LOCKED" in body
    btn = page.locator("button", has_text="cannot be opened").first
    assert btn.is_disabled(), "live control must be disabled while the gate is locked"


def test_readiness_checks_rendered_as_checklist(page):
    page.goto("#/trading/demo")
    page.wait_for_selector(".check", timeout=40_000)
    assert page.locator(".check").count() >= 10, "the 14 readiness checks render as a checklist"
    assert page.locator(".check.fail, .check.pass").count() >= 1


def test_stale_indicator_when_api_down(browser, server):
    """When the API dies, the header says so — never silent staleness (§31)."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.goto(server + "/#/home")
    pg.wait_for_selector(".home-hero .hero-headline", timeout=30_000)
    # block all API calls: source failure must become visible, never silent
    pg.route("**/api/*", lambda route: route.abort())
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
    assert "Live trading stays locked" in page.locator("#main").inner_text()


def test_responsive_narrow_window(page):
    """No horizontal overflow disasters at laptop width (§33)."""
    page.set_viewport_size({"width": 900, "height": 800})
    page.wait_for_timeout(600)
    assert page.locator(".nav-toggle").is_visible(), "collapsed nav toggle appears at narrow width"
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 2, f"horizontal overflow of {overflow}px at 900px width"
