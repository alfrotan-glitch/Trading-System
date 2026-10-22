"""Desktop launcher — one-click operation, native window, reliable local backend."""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
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

    from qts.api.server import app, ensure_qts_api_routes

    ensure_qts_api_routes()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio",
        server_header=False,
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)
    # run in thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # wait for health
    import urllib.request

    url = f"http://{host}:{port}/api/health"
    for _ in range(30):
        try:
            # B310: health probe of local API, URL built from local host/port config
            with urllib.request.urlopen(url, timeout=1) as resp:  # nosec B310
                if resp.status == 200:
                    print(f"[launcher] API healthy at {url}")
                    return server, thread
        except Exception:
            time.sleep(0.5)
    print("[launcher] API not healthy after 15s, continuing anyway")
    return server, thread


def open_desktop_window(host: str, port: int):
    # A fresh query stops a native window from reopening a cached page.
    url = f"http://{host}:{port}/?desk=1"
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


def _emit(message: str) -> None:
    """Write to stdout when one exists.

    A windowed PyInstaller build can have ``sys.stdout is None``; a bare print()
    then raises and turns ``--version`` into a non-zero exit.
    """
    if getattr(sys, "stdout", None) is None:
        return
    try:
        print(message)
    except Exception:
        return


def _smoke_packaged_application() -> None:
    """Read-only packaged-executable check; never opens UI or sends orders.

    This is stronger than --version: it proves that the frozen API routes and
    UI files survived packaging and can import within the executable. It never
    binds a public port, probes a broker, changes permissions or trades.
    """
    from qts.api.server import app, ensure_qts_api_routes

    ensure_qts_api_routes()
    required_routes = {"/api/health/live", "/api/version", "/api/demo/guide"}
    available_routes = {getattr(route, "path", "") for route in app.routes}
    missing = sorted(required_routes - available_routes)
    if missing:
        # Distinguish an incomplete API import from routers that were loaded
        # but had their declarations stripped (e.g. packaging/circular import).
        from qts.api.routes.demo import router as demo_router
        from qts.api.routes.system import router as system_router

        raise RuntimeError(
            f"Packaged backend missing routes: {missing}; "
            f"registered={len(available_routes)} paths={sorted(available_routes)[:18]}; "
            f"system_router={len(system_router.routes)} demo_router={len(demo_router.routes)}"
        )
    ui_path = _get_ui_dir() / "index.html"
    if not ui_path.is_file() or ui_path.stat().st_size < 100:
        raise RuntimeError(f"Packaged desktop UI not accessible: {ui_path}")
    _emit("QTS packaged import, API routes and desktop UI: OK")


def _handle_cli(argv: list[str] | None = None) -> bool:
    """Answer ``--version``/``--help`` without starting a server or a window.

    A packaged (windowed) executable has no console, but the exit code still
    proves the frozen import graph and bootstrap succeeded — which is exactly
    what the release workflow smoke-tests.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--smoke" in args:
        try:
            _smoke_packaged_application()
        except Exception as exc:
            msg = f"QTS packaged smoke FAILED: {type(exc).__name__}: {exc}"
            _emit(msg)
            # Windowed PyInstaller has no stdout. The CI smoke probe supplies a
            # path for a short, non-secret diagnostic rather than concealing the
            # actual bootstrap failure. This is only a read-only self-test path;
            # never include account, environment, or machine identity here.
            diagnostic = (os.getenv("QTS_SMOKE_RESULT_PATH") or "").strip()
            if diagnostic:
                with contextlib.suppress(OSError):
                    Path(diagnostic).write_text(msg, encoding="utf-8")
            raise SystemExit(1) from exc
        return True
    if "--version" in args or "-V" in args:
        from qts import __version__

        _emit(f"QTS {__version__}")
        return True
    if "--help" in args or "-h" in args:
        _emit(
            "QTS — gold research workstation\n\n"
            "Usage: QTS [--version] [--help]\n\n"
            "Without arguments QTS runs startup health, serves the local API on\n"
            "127.0.0.1:8000 and opens the workstation window.\n"
            "Live trading is locked; real-capital exposure is 0."
        )
        return True
    return False


def main():
    if _handle_cli():
        return
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
