"""QTS CLI — Edge Lab forward observation.

A backtest holdout can be read once. After that, the only genuinely unseen
evidence is future data, recorded with a frozen definition. These commands are
that pipeline: register, log, score.

Nothing here promotes a strategy, changes a gate, or touches live trading.
"""

from __future__ import annotations

import json

import click
import pandas as pd

from qts.research.edgelab import forward
from qts.research.edgelab.candidates import candidates


@click.group("forward")
def forward_group() -> None:
    """Forward observation of registered candidates (never promotes)."""


@forward_group.command("candidates")
def forward_candidates() -> None:
    """List the frozen candidate catalogue and registration status."""
    reg = forward.registered()
    rows = []
    for c in candidates():
        rec = reg.get(c.id)
        rows.append(
            {
                "id": c.id,
                "name": c.name,
                "family": c.family,
                "hash": c.definition_hash(),
                "registered": bool(rec),
                "registered_at": (rec or {}).get("registered_at", "—"),
            }
        )
    click.echo(pd.DataFrame(rows).to_string(index=False))
    click.echo(
        "\nA candidate is a hypothesis that passed the pre-registered gate on development "
        "data. Registration is not validation: no candidate is proven until it earns "
        "forward evidence."
    )


@forward_group.command("register")
@click.option("--id", "candidate_id", default=None, help="register one candidate (default: all)")
def forward_register(candidate_id: str | None) -> None:
    """Freeze candidate definitions in the registry (refuses silent edits)."""
    for c in candidates():
        if candidate_id and c.id != candidate_id:
            continue
        rec = forward.register(c)
        click.echo(f"registered {rec['id']} ({rec['name']}) hash={rec['definition_hash']}")


@forward_group.command("log")
@click.option("--as-of", default=None, help="date to record (default: latest available bar)")
def forward_log(as_of: str | None) -> None:
    """Never transform old bars or rejected hypotheses into new evidence.

    The former command attached same-day macro closes to an AM gold fix
    (known look-ahead), and allowed --as-of historical rewrites. Genuinely
    prospective input must instead go through a frozen, source-verified
    completed-close collection path.
    """
    from qts.research.edgelab.candidates import active_candidates

    active = active_candidates()
    if not active:
        click.echo(
            "No active, validated-for-forward-research candidate exists. "
            "The rejected XL-001 macro rule will not be recorded. "
            "For market evidence without placing orders, use the Windows "
            "'Start Observation (No Orders)' function with a verified MT5 DEMO account."
        )
        return
    if as_of:
        raise click.ClickException(
            "Manual historical --as-of logging is disabled: records created "
            "after an outcome is known cannot count as forward evidence."
        )
    raise click.ClickException(
        "Legacy manual signal logging is disabled because its AM-fix/macro "
        "timing is non-executable. Register the frozen active rule and use a "
        "timestamp-verified broker completed-bar collector. No records written."
    )


@forward_group.command("score")
@click.option("--json", "as_json", is_flag=True, help="machine-readable output")
def forward_score(as_json: bool) -> None:
    """Score the forward ledger — the only genuinely unseen evidence available."""
    ledger = forward.load_ledger()
    if ledger.empty:
        click.echo("No forward observations recorded yet. Run `qts forward log` daily.")
        return
    df = forward.score(ledger)
    if as_json:
        click.echo(json.dumps({"rows": df.to_dict(orient="records")}, indent=2))
        return
    click.echo(df.to_string(index=False))
    from qts.research.edgelab import CostModel

    click.echo(
        f"\nCosts are ASSUMED (~{CostModel().per_side_bps():.2f} bps/side), not measured. "
        "`observations_for_significance` is the count needed to reach alpha_t=2.5 at the "
        "currently observed effect size — a projection, not a result."
    )
