#!/usr/bin/env bash
# QTS release gate — one command that must pass before a tag is cut.
#
#   scripts/verify_release.sh                 # full gate (fast + extended + UI + build)
#   QTS_VERIFY_SKIP_EXTENDED=1 scripts/verify_release.sh
#
# It is intentionally fail-fast and offline-friendly: no test is skipped silently,
# and the built wheel is imported from a scratch directory to prove the packaged
# product (not the checkout) contains the UI and reports the release version.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${QTS_VENV:-$ROOT/.venv}"
PY="${PYTHON:-$VENV/bin/python}"
BIN="$VENV/bin"

fail() { echo "RELEASE GATE FAILED: $*" >&2; exit 1; }
step() { echo; echo "=== $* ==="; }

[ -x "$PY" ] || fail "no Python at $PY (create .venv and pip install -e '.[dev,packaging]')"
command -v node >/dev/null 2>&1 || fail "node is required for the UI checks"
command -v npm >/dev/null 2>&1 || fail "npm is required for the UI tests"

step "Static analysis: ruff"
"$BIN/ruff" check src tests

step "Static analysis: mypy"
"$BIN/mypy" src

step "Static analysis: bandit"
"$BIN/bandit" -q -r src

step "Python fast suite"
"$PY" -m pytest -q --ignore=tests/integration --ignore=tests/research

if [ "${QTS_VERIFY_SKIP_EXTENDED:-0}" != "1" ]; then
    step "Python extended suite (integration + research)"
    "$PY" -m pytest -q --run-integration --run-research tests/integration tests/research
else
    echo "extended suite skipped by QTS_VERIFY_SKIP_EXTENDED=1 (record this in the release notes)"
fi

step "JavaScript syntax"
while IFS= read -r -d '' file; do
    node --check "$file"
done < <(find src/qts/desktop/ui/js -name '*.js' -print0)

step "UI test suite"
if [ ! -d node_modules ]; then
    fail "node_modules missing — run 'npm ci' first"
fi
npm test

step "Build wheel + sdist"
rm -rf dist build
"$PY" -m build --outdir dist >/dev/null
WHEEL="$(find dist -maxdepth 1 -name '*.whl' | head -n1)"
SDIST="$(find dist -maxdepth 1 -name '*.tar.gz' | head -n1)"
[ -n "$WHEEL" ] || fail "no wheel produced"
[ -n "$SDIST" ] || fail "no sdist produced"

step "Wheel smoke test (packaged artefacts, not the checkout)"
VERSION="$("$PY" -c 'import qts; print(qts.__version__)')"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
"$PY" - "$WHEEL" "$VERSION" <<'PY'
import sys, zipfile
wheel, version = sys.argv[1], sys.argv[2]
names = set(zipfile.ZipFile(wheel).namelist())
required = {
    "qts/__init__.py",
    "qts/api/server.py",
    "qts/desktop/ui/index.html",
    "qts/desktop/ui/js/main.js",
    "qts/desktop/ui/css/base.css",
    f"qts-{version}.dist-info/METADATA",
}
missing = sorted(required - names)
if missing:
    raise SystemExit(f"wheel is missing required files: {missing}")
print(f"wheel contains {len(names)} files, including the workstation UI, version {version}")
PY
mkdir -p "$TMP/wheel"
"$PY" -m zipfile -e "$WHEEL" "$TMP/wheel" >/dev/null
PYTHONPATH="$TMP/wheel" "$PY" - "$VERSION" "$TMP/wheel" <<'PY'
import sys
import qts
from qts.api.server import app  # noqa: F401  (full import graph must resolve)
from pathlib import Path
version, root = sys.argv[1], Path(sys.argv[2])
assert qts.__version__ == version, (qts.__version__, version)
assert Path(qts.__file__).resolve().is_relative_to(root.resolve()), qts.__file__
assert (root / "qts/desktop/ui/index.html").is_file()
print(f"imported packaged qts {qts.__version__} from {qts.__file__}")
PY

step "Release gate PASSED"
echo "Artifacts:"
ls -lh dist
