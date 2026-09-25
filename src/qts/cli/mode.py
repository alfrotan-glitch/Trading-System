"""QTS CLI — mode."""

from __future__ import annotations

import json

import click


@click.group()
def mode() -> None:
    """Show or declare the process mode (DEMO-capable modes only; LIVE never)."""


@mode.command("show")
def mode_show() -> None:
    """The effective mode, and exactly which source decided it."""
    from qts.domain.modes import effective_mode_report, resolve_mode

    report = effective_mode_report()
    click.echo(f"effective mode: {resolve_mode().value}")
    click.echo(f"decided by:     {report['mode_source']}")
    click.echo(f"declaration:    {report['persisted_mode_declaration'] or '<none>'}")
    click.echo(f"env:            QTS_MODE={report['mode_source_env'].get('QTS_MODE')} QTS_ENV={report['mode_source_env'].get('QTS_ENV')}")
    if report["refused_real_capital_declarations"]:
        click.echo(f"REFUSED:        {report['refused_real_capital_declarations']}", err=True)
    if report.get("resolution_error"):
        click.echo(f"error:          {report['resolution_error']}", err=True)
    click.echo(json.dumps(report, indent=2, default=str))


@mode.command("declare")
@click.argument("value")
def mode_declare(value: str) -> None:
    """Persist the mode declaration that BOTH the CLI and the web backend read.

    ``QTS_MODE`` is per-process environment: a backend launched by the desktop
    app never sees what an operator exported in one shell, which is how the UI
    came to report DEVELOPMENT while the CLI reported DEMO_EXECUTION. This writes
    the declaration into the machine-local setup file that both surfaces resolve
    from (below the environment in precedence). LIVE and its aliases are refused
    — LIVE stays locked behind its own gate and can never be declared here.
    """
    from qts.config.wizard import declare_mode
    from qts.domain.modes import mode_source, resolve_mode

    try:
        result = declare_mode(value)
    except ValueError as exc:
        click.echo(f"REFUSED: {exc}", err=True)
        raise SystemExit(2) from exc
    click.echo(f"declared: {result['declared']} -> {result['stored_at']}")
    click.echo(f"precedence: {result['precedence']}")
    click.echo(f"effective mode now: {resolve_mode().value} (decided by {mode_source()})")


