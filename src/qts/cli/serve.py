"""QTS CLI — production API server.

This is the supported way to run the QTS HTTP surface outside the desktop
launcher: inside a container, under systemd, or behind an operator's TLS proxy.
It is intentionally conservative:

* loopback is the default bind address;
* a non-loopback bind requires ``QTS_ALLOW_REMOTE=1`` (and should be paired with
  ``QTS_ALLOWED_ORIGINS`` plus a TLS-terminating proxy that authenticates the
  operator);
* the ``Server`` response header is disabled;
* shutdown is graceful, so an interrupted deploy finishes the in-flight request
  instead of dropping it.

No live-trading permission is created here. ``LIVE`` stays locked.
"""

from __future__ import annotations

import ipaddress
import os

import click

LOG_LEVELS = ["critical", "error", "warning", "info", "debug", "trace"]


def _is_loopback(host: str) -> bool:
    candidate = (host or "").strip().strip("[]").lower()
    if candidate in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


@click.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address. Loopback by default.")
@click.option("--port", default=8000, show_default=True, type=click.IntRange(1, 65535))
@click.option("--workers", default=1, show_default=True, type=click.IntRange(1, 8))
@click.option("--log-level", default="info", show_default=True, type=click.Choice(LOG_LEVELS))
@click.option(
    "--proxy-headers/--no-proxy-headers",
    default=False,
    help="Trust X-Forwarded-* from a reverse proxy you control.",
)
def serve(host: str, port: int, workers: int, log_level: str, proxy_headers: bool) -> None:
    """Run the QTS API/desktop server (production entry point)."""
    remote_allowed = os.getenv("QTS_ALLOW_REMOTE") == "1"
    if not _is_loopback(host) and not remote_allowed:
        raise click.ClickException(
            f"Refusing to bind {host!r}: QTS exposes an unauthenticated local operator API. "
            "Set QTS_ALLOW_REMOTE=1 only behind an authenticated TLS proxy, and list the "
            "public origin in QTS_ALLOWED_ORIGINS."
        )
    if remote_allowed and not os.getenv("QTS_ALLOWED_ORIGINS", "").strip():
        click.echo(
            "warning: QTS_ALLOW_REMOTE=1 without QTS_ALLOWED_ORIGINS — browser mutations "
            "from the public origin will be rejected (fail closed).",
            err=True,
        )
    if proxy_headers and not remote_allowed:
        click.echo("warning: --proxy-headers on a loopback bind trusts headers nobody forwards.", err=True)

    import uvicorn

    from qts import __version__

    click.echo(f"QTS {__version__} — API on http://{host}:{port} (workers={workers}, live=LOCKED)")
    uvicorn.run(
        "qts.api.server:app",
        host=host,
        port=port,
        workers=workers,
        log_level=log_level,
        server_header=False,
        proxy_headers=proxy_headers,
        timeout_graceful_shutdown=10,
        access_log=True,
    )
