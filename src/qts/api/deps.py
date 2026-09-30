"""Shared API helpers. No FastAPI app and no route registration."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from qts.config.paths import artifact_path

DEFAULT_TRUSTED_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "testserver"})


def _is_trusted_origin(origin_or_url: str | None) -> bool:
    if not origin_or_url:
        return False
    val = origin_or_url.strip().lower()
    if val in ("null", "tauri://localhost", "vscode-webview://"):
        return True
    try:
        parsed = urlparse(val)
        host = (parsed.hostname or "").lower()
        if host in DEFAULT_TRUSTED_HOSTS:
            return True
        if host.endswith(".e2b.app"):  # Sandbox live preview proxy host
            return True
        extra = os.getenv("QTS_ALLOWED_ORIGINS", "")
        if extra:
            allowed = {x.strip().lower() for x in extra.split(",") if x.strip()}
            if val in allowed or host in allowed:
                return True
    except Exception:
        return False
    return False




def _env() -> str:
    import os

    return os.getenv("QTS_ENV", "development")




def _connection_adapter(symbol: str | None = None) -> tuple[Any, dict[str, Any]]:
    """The one MT5 connection for API probes (module-level = test injection seam).

    Every broker-facing API probe must use the SAME resolved connection — terminal
    path plus the canonical→venue alias table. Building adapters inline is how two
    endpoints came to ask the broker for ``XAUUSD`` while the DEMO session traded
    ``XAUUSD@``.
    """
    from qts.adapters.mt5_factory import adapter_from_setup

    return adapter_from_setup(symbol)




def _db_path() -> Path:
    """The DEMO state database — the SAME file the CLI reads.

    This used to be the relative literal ``data/sqlite/qts.db``, i.e. resolved
    against the backend process's working directory. The CLI resolves its own
    default the same way, so a backend launched from the repository root and a
    ``qts`` invocation from anywhere else read *different* stage, authority and
    journal state — one half of the reported "UI says DISABLED while CLI says
    AUTHORIZED" contradiction. Both now anchor at the machine-local state root
    (:mod:`qts.config.paths`), and the resolved location is published by
    ``/api/demo/state`` so agreement is checkable.
    """

    return artifact_path("db")




def _evidence_strategy_id(ev: dict[str, Any]) -> str | None:
    """Strategy identity recorded IN the evidence. Never inferred.

    A caller-supplied id, a URL path, or a matching instrument symbol is not
    attribution. An absent or blank ``strategy_id`` means the file does not
    name a strategy.
    """
    sid = ev.get("strategy_id") if isinstance(ev, dict) else None
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    return None




def _evidence_attribution(ev: dict[str, Any], requested: str) -> dict[str, Any]:
    """Whether ``ev`` is validation of ``requested``, and why not if it isn't."""
    found = _evidence_strategy_id(ev)
    if found is None:
        return {
            "attributed": False,
            "requested_strategy_id": requested,
            "evidence_strategy_id": None,
            "reason": (
                "evidence file does not record a strategy_id; it cannot be treated as "
                "validation of the requested strategy"
            ),
        }
    if found != requested:
        return {
            "attributed": False,
            "requested_strategy_id": requested,
            "evidence_strategy_id": found,
            "reason": f"evidence strategy_id={found!r} does not match requested {requested!r}",
        }
    return {
        "attributed": True,
        "requested_strategy_id": requested,
        "evidence_strategy_id": found,
        "reason": "evidence strategy_id matches the request",
    }




def _reconciliation_status() -> tuple[bool, str, str]:
    """(healthy, status, detail) from the DURABLE reconcile-suspension row.

    ``status`` is one of ``Healthy`` | ``Drift Detected`` | ``UNAVAILABLE``.
    A probe that cannot be completed is never reported as Healthy: an
    unmeasurable reconciliation state is not a clean one.

    ONLY a missing ``reconcile_state`` table is benign — it honestly means no
    ExecutionEngine has ever persisted suspension state. A locked, damaged or
    otherwise unreadable store is ``UNAVAILABLE`` and not healthy, matching
    ``ExecutionEngine._load_reconcile_suspend`` and
    ``live_gate.check_reconciliation_health`` so all three readers of the same
    durable row cannot disagree.

    Shared by ``/api/health`` and ``/api/risk`` so both endpoints report the
    same fact and ``/api/risk`` no longer has to invoke the whole health
    report (which re-runs the full live-readiness gate) to read one row.
    """
    from qts.db import connect as db_connect

    try:
        dbp = _db_path()
        if not dbp.exists():
            return True, "Healthy", "no reconcile state"
        with db_connect(dbp) as con:
            try:
                row = con.execute("SELECT suspended FROM reconcile_state WHERE k=1").fetchone()
            except sqlite3.OperationalError as e:
                # ONLY a missing table is benign (nothing was ever persisted).
                # A locked or damaged store is unreadable, and "could not read
                # the suspension flag" must never be reported as "Healthy".
                if "no such table" in str(e).lower():
                    return True, "Healthy", f"no reconcile state recorded ({e})"
                return (
                    False,
                    "UNAVAILABLE",
                    f"reconciliation suspension state unreadable — fail closed ({type(e).__name__}: {e})",
                )
        if row and row[0]:
            return (
                False,
                "Drift Detected",
                "unresolved reconciliation SUSPENDED — broker/local state diverged",
            )
        if row is None:
            return True, "Healthy", "no reconcile state"
        return True, "Healthy", "no unresolved reconciliation suspension"
    except Exception as e:
        return False, "UNAVAILABLE", f"reconciliation health probe failed: {e}"




def _env_mode() -> str:
    import os

    mode = os.getenv("QTS_MODE", "Research")
    # map env to mode
    env = _env()
    mapping = {
        "development": "Research",
        "paper": "Paper",
        "shadow": "Shadow",
        "dry_run": "Dry Run",
        "micro": "Micro",
        "live": "Live",
    }
    return mapping.get(env, mode)




def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "UNAVAILABLE", "value": None, "reason": reason}




def _wizard_setup_kwargs(terminal_path: str | None, symbol: str | None) -> dict[str, Any]:
    """Merge wizard inputs with the persisted (saved) setup.

    Precedence: explicit request param > saved wizard file > (inside the
    gate) QTS_MT5_PATH/QTS_MT5_SYMBOL env > MT5_PATH > auto-detect.
    The same resolution is used by readiness AND demo-enablement so the two
    can never evaluate different connections.
    """
    from qts.adapters.mt5_adapter import normalize_terminal_path
    from qts.config.wizard import load_setup

    saved = load_setup()
    sm = saved.get("symbol_map")
    resolved_path = terminal_path or saved.get("terminal_path") or None
    return {
        "terminal_path": normalize_terminal_path(resolved_path),
        "symbol": symbol or saved.get("symbol") or None,
        "symbol_map": sm if isinstance(sm, dict) else None,
    }




def _resolve_observe_symbol(setup_kwargs: dict[str, Any]) -> tuple[str, str]:
    """(canonical, broker) symbol from saved wizard config/env (XAUUSD -> XAUUSD@).

    Returns the CANONICAL name first, whichever spelling the operator saved: an
    observer configured with the venue alias used to return ``XAUUSD@`` as the
    "requested" symbol, from which an empty alias table was then derived — so
    observation recorded a venue spelling as if it were canonical.
    """
    import os

    from qts.adapters.mt5_adapter import broker_symbol as _broker_of
    from qts.adapters.mt5_adapter import canonical_symbol as _canonical_of

    requested = setup_kwargs.get("symbol") or os.getenv("QTS_MT5_SYMBOL", "XAUUSD")
    raw_map = setup_kwargs.get("symbol_map")
    symbol_map = {str(k): str(v) for k, v in raw_map.items()} if isinstance(raw_map, dict) else {}
    canonical = _canonical_of(str(requested), symbol_map)
    return canonical, _broker_of(canonical, symbol_map)




def _demo_policy() -> Any:
    """The resolved DEMO execution policy for this API process.

    Resolved from the recorded owner authorization artifact
    (``qts.lifecycle.demo_authorization``). Without a valid artifact this
    returns ``DEMO_EXECUTION = DISABLED BY POLICY``, which is the shipped
    default; the artifact itself can never permit LIVE.
    """
    from qts.domain.modes import resolve_mode
    from qts.lifecycle.demo_authorization import resolve_demo_execution_policy

    return resolve_demo_execution_policy(mode=resolve_mode().value)



