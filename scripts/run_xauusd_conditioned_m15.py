#!/usr/bin/env python3
"""Run the fixed, discovery-only conditioned-volatility M15 assay."""

from __future__ import annotations

import argparse
from pathlib import Path

from qts.research.xauusd_conditioned_m15 import (
    DEFAULT_INPUT,
    json_text,
    render_report,
    run_discovery,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_discovery(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json_text(report), encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_report(report), encoding="utf-8")
    print(f"discovery-only: {args.input} rows={report['input']['rows']} hypotheses=4 orders_submitted=0")
    print(f"JSON: {args.output}")
    print(f"Markdown: {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
