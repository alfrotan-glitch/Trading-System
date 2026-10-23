"""Run the preregistered fixed quote-only ML assay on local MT5 ticks."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from qts.data.mt5_history_acquisition import MANIFEST_FILENAME
from qts.data.mt5_timestamp_basis import timestamp_basis_assessment
from qts.research.xauusd_broker_ml import BrokerBars, evaluate_broker_ml
from qts.research.xauusd_tick_discovery import discovery_cutoff


@dataclass
class _BarBuilder:
    times: list[int] = field(default_factory=list)
    open_bid: list[float] = field(default_factory=list)
    open_ask: list[float] = field(default_factory=list)
    high_mid: list[float] = field(default_factory=list)
    low_mid: list[float] = field(default_factory=list)
    close_bid: list[float] = field(default_factory=list)
    close_ask: list[float] = field(default_factory=list)
    mean_spread: list[float] = field(default_factory=list)
    _minute: int | None = None
    _open_bid: float = 0.0
    _open_ask: float = 0.0
    _high_mid: float = 0.0
    _low_mid: float = 0.0
    _close_bid: float = 0.0
    _close_ask: float = 0.0
    _spread_sum: float = 0.0
    _count: int = 0

    def _start(self, minute: int, bid: np.ndarray, ask: np.ndarray) -> None:
        mid = (bid + ask) / 2.0
        self._minute = minute
        self._open_bid = float(bid[0])
        self._open_ask = float(ask[0])
        self._high_mid = float(mid.max())
        self._low_mid = float(mid.min())
        self._close_bid = float(bid[-1])
        self._close_ask = float(ask[-1])
        self._spread_sum = float((ask - bid).sum())
        self._count = len(bid)

    def _finish(self) -> None:
        if self._minute is None or self._count == 0:
            return
        self.times.append(self._minute * 60_000)
        self.open_bid.append(self._open_bid)
        self.open_ask.append(self._open_ask)
        self.high_mid.append(self._high_mid)
        self.low_mid.append(self._low_mid)
        self.close_bid.append(self._close_bid)
        self.close_ask.append(self._close_ask)
        self.mean_spread.append(self._spread_sum / self._count)

    def consume(self, minute: int, bid: np.ndarray, ask: np.ndarray) -> None:
        if self._minute is None:
            self._start(minute, bid, ask)
            return
        if minute == self._minute:
            mid = (bid + ask) / 2.0
            self._high_mid = max(self._high_mid, float(mid.max()))
            self._low_mid = min(self._low_mid, float(mid.min()))
            self._close_bid = float(bid[-1])
            self._close_ask = float(ask[-1])
            self._spread_sum += float((ask - bid).sum())
            self._count += len(bid)
            return
        self._finish()
        self._start(minute, bid, ask)

    def finish(self) -> BrokerBars:
        self._finish()
        return BrokerBars(
            time_msc=np.asarray(self.times, dtype=np.int64),
            open_bid=np.asarray(self.open_bid, dtype=np.float64),
            open_ask=np.asarray(self.open_ask, dtype=np.float64),
            high_mid=np.asarray(self.high_mid, dtype=np.float64),
            low_mid=np.asarray(self.low_mid, dtype=np.float64),
            close_bid=np.asarray(self.close_bid, dtype=np.float64),
            close_ask=np.asarray(self.close_ask, dtype=np.float64),
            mean_spread=np.asarray(self.mean_spread, dtype=np.float64),
        )


def _read_bars(dataset_dir: Path, parts: list[dict[str, Any]]) -> BrokerBars:
    builder = _BarBuilder()
    for part in parts:
        parquet = pq.ParquetFile(dataset_dir / "parts" / part["part"])
        for batch in parquet.iter_batches(batch_size=500_000, columns=["time_msc", "bid", "ask"]):
            stamp = np.asarray(batch.column("time_msc").to_numpy(zero_copy_only=False), dtype=np.int64)
            bid = np.asarray(batch.column("bid").to_numpy(zero_copy_only=False), dtype=np.float64)
            ask = np.asarray(batch.column("ask").to_numpy(zero_copy_only=False), dtype=np.float64)
            if not (np.isfinite(stamp).all() and np.isfinite(bid).all() and np.isfinite(ask).all()):
                raise ValueError("raw broker ledger contains non-finite quote fields")
            if np.any((bid <= 0.0) | (ask < bid)):
                raise ValueError("raw broker ledger contains invalid bid/ask ordering")
            minutes = stamp // 60_000
            starts = np.concatenate(([0], np.flatnonzero(minutes[1:] != minutes[:-1]) + 1))
            ends = np.concatenate((starts[1:], [len(minutes)]))
            for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
                builder.consume(int(minutes[start]), bid[start:end], ask[start:end])
    bars = builder.finish()
    if len(bars.time_msc) < 100:
        raise ValueError("insufficient one-minute bars")
    return bars


def run(dataset_dir: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads((dataset_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    parts = manifest.get("parts") or []
    bars = _read_bars(dataset_dir, parts)
    time_min, time_max = int(bars.time_msc.min()), int(bars.time_msc.max())
    cutoff = discovery_cutoff(time_min, time_max)
    result = evaluate_broker_ml(bars, cutoff_time_msc=cutoff, time_min=time_min, time_max=time_max)
    result["dataset"] = {
        "manifest_dataset_sha256": manifest.get("dataset_sha256"),
        "raw_row_count": manifest.get("row_count"),
        "one_minute_bar_count": len(bars.time_msc),
        "discovery_cutoff_time_msc": cutoff,
    }
    result["timestamp_basis"] = timestamp_basis_assessment(manifest, evidence)
    result.pop("_discovery_times", None)
    if result["timestamp_basis"].get("status") not in {"CONFIRMED", "MEASURED_SAME_SESSION"}:
        result["decision"] = "INCONCLUSIVE"
        result["edge_claim"] = "NOT ESTABLISHED"
        result["strategy_promoted"] = False
        result.setdefault("integrity", {})["blocked_reason"] = "timestamp basis not confirmed"
    return result


def _render(result: dict[str, Any]) -> str:
    holdout = result.get("holdout", {})
    stress = holdout.get("costs", {}).get("2.0", {})
    return "\n".join(
        [
            "# XAUUSD fixed quote-only ML assay",
            "",
            f"Decision: {result.get('decision')}",
            f"Timestamp basis: {result.get('timestamp_basis', {}).get('status')}",
            f"One-minute bars: {result.get('dataset', {}).get('one_minute_bar_count')}",
            f"Holdout trades: {holdout.get('n')}",
            f"Holdout mean net bps at 2 bps extra stress: {stress.get('mean_net_bps')}",
            f"Holdout bootstrap lower bound: {(stress.get('bootstrap') or {}).get('lo')}",
            "",
            "No candidate was promoted. LIVE is locked and order submission is disabled.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run fixed quote-only ML on local MT5 XAUUSD data")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--timestamp-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = json.loads(args.timestamp_evidence.read_text(encoding="utf-8"))
    result = run(args.dataset_dir, evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(_render(result), encoding="utf-8")
    print(json.dumps({"decision": result["decision"], "holdout_n": result["holdout"].get("n")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
