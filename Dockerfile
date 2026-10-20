# QTS production image — research workstation + local operator API.
#
# Live trading is structurally locked in the code. This image adds no trading
# permission; it packages the same fail-closed product.
#
# Build:  docker build -t qts:1.0.1 .
# Run:    docker run --rm -p 127.0.0.1:8000:8000 -v qts-state:/data qts:1.0.1
# Open:   http://127.0.0.1:8000/

# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    QTS_STATE_ROOT=/data \
    QTS_API_HOST=0.0.0.0 \
    QTS_API_PORT=8000 \
    QTS_ALLOW_REMOTE=1 \
    QTS_ENV=dev \
    QTS_MT5_MODE=MOCK

WORKDIR /app

# tini reaps zombies and forwards SIGTERM, so `docker stop` is a graceful shutdown.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# 1) Runtime dependencies, exactly the verified lock.
COPY requirements-prod.lock ./
RUN pip install --no-cache-dir -r requirements-prod.lock \
    && pip install --no-cache-dir setuptools wheel

# 2) The product itself. No dependencies resolved here: the lock is the authority.
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY data ./data
COPY docker/entrypoint.sh /usr/local/bin/qts-entrypoint
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
    && chmod 0555 /usr/local/bin/qts-entrypoint \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin qts \
    && mkdir -p /data \
    && chown -R qts:qts /data /app

USER qts

VOLUME ["/data"]
EXPOSE 8000

# Liveness only (no broker/SQLite access): a dependency outage must not restart-loop the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=3).status == 200 else 1)"]

ENTRYPOINT ["tini", "--", "qts-entrypoint"]
CMD []
