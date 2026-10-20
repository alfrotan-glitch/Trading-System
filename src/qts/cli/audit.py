"""QTS CLI — audit."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

from qts.observability.audit import PROTECTED_EVENT_TYPES, SqliteAuditLog


@click.group()
def audit() -> None:
    pass


@audit.command("query")
@click.option("--strategy", default=None)
@click.option("--limit", default=20, type=int)
def audit_query(strategy: str | None, limit: int) -> None:
    log = SqliteAuditLog()

    events = log.query(strategy_id=strategy, limit=limit)
    for e in events:
        click.echo(f"{e.event_time.isoformat()} {e.event_type.value} {json.dumps(e.payload, default=str)[:120]}")


@audit.command("stats")
@click.option("--json-out", default=None, help="also write the report to this file")
def audit_stats(json_out: str | None) -> None:
    """Rows, age and size of both audit sinks, plus the retention policy.

    The audit log is evidence. This reports how large it has grown so an operator
    can act BEFORE a full disk stops the engine, instead of after.
    """
    report = SqliteAuditLog().stats()
    mega = 1024 * 1024
    click.echo(f"database:   {report['db_path']}  ({report['db_bytes'] / mega:.2f} MiB)")
    click.echo(f"rows:       {report['rows']:,}")
    click.echo(f"oldest:     {report['oldest_event_time'] or '—'}")
    click.echo(f"newest:     {report['newest_event_time'] or '—'}")
    if report["jsonl_path"]:
        click.echo(
            f"jsonl:      {report['jsonl_path']}  "
            f"({report['jsonl_bytes'] / mega:.2f} MiB, {report['jsonl_lines']:,} lines)"
        )
    if report["rows_by_type"]:
        click.echo("by type:")
        for name, count in report["rows_by_type"].items():
            click.echo(f"  {name.ljust(22)} {count:>10,}")
    click.echo(f"prunable:   {', '.join(report['prunable_types'])}")
    click.echo(f"protected:  {', '.join(report['protected_types'])} (never pruned)")
    if json_out:
        target = Path(json_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        click.echo(f"wrote {target}")


@audit.command("prune")
@click.option("--older-than-days", default=90, show_default=True, type=click.IntRange(1, 36500))
@click.option("--confirm", is_flag=True, help="actually delete; without it this is a dry run")
@click.option("--vacuum", is_flag=True, help="compact the database after deleting")
@click.option(
    "--rotate-jsonl",
    is_flag=True,
    help="move the live JSONL sink to a timestamped archive (history is preserved)",
)
@click.option("--archive-dir", default=None, help="where rotated JSONL archives are written")
def audit_prune(
    older_than_days: int,
    confirm: bool,
    vacuum: bool,
    rotate_jsonl: bool,
    archive_dir: str | None,
) -> None:
    """Age out high-volume market events. SAFETY EVIDENCE IS NEVER DELETED.

    Only BAR, TICK, SIGNAL, NO_TRADE, POSITION_UPDATE and ACCOUNT_UPDATE rows older
    than the cutoff can be removed. Kill switches, risk vetoes, orders, fills,
    reconciliations, lifecycle transitions and data-quality alerts are kept at any
    age — there is no flag that removes them. Run without --confirm to preview.
    """
    log = SqliteAuditLog()
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = log.prune(before=cutoff, dry_run=not confirm, vacuum=vacuum)
    mode = "DELETED" if confirm else "WOULD DELETE (dry run)"
    click.echo(f"cutoff:          {result['cutoff']}")
    click.echo(f"{mode}:     {result['matched_prunable']} prunable event(s)")
    click.echo(
        f"protected kept:  {result['protected_kept']} safety event(s) — never removable by this command"
    )
    if confirm:
        click.echo(f"deleted:         {result['deleted']}")
        if result.get("vacuumed"):
            click.echo(f"vacuumed:        {result['db_bytes'] / (1024 * 1024):.2f} MiB")
        click.echo("recorded:        audit_prune lifecycle event written")
    else:
        click.echo("nothing was deleted; re-run with --confirm to apply")
    if rotate_jsonl:
        archive = log.rotate_jsonl(archive_dir=archive_dir)
        click.echo(f"jsonl:           archived to {archive}" if archive else "jsonl:           nothing to rotate")
    if not confirm and rotate_jsonl:
        click.echo("warning: --rotate-jsonl applied even though the database prune was a dry run", err=True)
    click.echo(f"protected types: {', '.join(sorted(t.value for t in PROTECTED_EVENT_TYPES))}")


@audit.command("ship")
@click.option("--jsonl", default=None, help="JSONL sink to ship (default: the anchored audit log)")
@click.option("--shipper", default="local", type=click.Choice(["local", "s3"]))
@click.option("--bucket", default=None, help="S3 bucket (required for s3)")
@click.option("--prefix", default="qts/audit/")
def audit_ship(jsonl: str | None, shipper: str, bucket: str | None, prefix: str) -> None:

    from qts.config.paths import artifact_path
    from qts.observability.shipper import LocalShipper, S3Shipper, ship_audit_logs

    # The anchored sink, not <cwd>/logs/audit.jsonl — shipping must never silently
    # target a file that only exists because of where the command was run.
    path = Path(jsonl) if jsonl else artifact_path("audit_jsonl")
    if shipper == "s3":
        if not bucket:
            click.echo("s3 shipper requires --bucket", err=True)
            raise SystemExit(2)
        shipper_obj: S3Shipper | LocalShipper = S3Shipper(bucket=bucket, prefix=prefix)
    else:
        shipper_obj = LocalShipper()
    uri = ship_audit_logs(path, shipper_obj)
    if uri:
        click.echo(f"shipped {path} -> {uri}")
    else:
        click.echo(f"ship failed or {path} not found", err=True)
        raise SystemExit(1)


