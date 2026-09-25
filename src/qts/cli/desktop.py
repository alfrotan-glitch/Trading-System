"""QTS CLI — desktop."""

from __future__ import annotations

import click


@click.group()
def desktop() -> None:
    """Desktop application."""


@desktop.command("launch")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def desktop_launch(host: str, port: int) -> None:
    from qts.desktop.health import startup_health_check
    from qts.desktop.launcher import open_desktop_window, start_api_server

    click.echo("[desktop] startup health check")
    health = startup_health_check()
    for c in health["checks"]:
        click.echo(f"  {c['name']}: {'PASS' if c['passed'] else 'FAIL'} {c['detail']}")
    click.echo(f"overall: {health['overall']} status={health['system_status']}")
    server, thread = start_api_server(host, port)
    click.echo(f"API at http://{host}:{port}/ — opening desktop window")
    open_desktop_window(host, port)


@desktop.command("api")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def desktop_api(host: str, port: int) -> None:
    import uvicorn

    from qts.api.server import app

    click.echo(f"starting API server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


