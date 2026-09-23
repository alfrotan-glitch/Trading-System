#!/usr/bin/env python3
"""Run H-DIR-01 ONLY on a separately attested discovery-only view.

No full-archive fallback, release download, extraction, order or execution
path exists. Missing authorization means NOT RUN, not a null directional result.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qts.research.xauusd_directional import HYPOTHESIS, PREREGISTRATION, SCHEMA, render_report
from qts.research.xauusd_directional_view import ViewBoundaryViolation, preflight_view, scan_attested_view

AUTHORITY = Path("docs/xauusd_directional_view_authority.json")
DEFAULT_VIEW = Path("data/raw/xauusd_discovery_view")
DEFAULT_OUTPUT = Path("reports/xauusd_directional_state.json")
DEFAULT_MARKDOWN = Path("reports/xauusd_directional_state.md")


def _not_run(reason: str, *, status: str = "NOT_RUN_ACCESS_BLOCKED") -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "preregistration": PREREGISTRATION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "reason": reason,
        "decision": "INCONCLUSIVE",
        "hypotheses": {
            HYPOTHESIS: {
                "status": (
                    "INVALIDATED"
                    if status == "PROTOCOL_VIOLATION"
                    else "INCONCLUSIVE"
                    if status == "INCONCLUSIVE_MEASUREMENT"
                    else "NOT RUN"
                ),
                "reason": reason,
            }
        },
        "edge_claim": "NOT ESTABLISHED",
        "strategy_promoted": False,
        "held_out_span_opened": False,
        "window": {"held_out_rows_read": 0},
        "safety": {"DEMO_EXECUTION": "DISABLED", "confirm_live": False, "orders_submitted": 0},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H-DIR-01: preauthorized discovery view only; no zip support")
    parser.add_argument("--view-dir", type=Path, default=DEFAULT_VIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args(argv)
    # Authorization is NOT supplied by a CLI flag or by the view itself. It
    # must be a separately reviewed, pinned artifact in this checkout.
    if not AUTHORITY.is_file():
        report = _not_run("No independently approved discovery-only manifest digest; archive must remain closed")
        exit_code = 2
    elif not args.view_dir.is_dir():
        report = _not_run("Attested discovery-only view not available; no full-zip fallback")
        exit_code = 2
    else:
        try:
            authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
            preflight_view(args.view_dir, authority)
        except (ValueError, OSError, KeyError) as exc:
            report = _not_run(f"Discovery-only access/integrity preflight failed: {exc}")
            exit_code = 2
        else:
            try:
                report = scan_attested_view(args.view_dir, authority)
                report["generated_at_utc"] = datetime.now(UTC).isoformat()
                report["code_identity"] = {
                    "module": "qts.research.xauusd_directional",
                    "git_sha": os.environ.get("GITHUB_SHA", "UNAVAILABLE"),
                    "host": os.environ.get("QTS_DISCOVERY_EXECUTION_HOST", "UNAVAILABLE"),
                }
                exit_code = 0
            except ViewBoundaryViolation as exc:
                # A misleading/corrupt view exposed a locked timestamp. Do
                # not falsely certify the held-out span as untouched.
                report = _not_run(f"Boundary protocol violated: {exc}", status="PROTOCOL_VIOLATION")
                report["held_out_span_opened"] = True
                report["window"]["held_out_rows_read"] = "UNKNOWN: LOCKED TIMESTAMP OBSERVED"
                exit_code = 2
            except (ValueError, OSError, KeyError) as exc:
                # A discovery-view scan failed after its preflight. It cannot
                # be counted as a valid test or as evidence against an edge.
                report = _not_run(
                    f"Attested discovery-view measurement failed: {exc}", status="INCONCLUSIVE_MEASUREMENT"
                )
                exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_report(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": (report.get("hypotheses") or {}).get(HYPOTHESIS, {}).get("status"),
                "held_out_span_opened": report["held_out_span_opened"],
                "strategy_promoted": False,
            }
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
