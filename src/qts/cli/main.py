"""QTS command line composition."""

from __future__ import annotations

import click

from qts.cli.audit import audit
from qts.cli.data import data
from qts.cli.demo import demo
from qts.cli.desktop import desktop
from qts.cli.edge import edge
from qts.cli.evidence import evidence
from qts.cli.mode import mode
from qts.cli.ops import backtest, health, run_cmd, validate_cmd
from qts.cli.research import research
from qts.cli.risk import risk


@click.group()
def main() -> None:
    """QTS — research, risk, and DEMO-forward trading."""


main.add_command(data)
main.add_command(backtest)
main.add_command(validate_cmd)
main.add_command(risk)
main.add_command(health)
main.add_command(audit)
main.add_command(evidence)
main.add_command(research)
main.add_command(edge)
main.add_command(run_cmd)
main.add_command(desktop)
main.add_command(mode)
main.add_command(demo)
