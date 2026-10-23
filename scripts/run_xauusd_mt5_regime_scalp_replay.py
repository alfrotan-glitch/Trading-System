"""Evaluate the frozen QTS 1m scalp idea on the LOCAL MT5 discovery window.

Read-only for market data; never sends orders, registers strategies, or
presents its estimates as audited executions/profitability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.data.mt5_timestamp_basis import timestamp_basis_assessment
from qts.execution.scalp_exit import ScalpExitPlan
from qts.research.mt5_tick_bars import read_broker_bars
from qts.research.scalp_replay import replay_scalp_bars
from qts.research.xauusd_tick_discovery import discovery_cutoff

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATA_ROOT = REPO_ROOT / "data" / "raw" / "mt5_ticks"
LOCAL_REPORT_ROOT = REPO_ROOT / "data" / "raw" / "scalp_replay_reports"

# Frozen research-only decision thresholds; no optimizer or CLI price tuning.
PLAN = ScalpExitPlan.from_mapping({
    "take_profit_net_bps": "5",
    "extra_cost_reserve_bps": "2",
    "max_loss_net_bps": "12",
    "max_spread_bps": "3",
    "max_tick_age_s": "3",
})


def discover_dataset(root: Path, timestamp_evidence: dict[str, Any]) -> Path:
    """Select the longest COMPLETE digest-bound XAUUSD dataset, never by returns.

    All choices are based on acquisition integrity and sample size. No strategy
    results are inspected, so choosing a dataset cannot optimize a backtest.
    """
    permitted = set(timestamp_evidence.get("dataset_sha256s") or [])
    eligible: list[tuple[int, str, Path]] = []
    if not root.is_dir():
        raise ValueError("local MT5 raw-data directory not found")
    for manifest_path in root.rglob(MANIFEST_FILENAME):
        if "xauusd" not in str(manifest_path.parent).lower():
            continue
        try:
            doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = doc.get("row_count")
        if (
            doc.get("status") != "COMPLETE"
            or doc.get("dataset_sha256") not in permitted
            or not isinstance(rows, int) or rows <= 0
            or not doc.get("parts")
        ):
            continue
        eligible.append((rows, str(manifest_path.parent), manifest_path.parent))
    if not eligible:
        raise ValueError("no COMPLETE XAUUSD MT5 dataset matches independent timestamp evidence")
    return max(eligible)[2]


def run(dataset_dir: Path, timestamp_evidence: dict[str, Any]) -> dict[str, Any]:
    """Replay only the historical discovery portion, excluding seen holdout."""
    manifest = json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    if manifest.get("status") != "COMPLETE":
        raise ValueError("scalp replay requires a COMPLETE immutable MT5 acquisition")
    if not manifest.get("dataset_sha256") or not manifest.get("parts"):
        raise ValueError("scalp replay requires a complete digest and nonempty parts ledger")
    basis = timestamp_basis_assessment(manifest, timestamp_evidence)
    if basis.get("status") not in {"CONFIRMED", "MEASURED_SAME_SESSION"}:
        raise ValueError("MT5 timestamp basis unconfirmed; refusing scalp replay")
    bars = read_broker_bars(dataset_dir, manifest.get("parts") or [])
    start, end = int(bars.time_msc.min()), int(bars.time_msc.max())
    cutoff = discovery_cutoff(start, end)
    report = replay_scalp_bars(bars, exit_plan=PLAN, end_exclusive_time_msc=cutoff)
    # Side-by-side separate replays on precisely the SAME discovery bars.
    # No cherry-picking, mixing fills, or strategy promotion.
    earlier = replay_scalp_bars(
        bars, exit_plan=PLAN, end_exclusive_time_msc=cutoff,
        entry_mode="anticipatory",
    )
    report["anticipatory_comparison"] = {
        "mode": earlier["entry_mode"],
        "signals": earlier["signals"],
        "metrics": earlier["metrics"],
        "entry_refusals_cost_gate": earlier["entry_refusals_cost_gate"],
        "early_chase_refusals": earlier["early_chase_refusals"],
        "observed_bar_gaps": earlier["observed_bar_gaps"],
        "stop_detection_basis": earlier["stop_detection_basis"],
        "decision": "RESEARCH_ONLY_NOT_VALIDATED",
    }
    report["source"] = {
        "manifest_dataset_sha256": manifest.get("dataset_sha256"),
        "timestamp_basis": basis,
        "data_start_time_msc": start,
        "discovery_cutoff_time_msc": cutoff,
        "holdout_excluded": True,
        "raw_tick_count": manifest.get("row_count"),
    }
    return report


def _markdown(report: dict[str, Any]) -> str:
    m = report["metrics"]
    return "\n".join([
        "# XAUUSD regime scalp — costed discovery-only replay",
        "",
        "**Research only. No validated edge. No broker orders. LIVE locked.**",
        "",
        f"- One-minute bars studied: {report['dataset_bars']}",
        f"- Proposed entries: {report['signals']}",
        f"- Simulated completed trades: {m['trades']}",
        f"- Mean net bps per trade (estimated): {m['mean_net_bps']}",
        f"- Win rate (estimated): {m['win_rate']}",
        f"- Sum of trade bps (not compounded): {m['total_net_bps_additive']}",
        f"- Hypothetical mean net bps with stops filled at trigger: {m['mean_net_bps_if_stop_at_trigger']}",
        f"- Stop-fill-model drag bps per trade: {m['stop_fill_assumption_drag_bps_per_trade']}",
        f"- Intrabar stop touches with unknown actual fills: {m['uncertain_intrabar_stop_count']}",
        f"- All uncertain exits, including gaps/end: {m['uncertain_exit_count']}",
        f"- Broker stop-detection basis: {report['stop_detection_basis']}",
        f"- Broker bar gaps: {report['observed_bar_gaps']}",
        "",
        "## Unconfirmed early-entry comparison (same discovery window)",
        "",
        f"- Anticipatory proposed signals: {report['anticipatory_comparison']['signals']}",
        f"- Anticipatory trades: {report['anticipatory_comparison']['metrics']['trades']}",
        f"- Anticipatory estimated mean net bps: {report['anticipatory_comparison']['metrics']['mean_net_bps']}",
        f"- Anticipatory estimated win rate: {report['anticipatory_comparison']['metrics']['win_rate']}",
        f"- Anticipatory hypothetical mean net bps with stops filled at trigger: {report['anticipatory_comparison']['metrics']['mean_net_bps_if_stop_at_trigger']}",
        f"- Anticipatory stop-fill-model drag bps per trade: {report['anticipatory_comparison']['metrics']['stop_fill_assumption_drag_bps_per_trade']}",
        "",
        "The stop-trigger scenario is hypothetical: it is NOT a demonstrated executable fill.",
        "Do NOT choose a winning mode from this discovery comparison and call it validated.",
        "",
        "## By trading family",
        "",
        *[
            f"- {family}: trades={values['trades']}; mean estimated net bps={values['mean_net_bps']}"
            for family, values in m["by_family"].items()
        ],
        "",
        "## Limits",
        "",
        *[f"- {x}" for x in report["limitations"]],
        "",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, help="Override automatic local discovery")
    parser.add_argument(
        "--timestamp-evidence", type=Path,
        default=REPO_ROOT / "data" / "evidence" / "mt5_timestamp_basis_20261023.json",
    )
    # Reports contain broker-derived trade details and must remain in the
    # existing gitignored raw-data tree, never in committed evidence.
    parser.add_argument("--output", type=Path, default=LOCAL_REPORT_ROOT / "report.json")
    parser.add_argument("--markdown", type=Path, default=LOCAL_REPORT_ROOT / "report.md")
    args = parser.parse_args(argv)
    evidence = json.loads(args.timestamp_evidence.read_text(encoding="utf-8"))
    dataset_dir = args.dataset_dir if args.dataset_dir is not None else discover_dataset(LOCAL_DATA_ROOT, evidence)
    report = run(dataset_dir, evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "metrics": report["metrics"], "source": report["source"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
