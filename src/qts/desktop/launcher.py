"""Desktop launcher — one-click operation, native window, reliable local backend."""

from __future__ import annotations

import os
import sys
import time
import threading
import webbrowser
from pathlib import Path


def _get_ui_dir() -> Path:
    return Path(__file__).parent / "ui"


def _get_api_host_port() -> tuple[str, int]:
    host = os.getenv("QTS_API_HOST", "127.0.0.1")
    port = int(os.getenv("QTS_API_PORT", "8000"))
    return host, port


def start_api_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    from qts.api.server import app

    config = uvicorn.Config(app, host=host, port=port, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    # run in thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # wait for health
    import urllib.request
    import json

    url = f"http://{host}:{port}/api/health"
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    print(f"[launcher] API healthy at {url}")
                    return server, thread
        except Exception:
            time.sleep(0.5)
    print(f"[launcher] API not healthy after 15s, continuing anyway")
    return server, thread


def open_desktop_window(host: str, port: int):
    url = f"http://{host}:{port}/"
    # Prefer pywebview native window
    try:
        import webview  # type: ignore

        print("[launcher] launching native webview")
        # webview must run on main thread; we already started server in background
        webview.create_window("QTS Trading System", url, width=1280, height=800, resizable=True)
        # start webview loop (blocking)
        webview.start()
        return
    except ImportError:
        print("[launcher] pywebview not installed — falling back to browser")
    except Exception as e:
        print(f"[launcher] webview failed {e} — falling back to browser")
    # Fallback: open browser
    print(f"[launcher] opening browser at {url}")
    webbrowser.open(url)
    # Keep main thread alive while server thread runs
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[launcher] shutting down")
        from qts.desktop.health import shutdown_procedure

        shutdown_procedure()


def main():
    print("[launcher] QTS Desktop starting — startup health check")
    from qts.desktop.health import startup_health_check

    health = startup_health_check()
    print(f"[launcher] health overall={health['overall']} status={health['system_status']}")
    for c in health["checks"]:
        print(f"  {c['name']}: {'PASS' if c['passed'] else 'FAIL'} {c['detail']}")
    if not health["overall"]:
        print("[launcher] BLOCKED — dashboard will show reasons, not auto-trading")

    host, port = _get_api_host_port()
    server, thread = start_api_server(host, port)
    # give server a moment
    time.sleep(1)
    open_desktop_window(host, port)


if __name__ == "__main__":
    main()
