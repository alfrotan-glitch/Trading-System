#!/bin/sh
# QTS container entrypoint.
#
#  1. Seed machine-local state into the volume on first boot (the image ships the
#     committed evidence/policy files; the volume keeps journal, pin and DB state).
#  2. Establish the deterministic research data version QTS verifies at startup.
#     Without it the UI honestly reports `Blocked — verify_data`.
#  3. Replace this shell with the server so signals reach uvicorn.
set -eu

: "${QTS_STATE_ROOT:=/data}"
export QTS_STATE_ROOT

if [ ! -d "${QTS_STATE_ROOT}/data" ]; then
    echo "[entrypoint] seeding state root ${QTS_STATE_ROOT} from image defaults"
    mkdir -p "${QTS_STATE_ROOT}"
    cp -a /app/data "${QTS_STATE_ROOT}/data"
fi

if [ "${QTS_SKIP_BOOTSTRAP:-0}" != "1" ]; then
    echo "[entrypoint] qts data bootstrap"
    qts data bootstrap
fi

exec qts serve \
    --host "${QTS_API_HOST:-0.0.0.0}" \
    --port "${QTS_API_PORT:-8000}" \
    --workers "${QTS_WORKERS:-1}" \
    --log-level "${QTS_LOG_LEVEL:-info}"
