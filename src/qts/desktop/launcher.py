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
    """Find UI assets in either an editable checkout or a frozen Windows EXE.

    In a PyInstaller executable the launcher is the ENTRY SCRIPT, not an
    imported qts.desktop module. Its __file__ resolves directly under
    sys._MEIPASS, while packaged assets live under qts/desktop/ui.
    """
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        return bundle_root / "qts" / "desktop" / "ui"
    return Path(__file__).parent / "ui"


def _get_api_host_port() -> tuple[str, int]:
    host = os.getenv("QTS_API_HOST", "127.0.0.1")
    port = int(os.getenv("QTS_API_PORT", "8000"))
    return host, port


def start_api_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn

    from qts.api.server import app

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        # A PyInstaller console=False build has sys.stdout/stderr=None.
        # Uvicorn's default logging formatter inspects isatty() on those
        # streams and fails before binding HTTP. Disable that default
        # configuration for the desktop launcher (not the server itself).
        log_config=None,
        access_log=False,
        loop="asyncio",
        server_header=False,
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)
    # run in thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # A 200 from the lightweight health endpoint AND this Uvicorn instance
    # reporting started are required. A different QTS process on the port must
    # never be mistaken for the server started by this invocation.
    import json
    import urllib.request

    url = f"http://{host}:{port}/api/health/live"
    for _ in range(30):
        if not thread.is_alive():
            break
        try:
            # Local probe only; safe on a machine with no broker/MT5 installed.
            with urllib.request.urlopen(url, timeout=1) as resp:  # nosec B310
                if resp.status != 200:
                    continue
                body = json.loads(resp.read(4096).decode("utf-8"))
            if server.started and body.get("status") == "ok" and body.get("live_trading") == "LOCKED":
                _emit(f"[launcher] QTS local API healthy at {url}")
                return server, thread
        except (OSError, ValueError):
            pass
        time.sleep(0.5)

    server.should_exit = True
    thread.join(timeout=2)
    raise RuntimeError(
        f"QTS local API did not start correctly on {host}:{port}. "
        "Another process may already be using the port, or a runtime dependency is missing. "
        "The desktop window was not opened against an unverified backend."
    )


def open_desktop_window(host: str, port: int):
    # A fresh query stops a native window from reopening a cached page.
    url = f"http://{host}:{port}/?desk=1"
    # Prefer pywebview native window
    try:
        import webview  # type: ignore

        _emit("[launcher] launching native webview")
        # webview must run on main thread; we already started server in background
        webview.create_window("QTS Trading System", url, width=1280, height=800, resizable=True)
        # start webview loop (blocking)
        webview.start()
        return
    except ImportError:
        _emit("[launcher] pywebview not installed — falling back to browser")
    except Exception as e:
        _emit(f"[launcher] webview failed {e} — falling back to browser")
    # Fallback: open browser
    _emit(f"[launcher] opening browser at {url}")
    webbrowser.open(url)
    # Keep main thread alive while server thread runs
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _emit("[launcher] shutting down")
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
    from qts.api.server import app

    # FastAPI >=0.137 stores included routers as lazy internal
    # _IncludedRouter objects without a .path attribute. `app.routes` is
    # intentionally NOT a flattened list of HTTP endpoints. The generated
    # OpenAPI schema is the supported, recursively-resolved route inventory.
    required_routes = {"/api/health/live", "/api/version", "/api/demo/guide"}
    schema = app.openapi()
    available_routes = set(schema.get("paths", {}))
    missing = sorted(required_routes - available_routes)
    if missing:
        raise RuntimeError(
            f"Packaged backend missing API endpoints: {missing}; "
            f"schema_paths={len(available_routes)}"
        )
    ui_path = _get_ui_dir() / "index.html"
    if not ui_path.is_file() or ui_path.stat().st_size < 100:
        raise RuntimeError(f"Packaged desktop UI not accessible: {ui_path}")
    _emit("QTS packaged import, API routes and desktop UI: OK")



def _smoke_http_server() -> None:
    """Run genuine loopback HTTP/API/UI probes, without touching a trading terminal."""
    import socket
    import urllib.request

    # The OS selects a local ephemeral port. No public listener, account
    # connection, order, or broker-dependent endpoint is involved.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    server, thread = start_api_server("127.0.0.1", port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:  # nosec B310
            data = resp.read(1_000_000).lower()
            if resp.status != 200 or b"</html>" not in data:
                raise RuntimeError("QTS home page did not return valid HTML")
        _emit("QTS local API and bundled desktop page HTTP smoke: OK")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("QTS local API did not stop after HTTP smoke")


def _handle_cli(argv: list[str] | None = None) -> bool:
    """Answer ``--version``/``--help`` without starting a server or a window.

    A packaged (windowed) executable has no console, but the exit code still
    proves the frozen import graph and bootstrap succeeded — which is exactly
    what the release workflow smoke-tests.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--smoke" in args or "--smoke-server" in args:
        try:
            _smoke_packaged_application()
            if "--smoke-server" in args:
                _smoke_http_server()
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
            "Usage: QTS [--version] [--help] [--smoke] [--smoke-server]\n\n"
            "Without arguments QTS runs startup health, serves the local API on\n"
            "127.0.0.1:8000 and opens the workstation window.\n"
            "Live trading is locked; real-capital exposure is 0."
        )
        return True
    return False


def main():
    if _handle_cli():
        return
    _emit("[launcher] QTS Desktop starting — startup health check")
    from qts.desktop.health import startup_health_check

    health = startup_health_check()
    _emit(f"[launcher] health overall={health['overall']} status={health['system_status']}")
    for c in health["checks"]:
        _emit(f"  {c['name']}: {'PASS' if c['passed'] else 'FAIL'} {c['detail']}")
    if not health["overall"]:
        _emit("[launcher] BLOCKED — dashboard will show reasons, not auto-trading")

    host, port = _get_api_host_port()
    server, thread = start_api_server(host, port)
    # give server a moment
    time.sleep(1)
    open_desktop_window(host, port)


if __name__ == "__main__":
    main()
