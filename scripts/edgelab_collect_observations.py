"""Collect genuinely new forward observations for active candidates.

The forward ledger was empty for a defensible reason — nothing in hand was newer
than the candidate's freeze — but an empty ledger is not a plan. This script is the
plan made executable:

1. **Fetch.** Pull the FRED mirror and the Dukascopy replay feed from GitHub at
   their current HEAD. Only ``codeload.github.com`` is reachable here, so the
   tarball path is used rather than the API.
2. **Build a tradable price series.** Gold is measured on **24-hour UTC M15
   closes**, not the LBMA AM fix, because DXY and the 10-year yield settle around
   22:00 UTC — a 24:00 close is the first price struck after the inputs exist.
   This is the correction that came out of the XL-001 audit.
3. **Plan, don't assume.** ``collect.plan_observations`` decides which dates are
   legitimately forward: strictly after the registration date, with a complete and
   fresh set of drivers, and not already recorded.
4. **Record.** Entries go into the append-only ledger. Re-running is idempotent;
   a conflicting re-log raises rather than rewriting history.

If no active candidate exists, the script says so and writes nothing.
No network download is needed when there is no eligible rule. If a candidate
is ever promoted into the forward *research* queue, the script may prepare a
dry-run plan but will not claim external historical replay is authenticated
broker evidence or silently backfill observations after their outcomes occurred.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from qts.research.edgelab import forward
from qts.research.edgelab.candidates import DRIVERS, active_candidates, candidates
from qts.research.edgelab.collect import align_drivers, complete_dates, plan_observations, staleness
from qts.research.edgelab.fred_drivers import load_broad_dollar, load_treasury_10y
from qts.research.edgelab.intraday import daily_bars

FRED_REPO = "sgdividends/fred-macro-data"
DUKA_REPO = "vudo805/forex-price-simulator"
FRED_FILES = {
    "treasury_10y.csv": "treasury_10y",
    "treasury_10y_real.csv": "treasury_10y_real",
    "broad_dollar.csv": "broad_dollar",
}
FRED_DIR = Path("data/raw/longgold/fred")
DUKA_DIR = Path("data/research/xauusd_m15_vudo.parquet")
REPORT = Path("data/research/forward_collection_report.json")


def _download(url: str, timeout: int = 300) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "qts-research"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed GitHub URL
        return r.read()


def refresh_fred(verbose: bool = True) -> dict:
    """Re-download the FRED mirror and report per-series coverage."""
    blob = _download(f"https://codeload.github.com/{FRED_REPO}/tar.gz/HEAD")
    out = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for member in tf.getmembers():
            name = Path(member.name).name
            if name in FRED_FILES and "/data/fred/" in member.name:
                data = tf.extractfile(member)
                if data is None:
                    continue
                FRED_DIR.mkdir(parents=True, exist_ok=True)
                (FRED_DIR / name).write_bytes(data.read())
                s = pd.read_csv(FRED_DIR / name, parse_dates=["date"]).set_index("date")["value"]
                out[FRED_FILES[name]] = {"last": str(s.index.max().date()), "rows": int(len(s))}
                if verbose:
                    print(f"  {name:24s} -> {s.index.max().date()}  ({len(s)} rows)")
    if not out:
        raise RuntimeError("FRED mirror contained none of the expected files")
    return out


def refresh_gold(verbose: bool = True) -> dict:
    """Re-download the Dukascopy-derived M15 series and rebuild the parquet."""
    blob = _download(f"https://codeload.github.com/{DUKA_REPO}/tar.gz/HEAD")
    frames = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for member in tf.getmembers():
            if "/data/XAUUSD/" in member.name and member.name.endswith(".parquet"):
                data = tf.extractfile(member)
                if data is None:
                    continue
                frames.append(pd.read_parquet(io.BytesIO(data.read())))
    if not frames:
        raise RuntimeError("no XAUUSD parquet parts found in the replay feed")
    df = pd.concat(frames).sort_index()
    # The replay feed ships tz-naive timestamps that are UTC by construction. Losing
    # the timezone here silently breaks every downstream join, so it is restored and
    # asserted rather than assumed.
    if isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df[~df.index.duplicated(keep="first")]
    if "ticks" in df.columns:
        df = df.rename(columns={"ticks": "volume"})
    if df.index.tz is None:  # pragma: no cover - defensive
        raise RuntimeError("replay feed index is not timezone-aware")
    DUKA_DIR.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DUKA_DIR)
    info = {"rows": int(len(df)), "first": str(df.index.min()), "last": str(df.index.max())}
    if verbose:
        print(f"  XAUUSD M15 {info['first']} .. {info['last']} ({info['rows']} bars)")
    return info


def driver_frame() -> pd.DataFrame:
    """The driver columns candidatess read, on their own calendar."""
    d = pd.concat(
        [load_broad_dollar().rename("usd_broad"), load_treasury_10y().rename("y10")], axis=1, sort=True
    ).sort_index()
    if d.index.tz is None:
        d.index = d.index.tz_localize("UTC")
    d = d[~d.index.duplicated(keep="first")].dropna()
    # XL-001 names its inputs 'dxy' and 'y10'; the broad dollar is the series that
    # actually extends past 2024, and the round-8 audit showed the substitution does
    # not drive the result (alpha_t 2.69 vs 2.93 on the overlap).
    return d.rename(columns={"usd_broad": "dxy"})


def run(dry_run: bool, verbose: bool = True) -> dict:
    report: dict = {"generated_at": datetime.now(UTC).isoformat(), "dry_run": dry_run}

    active = active_candidates()
    report["active_candidates"] = [c.id for c in active]
    report["rejected_candidates"] = [{"id": c.id, "reason": c.rejected_reason} for c in candidates() if c.status == "rejected"]
    if not active:
        report["outcome"] = (
            "no active candidate: nothing can be recorded. XL-001 is rejected by the "
            "round-10 timing audit; registering a replacement now, after observing "
            "which constructions failed, would be hindsight fitting."
        )
        if verbose:
            print(f"\n{report['outcome']}")
        return report

    if verbose:
        print("=== refreshing inputs for registered research candidates")
    report["fred"] = refresh_fred(verbose)
    report["gold"] = refresh_gold(verbose)

    bars = daily_bars(pd.read_parquet(DUKA_DIR))
    bars = bars.loc["2024-06-01":]
    drivers = driver_frame()
    reg = forward.registered()
    existing = forward.load_ledger()
    report["candidates"] = {}

    for cand in active:
        cols = DRIVERS.get(cand.id)
        if not cols:
            report["candidates"][cand.id] = {"skipped": "no driver declaration"}
            continue
        raw = drivers[[c for c in drivers.columns if c in cols]]
        # Freshness is measured on the raw frame, not the filled one.
        usable = complete_dates(bars["close"], raw, bars.index)
        if len(usable) == 0:
            report["candidates"][cand.id] = {"skipped": "no complete date in the new data"}
            continue

        # The signal must be computed on the full driver history, then sampled —
        # computing it inside the window would zero out the 126-bar warm-up.
        full_index = pd.DatetimeIndex(raw.index.union(bars.index)).sort_values()
        sig = cand.signal(align_drivers(raw, full_index)).reindex(usable)

        frozen = reg.get(cand.id)
        if not frozen or frozen.get("definition_hash") != cand.definition_hash():
            report["candidates"][cand.id] = {
                "skipped": "candidate was never frozen, or definition hash changed"
            }
            continue
        reg_date = pd.Timestamp(frozen["registered_at"]).date()
        have = set(existing.loc[existing["candidate_id"] == cand.id, "date"].dt.date) if not existing.empty else set()
        plan = plan_observations(cand.id, reg_date, bars.loc[usable], sig, "m15_utc_close", have)

        warn = staleness(usable[-1].date(), drivers.index.max().date())
        entry = {
            "registered_on": reg_date.isoformat(),
            "usable_dates": len(usable),
            "planned": len(plan.observations),
            "reason": plan.reason,
            "staleness": warn,
        }
        if plan.empty and verbose:
            print(f"\n  {cand.id}: {plan.reason}")

        if not dry_run:
            # This public GitHub replay has no cryptographically attributable
            # MT5 broker-completed-bar/quote identity or true publication audit.
            # Writing a "forward" evidence entry from it would misstate both
            # provenance and chronology. Keep its plan for research inspection
            # and gather actual authenticated DEMO ticks through the in-app
            # OBSERVE-ONLY collector instead. The latter never places an order.
            entry["written"] = 0
            entry["blocked"] = (
                "historical replay is not verified broker forward evidence; "
                "use the in-app MT5 OBSERVE-ONLY collector"
            )
        report["candidates"][cand.id] = entry

    return report


def _git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    except OSError:  # pragma: no cover
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="plan but do not write")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    print(f"forward collection at {datetime.now(UTC).isoformat()} (rev {_git_rev()})")
    report = run(dry_run=args.dry_run, verbose=not args.quiet)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nreport: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
