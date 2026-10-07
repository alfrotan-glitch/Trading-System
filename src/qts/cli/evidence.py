"""QTS CLI — evidence."""

from __future__ import annotations

import json
from pathlib import Path

import click

from qts.cli.support import observatory_db_path


@click.group()
def evidence() -> None:
    """Sanitized session-evidence export/verify (Desktop -> auditable artifact)."""


@evidence.command("export-session")
@click.argument("session_id")
@click.option("--db", default=observatory_db_path, help="canonical observation store")
@click.option("--out", default=None, help="output path (default data/evidence/exports/<id>.session_evidence.json)")
def evidence_export_session(session_id: str, db: str, out: str | None) -> None:
    """Recompute ONE session's evidence from the canonical store and write a
    sanitized, digest-bound artifact. Run this ON THE DESKTOP that observed."""
    from qts.observability.session_export import SessionExportError, write_session_evidence

    try:
        art, path = write_session_evidence(session_id, db_path=db, out_path=out)
    except SessionExportError as e:
        click.echo(f"export refused (fail-closed): {e}", err=True)
        raise SystemExit(1) from e
    c = art["counters"]
    click.echo(f"exported session {session_id} -> {path}")
    click.echo(
        f"  ticks={c['tick_count']} provenance={c['ticks_by_provenance']} "
        f"duplicates_in_store={c['duplicate_raw_stamps_in_store']} status={art['session']['status']}"
    )
    click.echo(f"  chain_root={art['digest']['chain_root']}")
    click.echo("  NOTE: transfer only this artifact; it contains no credentials.")


@evidence.command("verify")
@click.argument("artifact_path")
def evidence_verify(artifact_path: str) -> None:
    """Structurally verify an exported session-evidence artifact. Proves internal
    consistency + contract conformance, never the Desktop origin by itself."""
    from qts.observability.session_export import verify_session_export

    rpt = verify_session_export(Path(artifact_path))
    click.echo(json.dumps(rpt, indent=2, default=str))
    if rpt["verdict"] != "CONSISTENT":
        raise SystemExit(1)


@evidence.command("export-research")
@click.argument("session_id")
@click.option("--db", default=observatory_db_path, help="canonical observation store")
@click.option("--out", default=None, help="output path (default data/evidence/exports/<id>.research_snapshot.json)")
def evidence_export_research(session_id: str, db: str, out: str | None) -> None:
    """Export the COMPLETE research snapshot (full accepted payloads + acquisition
    ledger + run/clock identity) for ONE session. Separate contract from the v1
    audit artifact. Run this ON THE DESKTOP that observed."""
    from qts.observability.research_snapshot import ResearchSnapshotError, write_research_snapshot

    try:
        art, path = write_research_snapshot(session_id, db_path=db, out_path=out)
    except ResearchSnapshotError as e:
        click.echo(f"research snapshot refused (fail-closed): {e}", err=True)
        raise SystemExit(1) from e
    rec = art["reconciliation"]
    click.echo(f"research snapshot {session_id} -> {path}")
    click.echo(
        f"  accepted_rows={art['accepted']['count']} ledger_rows={art['ledger']['count']} "
        f"agreement={rec['ledger_store_agreement']}"
    )
    click.echo(f"  outcomes={art['ledger']['counts_by_outcome']}")
    click.echo(f"  manifest_hash={art['integrity']['manifest_hash']}")
    click.echo("  NOTE: transfer only this artifact; it contains no credentials.")


@evidence.command("verify-research")
@click.argument("snapshot_path")
def evidence_verify_research(snapshot_path: str) -> None:
    """Verify a research snapshot: completeness, ledger/store agreement, hashes
    and metadata integrity. Proves internal consistency, never Desktop origin."""
    from qts.observability.research_snapshot import verify_research_snapshot_file

    rpt = verify_research_snapshot_file(Path(snapshot_path))
    click.echo(json.dumps(rpt, indent=2, default=str))
    if rpt["verdict"] != "CONSISTENT":
        raise SystemExit(1)


