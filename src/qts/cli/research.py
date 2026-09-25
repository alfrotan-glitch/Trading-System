"""QTS CLI — research."""

from __future__ import annotations

import json
from pathlib import Path

import click

from qts.data.store import SqliteParquetDataStore
from qts.research.agent import NullAgent
from qts.research.experiment import ExperimentStore


@click.group()
def research() -> None:
    pass


@research.command("propose")
@click.option("--n", default=3, type=int)
def research_propose(n: int) -> None:
    agent = NullAgent()
    hyps = agent.propose(n=n)
    for h in hyps:
        click.echo(f"{h.id}: {h.statement} | falsifiability: {h.falsifiability}")
        store = ExperimentStore()
        store.put_hypothesis(h)


@research.command("impulse")
@click.option("--data-version", default=None, help="usable data version (default: latest usable)")
@click.option("--root", default="data", help="data root directory")
@click.option("--ledger-db", default=None, help="trial ledger SQLite (default: <root>/sqlite/qts.db)")
@click.option("--out", default=None, help="evidence JSON (default: <root>/evidence/impulse_research.json)")
@click.option("--report-out", default=None, help="optional markdown report path")
@click.option("--seed", default=42, type=int)
def research_impulse(
    data_version: str | None, root: str, ledger_db: str | None, out: str | None, report_out: str | None, seed: int
) -> None:
    """Impulse-continuation event study (RESEARCH ONLY — never enables trading).

    Fail-closed: exits non-zero with an honest message when no usable dataset
    exists. Never fabricates data, never promotes anything, never touches
    live eligibility or order submission.
    """
    from qts.research.impulse import ImpulseResearchConfig, render_markdown_report, run_impulse_research

    root_p = Path(root)
    ledger_path = Path(ledger_db) if ledger_db else root_p / "sqlite" / "qts.db"
    out_path = Path(out) if out else root_p / "evidence" / "impulse_research.json"
    store = SqliteParquetDataStore(root=root_p)
    try:
        try:
            evidence = run_impulse_research(
                store,
                data_version=data_version,
                cfg=ImpulseResearchConfig(seed=seed),
                ledger_db_path=ledger_path,
                partition_db_path=ledger_path,
                evidence_dir=root_p / "evidence",
            )
        except ValueError as e:
            raise click.ClickException(str(e)) from e
    finally:
        store.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    if report_out:
        rp = Path(report_out)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(render_markdown_report(evidence), encoding="utf-8")

    concl = evidence["conclusion"]
    t = evidence["analysis"]["totals"]
    click.echo(f"mode: {evidence['mode']}")
    click.echo(
        f"data: {evidence['provenance']['data_version']} class={evidence['provenance']['data_class']} "
        f"bars={evidence['provenance']['bars_read']}"
    )
    click.echo(
        f"event-study units: detected={t['events_detected_total']} family-scoped event records; "
        f"primary_outcomes={t.get('primary_outcomes_measured_total', t['events_detected_total'])}; "
        f"all_horizon_outcomes={t.get('all_horizon_outcomes_measured_total', t['events_measured_total'])}; "
        f"excluded={t['events_excluded_total']} trials_recorded={t['trials_recorded']}"
    )
    click.echo("event-study outcomes: see the human-readable report; units are measured event outcomes, not executed trades")
    click.echo(f"conclusion: {concl['conclusion']} (research {concl['go_block']})")
    for reason in concl["reasons"]:
        click.echo(f"  - {reason}")
    click.echo(f"evidence: {out_path}")
    click.echo("promotion: BLOCKED — research artifact only; live eligibility untouched")



@research.command("campaign")
@click.option(
    "--family", default="trend", type=click.Choice(["trend", "breakout", "mean_reversion", "momentum", "volatility"])
)
@click.option("--symbol", default="XAUUSD")
@click.option("--timeframe", default="1H")
@click.option("--data-version", required=True)
@click.option("--trials", default=12, type=int)
@click.option("--max-runtime", default=60, type=int)
def research_campaign(
    family: str, symbol: str, timeframe: str, data_version: str, trials: int, max_runtime: int
) -> None:
    from qts.research.campaign import CampaignConfig, run_campaign

    cfg = CampaignConfig(
        name=f"campaign-{family}",
        symbol=symbol,
        timeframe=timeframe,
        data_version=data_version,
        family=family,
        max_trials=trials,
        max_runtime_s=max_runtime,
        max_param_combinations=trials,
    )
    click.echo(f"launching bounded campaign family={family} trials={trials}")
    summary = run_campaign(cfg)
    Path("data/evidence").mkdir(parents=True, exist_ok=True)
    Path("data/evidence/campaign_last.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    click.echo(
        f"campaign {summary['campaign_id']} completed: passed={summary['passed']} failed={summary['failed']} total={summary['total_trials']} DSR N={summary['dsr_trial_count']}"
    )
    if summary["passed"] == 0:
        click.echo("BLOCK — no candidate survived scientific gates — keep NO_TRADE")


@research.command("autonomous")
@click.option("--name", default="autonomous-search")
@click.option("--symbol", default="XAUUSD")
@click.option("--timeframe", default="1H")
@click.option("--data-version", default=None)
@click.option("--trials", default=12, type=int)
@click.option("--max-runtime", default=60, type=int)
@click.option("--seed", default=42, type=int)
def research_autonomous(
    name: str, symbol: str, timeframe: str, data_version: str | None, trials: int, max_runtime: int, seed: int
) -> None:
    from qts.research.campaign_engine import run_autonomous_campaign

    click.echo(f"launching autonomous campaign {name} trials={trials} (11 steps, never LIVE)")
    result = run_autonomous_campaign(name, symbol, timeframe, data_version, trials, max_runtime, seed)
    Path("data/evidence").mkdir(parents=True, exist_ok=True)
    Path("data/evidence/autonomous_campaign.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    ev = result["evidence_portfolio"]
    click.echo(
        f"autonomous completed: trials {result['summary']['total_trials']} passed {result['summary']['passed']} distinct {result['novelty']['distinct_hypotheses']}"
    )
    click.echo(f"self-audit verdict {result['self_audit']['verdict']}")
    click.echo(f"overall {ev['overall']}")
    if ev["overall"].startswith("BLOCK"):
        click.echo("BLOCK — keep NO_TRADE — no genuine economic edge demonstrated")


@research.command("hypotheses")
def research_hypotheses() -> None:
    """List registered hypotheses. None is a validated trading opportunity."""
    from qts.research.catalog import list_hypotheses

    for row in list_hypotheses():
        click.echo(f"{row['id']}\t{row['edge_status']}\t{row['question']}")


@research.command(
    "run-hypothesis",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("hypothesis_id")
@click.pass_context
def research_run_hypothesis(ctx: click.Context, hypothesis_id: str) -> None:
    """Run one registered hypothesis. Does not authorize trading."""
    from qts.research.catalog import dispatch_hypothesis

    raise SystemExit(dispatch_hypothesis(hypothesis_id, list(ctx.args)))


