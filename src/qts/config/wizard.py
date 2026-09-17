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
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_SETUP_FILE = Path("data/setup/mt5_setup.json")

# allowlist: the ONLY fields this store persists (credential-free by design)
_ALLOWED_KEYS = ("terminal_path", "symbol", "symbol_map")

# broker symbols: XAUUSD, XAUUSD@, XAUUSD.m, XAUUSDm, GOLD#... keep conservative
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._@#+-]{1,64}$")
_MAX_MAP_ENTRIES = 64
_MAX_PATH_LEN = 512


def setup_file() -> Path:
    """Location of the machine-local wizard setup file."""
    return Path(os.getenv("QTS_SETUP_FILE") or DEFAULT_SETUP_FILE)


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

    rejected = sorted(k for k in payload if k not in _ALLOWED_KEYS)

    p = Path(path) if path is not None else setup_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {**load_setup(p), **saved, "saved_at": datetime.now(UTC).isoformat()}
    p.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "saved": {k: body[k] for k in _ALLOWED_KEYS if k in body},
        "stored_at": str(p),
        "rejected_fields": rejected,
        "credentials_note": (
            "login/password/server are NEVER stored here — use the OS credential "
            "store or .env (QTS_MT5_LOGIN / QTS_MT5_PASSWORD / QTS_MT5_SERVER)"
        ),
    }
