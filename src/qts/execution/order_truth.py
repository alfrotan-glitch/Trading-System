"""Canonical order and position ownership.

Three facts are authoritative, and they are not interchangeable:

* the broker's open positions are the venue truth for exposure;
* ``DemoOrderJournal`` is the durable evidence record for DEMO orders
  (client ids, tickets, deals, fills, slippage, P&L, close lifecycle);
* ``OrderManager`` is the execution engine's in-process working set for
  simulation and for the submit/reconcile path. It is not a second evidence
  store and must not be presented as broker truth.

LIVE orders are not representable. ``REAL_CAPITAL_EXPOSURE`` stays 0.
"""

from __future__ import annotations

from pathlib import Path

from qts.execution.demo_journal import DemoOrderJournal

SIMULATION_WORKING_SET = "qts.execution.engine.OrderManager"
DEMO_EVIDENCE_RECORD = "qts.execution.demo_journal.DemoOrderJournal"
VENUE_POSITION_AUTHORITY = "broker.positions"


def open_demo_journal(db_path: Path | str) -> DemoOrderJournal:
    """Open the only durable DEMO order record."""
    return DemoOrderJournal(db_path=db_path)
