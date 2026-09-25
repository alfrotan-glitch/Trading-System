"""Pytest wrapper for the Node-based UI tests.

Runs, in order:
  1. `node --test tests/ui/js/format.test.mjs status.test.mjs` — DOM-free
     truthfulness logic (always, if node exists).
  2. `node --test tests/ui/js/shell.test.mjs` — full jsdom functional tour
     against a REAL uvicorn server (requires jsdom; best-effort install).

Skip logic: no node → skip all; no jsdom and npm install fails → skip shell
tests only (logic tests still run). This keeps the standard suite green on
machines without a Node toolchain while exercising the real UI everywhere
Node is available.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
JS_DIR = REPO / "tests" / "ui" / "js"
LOGIC = [JS_DIR / "format.test.mjs", JS_DIR / "status.test.mjs"]
SHELL = JS_DIR / "shell.test.mjs"

node = shutil.which("node")


def _run(cmd: list[str], *, timeout: int = 600, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout, **kw)


@pytest.mark.skipif(node is None, reason="node not installed")
def test_ui_truthfulness_logic():
    r = _run([node, "--test", *[str(p) for p in LOGIC]])
    assert r.returncode == 0, f"Node UI logic tests failed:\n{r.stdout}\n{r.stderr}"


def _jsdom_available() -> bool:
    r = _run([node, "-e", "import('jsdom').then(()=>console.log('ok')).catch(()=>process.exit(1))"])
    return r.returncode == 0


def _try_install_jsdom() -> bool:
    if not shutil.which("npm"):
        return False
    _run(["npm", "install", "--silent", "--no-fund", "--no-audit"], timeout=300)
    return _jsdom_available()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(node is None, reason="node not installed")
def test_ui_shell_functional_tour():
    if not _jsdom_available() and not _try_install_jsdom():
        pytest.skip("jsdom not available and could not be installed — UI shell tour skipped")
    port = _free_port()
    env = dict(os.environ)
    env["QTS_SETUP_FILE"] = str(Path(os.getenv("QTS_TEST_TMP", "/tmp")) / "ui-shell-setup.json")
    env["QTS_UI_BASE"] = f"http://127.0.0.1:{port}"
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

    try:
        base = env["QTS_UI_BASE"]
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.fail("API server for UI shell tests did not become healthy")
        r = _run([node, "--test", "--test-concurrency=1", str(SHELL)], env=env)
        assert r.returncode == 0, f"UI shell tour failed:\n{r.stdout[-4000:]}\n{r.stderr[-1000:]}"
    finally:
        proc.terminate()
