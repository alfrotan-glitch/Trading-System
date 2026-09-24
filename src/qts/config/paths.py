"""One authoritative location for machine-local QTS state.

Every durable, machine-local artefact QTS reads — the setup wizard file, the
broker identity pin, the owner authorization, the forward-validation registry,
the DEMO journal/stage databases — used to default to a **relative** path
(``data/setup/mt5_setup.json``, ``data/sqlite/qts.db``, …). A relative default
is resolved against the *current working directory of whichever process asks*,
so:

* the desktop backend (launched from the repository root) read the operator's
  real setup, while
* a ``qts`` console script invoked from any other directory read **nothing at
  all** — silently, because a missing file loads as ``{}``.

That single flaw produced two of the reported symptoms: ``symbol_map`` saved in
``data/setup/mt5_setup.json`` but ignored by the CLI (so ``XAUUSD`` was sent to
the broker unmapped), and the UI and CLI disagreeing about mode, authority and
symbol state because they were not reading the same files.

This module removes the ambiguity. Resolution order for every artefact:

1. its own environment override (``QTS_SETUP_FILE``, ``QTS_DEMO_IDENTITY_PIN``,
   ``QTS_DEMO_AUTHORIZATION``, ``QTS_DEMO_REGISTRY``, ``QTS_DB_PATH``) — used
   verbatim, so tests and portable installs keep working;
2. an explicit path passed by the caller;
3. :func:`state_root` + the artefact's repository-relative default.

:func:`state_root` is ``QTS_STATE_ROOT`` when set, otherwise the repository root
detected from the installed package location (a checkout or an editable
install), otherwise ``~/.qts``. It is **never** the working directory, so two
processes on one machine always read the same state — and
:func:`paths_report` makes the resolved locations visible in the CLI, the API
and the static validator, so agreement is provable rather than assumed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

#: Repository-relative defaults for every machine-local artefact.
RELATIVE_DEFAULTS: dict[str, str] = {
    "setup": "data/setup/mt5_setup.json",
    "identity_pin": "data/evidence/demo_broker_identity_pin.json",
    "authorization": "data/evidence/demo_execution_authorization_2026-09-23.json",
    "registry": "data/evidence/demo_forward_validation_registry_2026-09-23.json",
    "db": "data/sqlite/qts.db",
    "journal_db": "data/sqlite/qts.db",
    "stage_db": "data/sqlite/qts.db",
    "observatory_db": "data/sqlite/forward_observatory.db",
}

#: Environment override per artefact (highest precedence, used verbatim).
ENV_OVERRIDES: dict[str, str] = {
    "setup": "QTS_SETUP_FILE",
    "identity_pin": "QTS_DEMO_IDENTITY_PIN",
    "authorization": "QTS_DEMO_AUTHORIZATION",
    "registry": "QTS_DEMO_REGISTRY",
    "db": "QTS_DB_PATH",
    "journal_db": "QTS_DEMO_JOURNAL_DB",
    "stage_db": "QTS_DEMO_STAGE_DB",
    "observatory_db": "QTS_OBSERVATORY_DB",
}

STATE_ROOT_ENV = "QTS_STATE_ROOT"
_USER_ROOT = Path.home() / ".qts"


def _detect_repo_root() -> Path | None:
    """The checkout/editable-install root, detected from this file's location.

    ``src/qts/config/paths.py`` → parents[3] is the repository root in a
    checkout or an editable install (both keep the source tree). A wheel or a
    frozen desktop build has no such marker and returns ``None``.
    """
    try:
        candidate = Path(__file__).resolve().parents[3]
    except IndexError:  # pragma: no cover - defensive
        return None
    if (candidate / "pyproject.toml").exists() and (candidate / "src" / "qts").is_dir():
        return candidate
    return None


def state_root() -> Path:
    """The ONE directory all machine-local state is anchored to."""
    env = (os.getenv(STATE_ROOT_ENV) or "").strip()
    if env:
        return Path(env).expanduser()
    detected = _detect_repo_root()
    if detected is not None:
        return detected
    return _USER_ROOT


def state_root_source() -> str:
    """Why :func:`state_root` resolved the way it did (auditable provenance)."""
    if (os.getenv(STATE_ROOT_ENV) or "").strip():
        return f"{STATE_ROOT_ENV}={os.getenv(STATE_ROOT_ENV)}"
    if _detect_repo_root() is not None:
        return "repository root detected from the installed package location"
    return f"no repository detected — user state directory {_USER_ROOT}"


def artifact_path(name: str, explicit: str | Path | None = None) -> Path:
    """Resolve one machine-local artefact path (never cwd-relative by default).

    ``explicit`` (a caller-supplied path, e.g. a CLI ``--db`` value) and the
    artefact's environment override are honoured verbatim; otherwise the
    repository-relative default is anchored at :func:`state_root`.
    """
    if name not in RELATIVE_DEFAULTS:
        raise KeyError(f"unknown QTS state artefact {name!r}")
    env_name = ENV_OVERRIDES.get(name)
    env_value = (os.getenv(env_name) or "").strip() if env_name else ""
    if env_value:
        return Path(env_value).expanduser()
    if explicit is not None and str(explicit).strip():
        return Path(str(explicit)).expanduser()
    return state_root() / RELATIVE_DEFAULTS[name]


def default_db_path() -> str:
    """Callable default for CLI ``--db`` options — anchored, never cwd-relative."""
    return str(artifact_path("db"))


def paths_report() -> dict[str, Any]:
    """Every resolved artefact location, for the CLI, the API and the validator.

    Displaying this on both surfaces is what makes "the UI and the CLI read the
    same state" checkable instead of hoped for.
    """
    root = state_root()
    out: dict[str, Any] = {
        "state_root": str(root),
        "state_root_source": state_root_source(),
        "working_directory": str(Path.cwd()),
        "cwd_independent": True,
        "artifacts": {},
    }
    for name, relative in RELATIVE_DEFAULTS.items():
        path = artifact_path(name)
        env_name = ENV_OVERRIDES.get(name)
        env_value = os.getenv(env_name) if env_name else None
        out["artifacts"][name] = {
            "path": str(path),
            "exists": path.exists(),
            "relative_default": relative,
            "source": (
                f"{env_name} (environment override)"
                if env_value
                else "state root + repository-relative default"
            ),
        }
    return out
