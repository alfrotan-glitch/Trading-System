"""QTS desktop API composition layer.

Routes live in ``qts.api.routes``. This module owns the FastAPI app, the
origin boundary, and the process-local seams tests patch
(``_demo_session``, ``_build_observe_collector``, ``_OBSERVE_STATE``,
``_DEMO_AUTHORITY``).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from qts.api.deps import (
    _connection_adapter,
    _db_path,
    _demo_policy,
    _env_mode,
    _is_trusted_origin,
    _reconciliation_status,
    _resolve_observe_symbol,
    _wizard_setup_kwargs,
)
from qts.api.routes.demo import router as demo_router
from qts.api.routes.market import observe_start, observe_status, observe_stop
from qts.api.routes.market import router as market_router
from qts.api.routes.research import router as research_router
from qts.api.routes.risk import router as risk_router
from qts.api.routes.system import router as system_router
from qts.api.routes.trading import router as trading_router

app = FastAPI(title="QTS Desktop API", version="0.1.0")


@app.middleware("http")
async def local_operator_boundary_middleware(request: Request, call_next):
    """Reject state-changing requests from untrusted browser origins."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        if origin and not _is_trusted_origin(origin):
            return JSONResponse(
                status_code=403,
                content={
                    "error": "FORBIDDEN_MUTATION",
                    "detail": (
                        f"Cross-origin state mutation rejected from untrusted origin {origin!r}. "
                        "Only local operator origins and verified proxies are permitted."
                    ),
                },
            )
        if referer and not _is_trusted_origin(referer):
            return JSONResponse(
                status_code=403,
                content={
                    "error": "FORBIDDEN_MUTATION",
                    "detail": f"Cross-origin state mutation rejected from untrusted referer {referer!r}.",
                },
            )
    response = await call_next(request)
    if request.method == "GET" and not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


_use_wildcard_cors = os.getenv("QTS_CORS_WILDCARD") == "1"
if _use_wildcard_cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-QTS-Operator"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$|^https://.*\.e2b\.app$|^tauri://localhost$|^vscode-webview://.*$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-QTS-Operator"],
    )

# Process-local seams. Tests patch these names on this module; route handlers
# resolve them at call time through ``_bind()``.
_OBSERVE_LOCK = threading.Lock()
_OBSERVE_STATE: dict[str, Any] = {"collector": None}
_DEMO_AUTHORITY: Any = None
_DEMO_AUTHORITY_LOCK = threading.Lock()

def _build_observe_collector(terminal_path: str | None, requested: str, broker: str, interval_s: float) -> Any:
    """Real collector wiring. Module-level factory = test injection seam."""
    from qts.adapters.market_data import MarketDataProvider
    from qts.adapters.mt5_adapter import MT5Adapter
    from qts.domain.value_objects import Instrument
    from qts.observability.demo_collector import ObservationCollector
    from qts.observability.forward_observatory import ForwardObservatory

    symbol_map = {requested: broker} if broker != requested else {}
    adapter = MT5Adapter(
        config={"path": terminal_path or "", "symbol_map": symbol_map, "symbol": requested}
    )
    provider = MarketDataProvider(broker=adapter)
    observatory = ForwardObservatory()
    return ObservationCollector(
        provider=provider,
        observatory=observatory,
        instrument=Instrument(symbol=requested, venue="MT5"),
        broker_symbol=broker,
        interval_s=interval_s,
    )




def _demo_session(symbol: str | None = None) -> Any:
    """One wired DEMO session for API calls (same safeguards as the CLI)."""
    from qts.execution.demo_session import DemoSession, DemoSessionConfig
    from qts.lifecycle.demo_registry import load_registry, resolve_entry

    setup = _wizard_setup_kwargs(None, None)
    session = DemoSession(
        DemoSessionConfig(
            symbol=symbol or setup.get("symbol") or "XAUUSD",
            terminal_path=setup.get("terminal_path"),
            symbol_map=setup.get("symbol_map") or {},
            db_path=_db_path(),
            actor="api",
        )
    )
    registry = load_registry()
    entry, _reasons = resolve_entry(registry)
    session._entry = entry  # type: ignore[attr-defined]
    return session




def _demo_authority() -> Any:
    """The ONE demo-execution permission authority for this API process.

    Audited through the standard domain-event log; the mode passed to the
    authority is the canonical resolved mode, so a DEMO_FORWARD (observe-only)
    process can never hold demo-execution permission.
    """
    global _DEMO_AUTHORITY
    with _DEMO_AUTHORITY_LOCK:
        if _DEMO_AUTHORITY is None:
            from qts.domain.modes import resolve_mode
            from qts.lifecycle.demo_authority import DemoExecutionAuthority
            from qts.observability.audit import SqliteAuditLog

            try:
                audit: Any = SqliteAuditLog()
            except Exception:
                audit = None
            _DEMO_AUTHORITY = DemoExecutionAuthority(
                db_path=_db_path(),
                audit=audit,
                # Binding the authority to the canonical resolved mode keeps a
                # DEMO_FORWARD (observe-only) process unable to hold execution
                # permission. When no owner authorization is recorded the API
                # stays observation-only, exactly as the product shipped.
                mode=resolve_mode().value if _demo_policy().enabled else "DEMO_FORWARD",
            )
        return _DEMO_AUTHORITY





app.include_router(system_router)
app.include_router(research_router)
app.include_router(trading_router)
app.include_router(risk_router)
app.include_router(market_router)
app.include_router(demo_router)

__all__ = [
    "app",
    "_connection_adapter",
    "_db_path",
    "_env_mode",
    "_reconciliation_status",
    "_resolve_observe_symbol",
    "_demo_session",
    "_demo_authority",
    "_build_observe_collector",
    "_OBSERVE_LOCK",
    "_OBSERVE_STATE",
    "_DEMO_AUTHORITY",
    "observe_start",
    "observe_status",
    "observe_stop",
]

_ui_dir = Path(__file__).parent.parent / "desktop" / "ui"
if _ui_dir.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dir), html=True), name="ui")
