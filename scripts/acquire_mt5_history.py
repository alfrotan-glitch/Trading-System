"""Read-only MT5 historical tick acquisition driver — boundary discovery ladder.

Purpose
-------
Acquire complete, lossless, provenance-bound raw tick history for an exact
broker symbol (verified: ``XAUUSD@`` on the WM Markets DEMO terminal) and
characterize the deepest history the terminal actually serves — without any
per-row analysis while MT5 is being queried, and without ever fabricating a
completeness claim.

Workflow
--------
1. Fail-closed environment gate: MetaTrader5 package, initialize, exact
   symbol, verifiably-DEMO account.  Otherwise the run records a refusal
   status and no tick is queried.
2. For each requested window, ascending: chunked-lossless acquisition via
   :func:`qts.data.mt5_history_acquisition.acquire_window` into
   ``data/raw/mt5_ticks/<symbol>/<window>d__<end>/`` (gitignored, resumable,
   atomic per chunk).
3. Only after the acquisition ladder has stopped, run the deferred analysis
   (:func:`qts.data.mt5_history_analysis.analyze_dataset`) per acquired
   dataset — reading local Parquet only, no MT5.
4. Write a bounded machine-readable evidence report (no raw rows) recording
   per-window status, coverage, hashes and paths.

Status vocabulary (per window) — never guess a boundary
-------------------------------------------------------
- ``COMPLETE`` / ``EMPTY_COMPLETE`` — every resolved chunk answered successfully.
- ``PARTIAL_INTERRUPTED`` — operator/time budget stopped the run; resumable.
- ``PARTIAL_QUERY_ERROR`` — one or more chunks failed at the split floor.
- ``REUSED_EXISTING_COMPLETE`` — a previous COMPLETE dataset was kept (no re-acquisition).
- ``SKIPPED_BUDGET`` — not attempted because the global time budget ran out.
- ``REFUSED_*`` / ``MT5_PACKAGE_UNAVAILABLE`` / ``INITIALIZE_FAILED`` — fail-closed, nothing queried.

A failed window proves nothing about retention depth by itself; the report
states the largest COMPLETE window and the smallest failing chunk span as
separate facts.

This script never calls an order API and never writes credentials.  Run it on
the Windows machine where the already-connected DEMO terminal is running.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qts.data.mt5_history_acquisition import (  # noqa: E402
    DEFAULT_DATASET_ROOT,
    STATUS_COMPLETE,
    STATUS_EMPTY_COMPLETE,
    STATUS_PARTIAL_INTERRUPTED,
    STATUS_PARTIAL_QUERY_ERROR,
    AcquisitionRefused,
    Mt5ConnectionLost,
    _TimeBudget,
    acquire_window,
    require_read_only_demo,
    resolve_symbol,
    software_identity,
    terminal_identity,
)
from qts.data.mt5_history_analysis import analyze_dataset  # noqa: E402

REPORT_SCHEMA = "qts.mt5_history_acquisition_report.v1"
DEFAULT_WINDOWS_DAYS = "7,30,45,60,90,120,180,270,365"

NO_ORDER_APIS_STATEMENT = (
    "The only MT5 functions invoked by this workflow are: initialize, shutdown, last_error, "
    "account_info, terminal_info, symbol_info, symbol_select, copy_ticks_range. No order_send or any "
    "order/deal/history-order API is reachable from this workflow; it performs acquisition only and submits nothing (LIVE remains LOCKED)."
)


def _parse_windows(value: str) -> list[int]:
    values = sorted({int(part.strip()) for part in value.split(",") if part.strip()})
    if not values or any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("--windows-days must be positive day counts, e.g. 7,30,45,60,90,180,365")
    return values


def _dataset_dir(root: Path, symbol: str, days: int, end_utc: datetime) -> Path:
    token = "".join(ch if ch.isalnum() or ch in "-." else "_" for ch in symbol)
    stamp = end_utc.strftime("%Y%m%dT%H%M%SZ")
    return root / token / f"{days}d__{stamp}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _base_report(args: argparse.Namespace, status: str) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "report_generated_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "read_only": True,
        "orders_submitted": 0,
        "order_send_called": False,
        "no_order_apis_statement": NO_ORDER_APIS_STATEMENT,
        "requested_symbol": args.symbol,
        "windows_days_requested": args.windows_days,
        "dataset_root": str(args.dataset_root),
        "software": software_identity(None),
        "environment": {
            "environment": "DEMO_FORWARD",
            "observation_mode": "OBSERVE_ONLY",
            "execution_policy": "acquisition workflow only — no order path is invoked; LIVE = LOCKED",
        },
        "windows": [],
        "analyses": {},
        "boundary_assessment": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", default=os.getenv("QTS_MT5_SYMBOL", "XAUUSD@"))
    parser.add_argument("--windows-days", type=_parse_windows, default=_parse_windows(DEFAULT_WINDOWS_DAYS))
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--evidence", type=Path, default=Path("data/evidence/mt5_history_acquisition.json"))
    parser.add_argument("--chunk-hours", type=float, default=24.0, help="base chunk size (bounded memory)")
    parser.add_argument("--min-chunk-minutes", type=float, default=60.0, help="adaptive split floor")
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        default=55.0,
        help="global budget; on exhaustion the run stops safely and every unfinished window is marked SKIPPED_BUDGET",
    )
    parser.add_argument("--max-window-runtime-minutes", type=float, default=None, help="per-window budget")
    parser.add_argument("--max-chunk-rows", type=int, default=5_000_000)
    parser.add_argument("--end-utc", default=None, help="ISO anchor; default: now (fixed once for all windows)")
    parser.add_argument("--force", action="store_true", help="re-acquire even if a COMPLETE dataset exists")
    parser.add_argument("--no-analyze", action="store_true", help="skip the deferred analysis stage")
    parser.add_argument("--analyze-only", type=Path, default=None, help="analyze one existing dataset dir and exit")
    args = parser.parse_args(argv)

    if args.analyze_only is not None:
        # Deferred analysis is fully independent of MT5 (no MetaTrader5 import here either).
        report = analyze_dataset(args.analyze_only)
        rendered = json.dumps(report, indent=2, sort_keys=True, default=str) + "\n"
        print(rendered)
        out = Path(str(args.analyze_only)) / "analysis.json"
        out.write_text(rendered, encoding="utf-8")
        return 0 if report.get("schema") else 1

    budget = _TimeBudget(args.max_runtime_minutes * 60.0 if args.max_runtime_minutes else None)

    try:
        import MetaTrader5 as mt5  # noqa: N813
    except ImportError:
        report = _base_report(args, "MT5_PACKAGE_UNAVAILABLE")
        report["detail"] = (
            "MetaTrader5 python package unavailable in this environment (Windows + MT5 terminal required). "
            "No tick was queried, acquired, or fabricated. Run this script on the operator machine where the "
            "already-connected WM Markets DEMO terminal is running; see docs/mt5_history_acquisition.md."
        )
        _write_json(args.evidence, report)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 2

    report = _base_report(args, "INITIALIZE_FAILED")
    path_env = os.getenv("QTS_MT5_PATH") or os.getenv("MT5_PATH")
    initialized = bool(mt5.initialize(path=path_env) if path_env else mt5.initialize())
    if not initialized:
        report["detail"] = f"mt5.initialize() failed: {mt5.last_error()!r}. Nothing was queried."
        _write_json(args.evidence, report)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 2

    try:
        report["status"] = "RUNNING"
        report["software"]["mt5_package_version"] = getattr(mt5, "__version__", None)
        flags = getattr(mt5, "COPY_TICKS_ALL", None)
        if flags is None:
            report["status"] = "CAPABILITY_UNVERIFIED"
            report["detail"] = "COPY_TICKS_ALL constant not exposed by the MT5 module — refusing to guess."
            _write_json(args.evidence, report)
            return 2

        try:
            environment = require_read_only_demo(mt5)
            actual_symbol = resolve_symbol(mt5, args.symbol)
            terminal = terminal_identity(mt5)
        except (AcquisitionRefused, Mt5ConnectionLost) as exc:
            report["status"] = "REFUSED_FAIL_CLOSED"
            report["detail"] = str(exc)
            _write_json(args.evidence, report)
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
            return 2

        report["environment"].update(environment)
        report["terminal"] = terminal
        report["actual_symbol"] = actual_symbol
        report["end_utc_anchor"] = args.end_utc or datetime.now(UTC).isoformat()
        end_utc = datetime.fromisoformat(report["end_utc_anchor"])
        if end_utc.tzinfo is None:
            end_utc = end_utc.replace(tzinfo=UTC)
        report["mt5_flags"] = {"COPY_TICKS_ALL": int(flags)}

        for days in args.windows_days:
            start_utc = end_utc - timedelta(days=days)
            window_record: dict[str, Any] = {
                "window_days": days,
                "requested_start_utc": start_utc.isoformat(),
                "requested_end_utc": end_utc.isoformat(),
            }
            if budget.exhausted:
                window_record["status"] = "SKIPPED_BUDGET"
                window_record["statement"] = (
                    "global time budget exhausted before this window started; not attempted. "
                    "This says nothing about availability."
                )
                report["windows"].append(window_record)
                continue
            dataset_dir = _dataset_dir(args.dataset_root, actual_symbol, days, end_utc)
            window_record["dataset_dir"] = str(dataset_dir)
            manifest_path = dataset_dir / "manifest.json"
            if manifest_path.exists():
                prior = json.loads(manifest_path.read_text(encoding="utf-8"))
                if args.force:
                    if prior.get("schema") != "qts.mt5_raw_tick_acquisition.v1":
                        window_record["status"] = "REFUSED_UNKNOWN_DATASET_DIR"
                        window_record["statement"] = (
                            "--force refuses to delete a directory that is not a QTS raw tick acquisition"
                        )
                        report["windows"].append(window_record)
                        continue
                    shutil.rmtree(dataset_dir)
                elif prior.get("status") in {STATUS_COMPLETE, STATUS_EMPTY_COMPLETE}:
                    window_record["status"] = "REUSED_EXISTING_COMPLETE"
                    window_record["manifest_summary"] = _manifest_summary(prior)
                    report["windows"].append(window_record)
                    continue
                # resumable partial: fall through and resume it
            t0 = time.monotonic()
            caps = [b for b in (
                (budget.deadline - time.monotonic()) if budget.deadline else None,
                (args.max_window_runtime_minutes * 60.0) if args.max_window_runtime_minutes else None,
            ) if b is not None]
            per_window_budget = _TimeBudget(min(caps) if caps else None)
            manifest = acquire_window(
                mt5,
                symbol_requested=args.symbol,
                symbol_actual=actual_symbol,
                environment=report["environment"],
                start_utc=start_utc,
                end_utc=end_utc,
                dataset_dir=dataset_dir,
                flags=flags,
                chunk=timedelta(hours=args.chunk_hours),
                min_chunk=timedelta(minutes=args.min_chunk_minutes),
                max_chunk_rows=args.max_chunk_rows,
                max_runtime_seconds=None,
                budget=per_window_budget,
            )
            window_record["status"] = manifest["status"]
            window_record["runtime_seconds"] = round(time.monotonic() - t0, 3)
            window_record["manifest_summary"] = _manifest_summary(manifest)
            report["windows"].append(window_record)
            _write_json(args.evidence, report)  # durable evidence after every window

        # ---- deferred analysis stage: AFTER the ladder stopped, local files only ----
        if not args.no_analyze:
            for window_record in report["windows"]:
                dataset_dir = window_record.get("dataset_dir")
                status = window_record.get("status")
                if not dataset_dir or status not in {
                    STATUS_COMPLETE,
                    STATUS_EMPTY_COMPLETE,
                    STATUS_PARTIAL_INTERRUPTED,
                    STATUS_PARTIAL_QUERY_ERROR,
                    "REUSED_EXISTING_COMPLETE",
                }:
                    window_record["analysis"] = "NOT_RUN (no acquired dataset to analyze)"
                    continue
                symbol_token = "".join(ch if ch.isalnum() or ch in "-." else "_" for ch in actual_symbol)
                analysis_path = (
                    Path("data/evidence")
                    / "mt5_history_analysis"
                    / f"{symbol_token}_{window_record['window_days']}d.json"
                )
                analysis = analyze_dataset(dataset_dir)
                _write_json(analysis_path, analysis)
                content = analysis.get("content", {})
                window_record["analysis"] = "PASS" if analysis["provenance_validation"]["overall"] == "PASS" else "FAIL"
                window_record["analysis_report"] = str(analysis_path)
                window_record["analysis_summary"] = {
                    "row_count": content.get("row_count"),
                    "raw_time_msc_min": content.get("raw_time_msc_min"),
                    "raw_time_msc_max": content.get("raw_time_msc_max"),
                    "non_monotonic_time_msc_count": content.get("non_monotonic_time_msc_count"),
                    "spread_bps_p95": (content.get("spread_bps") or {}).get("p95_bps"),
                    "provenance_validation": analysis["provenance_validation"]["overall"],
                }
                report["analyses"][f"{window_record['window_days']}d"] = str(analysis_path)
                _write_json(args.evidence, report)

        report["boundary_assessment"] = _boundary_assessment(report["windows"])
        complete = [w for w in report["windows"] if w.get("status") in {STATUS_COMPLETE, "REUSED_EXISTING_COMPLETE"}]
        report["status"] = (
            "ACQUISITION_LADDER_COMPLETE"
            if not any(w.get("status") == "SKIPPED_BUDGET" for w in report["windows"])
            else "ACQUISITION_LADDER_PARTIAL_BUDGET"
        )
        report["result_summary"] = {
            "largest_complete_window_days": max((w["window_days"] for w in complete), default=None),
            "complete_windows_days": [w["window_days"] for w in complete],
            "windows_with_any_rows": [
                w["window_days"]
                for w in report["windows"]
                if (w.get("manifest_summary") or {}).get("row_count")
            ],
        }
        _write_json(args.evidence, report)
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0
    finally:
        mt5.shutdown()


def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": manifest.get("status"),
        "row_count": manifest.get("row_count"),
        "raw_time_msc_min": manifest.get("raw_time_msc_min"),
        "raw_time_msc_max": manifest.get("raw_time_msc_max"),
        "raw_time_min": manifest.get("raw_time_min"),
        "raw_time_max": manifest.get("raw_time_max"),
        "chunks_committed": manifest.get("chunks_committed"),
        "chunks_failed": manifest.get("chunks_failed"),
        "returned_fields": manifest.get("returned_fields"),
        "returned_dtype_map": manifest.get("returned_dtype_map"),
        "dataset_sha256": manifest.get("dataset_sha256"),
        "dataset_files_size_bytes": manifest.get("dataset_files_size_bytes"),
        "timestamp_interpretation_confirmed": manifest.get("timestamp_interpretation_confirmed"),
        "acquisition_started_at_utc": manifest.get("acquisition_started_at_utc"),
        "acquisition_ended_at_utc": manifest.get("acquisition_ended_at_utc"),
        "resumed_from_previous_run": manifest.get("resumed_from_previous_run"),
        "mt5_error_last": manifest.get("mt5_error_last"),
    }


def _boundary_assessment(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """State the historical boundary honestly: facts first, no retention guesses."""
    complete_days = [
        w["window_days"] for w in windows if w.get("status") in {STATUS_COMPLETE, "REUSED_EXISTING_COMPLETE"}
    ]
    partial = [w for w in windows if w.get("status") in {STATUS_PARTIAL_QUERY_ERROR, STATUS_PARTIAL_INTERRUPTED}]
    skipped = [w for w in windows if w.get("status") == "SKIPPED_BUDGET"]
    failed_chunks: list[dict[str, Any]] = []
    for w in partial:
        summary = w.get("manifest_summary") or {}
        # failed chunks are in the dataset manifest, not the summary; record window-level fact only
        failed_chunks.append({"window_days": w["window_days"], "chunks_failed": summary.get("chunks_failed")})
    statement = (
        "A failed or partial window does NOT by itself prove a retention limit: query errors, terminal "
        "limits, interruptions and true data absence are recorded as distinct statuses. The largest "
        "COMPLETE window and the earliest non-empty raw timestamp are facts; anything deeper is "
        "UNKNOWN_BOUNDARY"
    )
    return {
        "largest_complete_window_days": max(complete_days, default=None),
        "complete_windows_days": sorted(complete_days),
        "partial_window_facts": failed_chunks,
        "skipped_window_days": [w["window_days"] for w in skipped],
        "retention_limit_classification": "UNKNOWN_BOUNDARY unless every chunk of a window returned success "
        "with empty old chunks and non-empty recent chunks (recorded per part in the dataset)",
        "statement": statement,
    }


if __name__ == "__main__":
    raise SystemExit(main())
