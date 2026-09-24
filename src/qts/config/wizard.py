"""Setup Wizard persistence — machine-local, gitignored, credential-free.

Truthfulness rule: the wizard's "Save Setup" must actually save what it
claims to save. Previously it displayed ``saved:true`` while persisting
nothing. Only NON-secret connection metadata is persisted here: MT5
terminal path, requested symbol, and broker symbol map (e.g. XAUUSD ->
XAUUSD@). Credentials (login/password/server) NEVER pass through this
store even if supplied — they are rejected explicitly and belong in the OS
credential store or ``.env`` (``QTS_MT5_LOGIN`` / ``QTS_MT5_PASSWORD`` /
``QTS_MT5_SERVER``; the legacy unprefixed ``MT5_*`` names remain accepted
as fallbacks by the CLI).

File: ``data/setup/mt5_setup.json`` (gitignored, machine-local); override
with ``QTS_SETUP_FILE`` (used by tests and portable installs).

Precedence consumed by the readiness gate (see api/server.py):
explicit request param > saved wizard file > QTS_MT5_PATH/QTS_MT5_SYMBOL
env > MT5_PATH env > MT5 auto-detect. Fail-closed behavior of the gate is
untouched: this store only supplies connection metadata, never gate
decisions, env/mode selection, or safety limits.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Repository-relative default; resolved via :mod:`qts.config.paths`.
DEFAULT_SETUP_FILE = Path("data/setup/mt5_setup.json")

#: Modes an operator or setup wizard may declare in the machine-local setup file.
#: Real-capital modes are absent on purpose: LIVE stays locked behind its own gate
#: and can never be selected from a config file, the API or the UI.
DECLARABLE_MODES = ("development", "paper", "shadow", "demo_forward", "demo_execution")

# allowlist: fields this store persists (credential-free by design).
_ALLOWED_KEYS = ("terminal_path", "symbol", "symbol_map", "mode")
_WRITEABLE_KEYS = ("terminal_path", "symbol", "symbol_map", "mode")

# broker symbols: XAUUSD, XAUUSD@, XAUUSD.m, XAUUSDm, GOLD#... keep conservative
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._@#+-]{1,64}$")
_MAX_MAP_ENTRIES = 64
_MAX_PATH_LEN = 512


def setup_file() -> Path:
    """Location of the machine-local wizard setup file.

    ``QTS_SETUP_FILE`` wins verbatim; otherwise the repository-relative default
    is anchored at the ONE machine-local state root (:mod:`qts.config.paths`) —
    never at the calling process's working directory. A cwd-relative default
    meant a ``qts`` console script launched outside the repository silently
    read no setup at all (``load_setup`` → ``{}``), which is how a saved
    ``symbol_map`` came to be ignored by the CLI while the backend honoured it.
    """
    from qts.config.paths import artifact_path

    return artifact_path("setup")


def load_setup(path: Path | str | None = None) -> dict[str, Any]:
    """Load persisted wizard setup. Missing/corrupt file -> {} (fail-closed:
    the readiness gate then falls back to env/auto-detect, never to a
    fabricated connection)."""
    p = Path(path) if path is not None else setup_file()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for k in _ALLOWED_KEYS:
        if k in data:
            out[k] = data[k]
    return out


def _valid_symbol(value: object) -> bool:
    return isinstance(value, str) and bool(_SYMBOL_RE.match(value.strip()))


def save_setup(payload: dict[str, Any], path: Path | str | None = None) -> dict[str, Any]:
    """Validate and persist allowlisted fields only. Partial updates merge
    with what is already stored. Returns an auditable summary including any
    rejected fields (e.g. credentials someone tried to sneak in)."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    saved: dict[str, Any] = {}

    if payload.get("terminal_path") is not None:
        tp = payload["terminal_path"]
        if not isinstance(tp, str) or not tp.strip() or len(tp) > _MAX_PATH_LEN:
            raise ValueError(f"terminal_path must be a non-empty string (<= {_MAX_PATH_LEN} chars)")
        saved["terminal_path"] = tp.strip()

    if payload.get("symbol") is not None:
        sym = payload["symbol"]
        if not _valid_symbol(sym):
            raise ValueError("symbol must match [A-Za-z0-9._@#+-]{1,64}")
        saved["symbol"] = str(sym).strip()

    if payload.get("symbol_map") is not None:
        sm = payload["symbol_map"]
        if not isinstance(sm, dict) or len(sm) > _MAX_MAP_ENTRIES:
            raise ValueError(f"symbol_map must be an object (<= {_MAX_MAP_ENTRIES} entries)")
        clean: dict[str, str] = {}
        for k, v in sm.items():
            if not _valid_symbol(k) or not _valid_symbol(v):
                raise ValueError("symbol_map keys and values must be valid symbol names")
            clean[str(k).strip()] = str(v).strip()
        saved["symbol_map"] = clean

    if payload.get("mode") is not None:
        m = str(payload["mode"]).strip().lower()
        if m not in DECLARABLE_MODES:
            raise ValueError(
                f"mode {payload['mode']!r} cannot be declared; declarable modes: {list(DECLARABLE_MODES)} "
                "(LIVE is never declarable — LIVE stays locked)"
            )
        saved["mode"] = m
        saved["mode_declared_at"] = datetime.now(UTC).isoformat()

    rejected = sorted(k for k in payload if k not in _WRITEABLE_KEYS)

    p = Path(path) if path is not None else setup_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {**load_setup(p), **saved, "saved_at": datetime.now(UTC).isoformat()}
    p.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "saved": {k: body[k] for k in _WRITEABLE_KEYS if k in body},
        "stored_at": str(p),
        "rejected_fields": rejected,
        "mode_note": (
            "the mode declaration is read from this file but cannot be written through the API/UI — "
            "use `qts mode declare demo_execution` (LIVE can never be declared; it stays locked)"
            if "mode" in payload
            else None
        ),
        "credentials_note": (
            "login/password/server are NEVER stored here — use the OS credential "
            "store or .env (QTS_MT5_LOGIN / QTS_MT5_PASSWORD / QTS_MT5_SERVER)"
        ),
    }


def declare_mode(value: str, path: Path | str | None = None) -> dict[str, Any]:
    """Persist the process-mode declaration both the CLI and the backend read.

    This is the fix for "the UI says DEVELOPMENT while the CLI says
    DEMO_EXECUTION": ``QTS_MODE`` is per-process environment, so a backend
    launched outside the operator's shell never saw it. The declaration lives in
    the same machine-local file as the connection metadata, is read by
    :func:`qts.domain.modes.resolve_mode` below the environment in precedence,
    and is auditable — every mode resolution reports its provenance.

    Real-capital modes are refused outright.
    """
    requested = str(value or "").strip().lower()
    if requested not in DECLARABLE_MODES:
        raise ValueError(
            f"mode {value!r} cannot be declared here; declarable modes: {list(DECLARABLE_MODES)} "
            "(LIVE and its aliases are never declarable — LIVE stays locked)"
        )
    p = Path(path) if path is not None else setup_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {**load_setup(p), "mode": requested, "mode_declared_at": datetime.now(UTC).isoformat()}
    p.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "declared": requested,
        "stored_at": str(p),
        "precedence": "QTS_MODE / QTS_ENV (environment) override this declaration; LIVE is never declarable",
    }
