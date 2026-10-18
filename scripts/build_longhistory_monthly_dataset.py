#!/usr/bin/env python3
"""Build the monthly long-history XAUUSD research series and its quality evidence.

Inputs (pinned, fetched separately; both datahub mirror repositories on GitHub):

  * ``data/raw/gold_monthly/data/monthly.csv``      — World Bank monthly gold
    (USD/oz) via ``datasets/gold-prices`` (pinned commit + SHA-256 below);
  * ``data/raw/fx/data/daily.csv``                  — Federal Reserve H.10 daily
    FX quotes via ``datasets/exchange-rates`` (pinned commit + SHA-256 below);
  * the already-built BaseMax research 15-minute file (for the monthly source
    replication, built by ``scripts/build_longhistory_dataset.py``).

Outputs:

  * ``data/raw/longhistory/processed/xauusd_worldbank_monthly_utc_197301_202609.csv``
  * ``data/raw/longhistory/processed/xauusd_basemax_monthly_utc_200406_202502.csv``
    (both gitignored — no price data is committed);
  * ``data/evidence/longhistory/monthly_data_quality.json`` (committed, no
    prices): pinned SHAs, row counts, gap checks, the empirical USD-index
    quote-convention probes, and cross-source month overlap statistics.

Execution convention documented here and frozen in the preregistration: the
World Bank series provides one monthly average price per month, so the research
bar is ``open = high = low = close = monthly average``. The engine fills a plan
written at month ``t`` at the open of month ``t+1``, i.e. at month ``t+1``'s
average — a uniform-across-the-month (TWAP) execution at the published average.
No price is ever invented, interpolated or smoothed; a missing month fails the
build instead of being filled.

Every step is deterministic.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qts.research.longhistory import sources as S  # noqa: E402

RAW = REPO_ROOT / "data" / "raw"
GOLD_CSV = RAW / "gold_monthly" / "data" / "monthly.csv"
FX_CSV = RAW / "fx" / "data" / "daily.csv"
PROCESSED = RAW / "longhistory" / "processed"
BASEMAX_15M = PROCESSED / "xauusd_basemax_utc_15m_20040611_20250228.csv"
OUT_GOLD = PROCESSED / "xauusd_worldbank_monthly_utc_197301_202609.csv"
OUT_REPL = PROCESSED / "xauusd_basemax_monthly_utc_200406_202502.csv"
EVIDENCE = REPO_ROOT / "data" / "evidence" / "longhistory" / "monthly_data_quality.json"

GOLD_REPO = "https://github.com/datasets/gold-prices"
GOLD_COMMIT = "f6e97610178379ef8db280702fcaa3ec0875c5c2"
FX_REPO = "https://github.com/datasets/exchange-rates"
FX_COMMIT = "c023dd8b8f879610641a7391c0394c3bbb42d0f7"

#: Fixed equal-weight basket for the USD strength index. Every series in this
#: extract is quoted as *currency per USD*; the convention is verified below
#: against probe dates before any index is built (the datahub README's claim
#: about USD/currency quotes for three countries does not match the data).
BASKET = (
    "Australia",
    "Canada",
    "Denmark",
    "Japan",
    "New Zealand",
    "Sweden",
    "Switzerland",
    "United Kingdom",
)

#: Empirical quote-convention probes: under the currency-per-USD reading each
#: series must land in these ranges at both probe dates. Ranges are tight
#: enough that the USD-per-currency reading (inverted values) fails them.
QUOTE_PROBES: dict[str, dict[str, tuple[float, float]]] = {
    # date -> country -> (lo, hi)
    "1985-03-01": {
        "Australia": (1.0, 2.0),
        "Canada": (1.2, 1.6),
        "Denmark": (8.0, 16.0),
        "Japan": (200.0, 300.0),
        "New Zealand": (1.8, 3.0),
        "Sweden": (8.0, 12.0),
        "Switzerland": (2.0, 4.0),
        "United Kingdom": (0.7, 1.2),
    },
    "2024-01-02": {
        "Australia": (1.2, 1.8),
        "Canada": (1.2, 1.5),
        "Denmark": (6.0, 8.0),
        "Japan": (120.0, 160.0),
        "New Zealand": (1.4, 1.9),
        "Sweden": (9.0, 12.0),
        "Switzerland": (0.8, 1.3),
        "United Kingdom": (0.7, 0.9),
    },
}

START = pd.Timestamp("1973-01-01")
END = pd.Timestamp("2026-09-30")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"monthly dataset build failed: {msg}")


def load_gold() -> pd.DataFrame:
    _require(GOLD_CSV.is_file(), f"missing {GOLD_CSV}; fetch the pinned sources first")
    raw = pd.read_csv(GOLD_CSV)
    _require(list(raw.columns) == ["Date", "Price"], "unexpected gold CSV schema")
    frame = raw.copy()
    frame["date"] = pd.to_datetime(frame["Date"]) + pd.offsets.MonthEnd(0)
    frame = frame.set_index("date")[["Price"]].astype(float)
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame = frame.loc[START:END]
    expected = pd.date_range(START, END, freq="ME")
    got = pd.DatetimeIndex(frame.index)
    missing = expected.difference(got)
    extra = got.difference(expected)
    _require(len(missing) == 0, f"gold months missing: {[str(m.date()) for m in missing[:5]]}")
    _require(len(extra) == 0, f"unexpected gold months: {[str(m.date()) for m in extra[:5]]}")
    _require(bool((frame["Price"] > 0).all()) and bool(np.isfinite(frame["Price"]).all()),
             "gold prices must be finite and positive")
    return frame


def quote_probes(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for date, checks in QUOTE_PROBES.items():
        probe = pd.Timestamp(date)
        for country, (lo, hi) in checks.items():
            series = daily[(daily["Country"] == country) & (daily["date"] <= probe)]
            _require(not series.empty, f"no FX observation for {country} on/before {date}")
            value = float(series.iloc[-1]["Exchange rate"])
            stamp = str(series.iloc[-1]["date"].date())
            _require(
                lo <= value <= hi,
                f"quote-convention probe failed for {country} at {date}: {value} not in [{lo}, {hi}] "
                "(series must be quoted currency-per-USD)",
            )
            rows.append(
                {"country": country, "probe_date": date, "observation_date": stamp,
                 "value": value, "accepted_range": [lo, hi], "reading": "currency_per_usd"}
            )
    return rows


def usd_index_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Equal-weight geometric USD index from the fixed basket, monthly.

    For each series, ``log(v_t / v_base)`` with ``v_base`` the first valid
    observation of that series; the daily cross-basket mean is exponentiated
    and the last daily value of each calendar month is the monthly point.
    """
    frame = daily[daily["Country"].isin(BASKET)].copy()
    frame["v"] = frame["Exchange rate"].astype(float)
    frame = frame.dropna(subset=["v"]).sort_values(["Country", "date"])
    _require(bool((frame["v"] > 0).all()), "FX rates must be positive")
    frame["base"] = frame.groupby("Country")["v"].transform("first")
    frame["logret"] = np.log(frame["v"] / frame["base"])
    pivot = frame.pivot_table(index="date", columns="Country", values="logret")
    coverage = pivot.notna().sum(axis=1)
    # Sparse days exist only where markets observe different holidays (six
    # single-quote days in 1971, before the research window). Require any
    # quote per day, and require the month-end observation day (the value the
    # monthly series actually uses) to carry at least six of the eight quotes.
    _require(int(coverage.min()) >= 1, "a day with zero basket quotes is in the pivot")
    last_day_of_month = pivot.groupby(pivot.index.to_period("M")).apply(lambda x: x.index[-1])
    end_coverage = coverage.reindex(last_day_of_month)
    _require(int(end_coverage.min()) >= 6,
             f"month-end coverage below 6 quotes: min={int(end_coverage.min())}")
    daily_index = np.exp(pivot.mean(axis=1))
    monthly = daily_index.groupby(daily_index.index.to_period("M")).last()
    monthly.index = monthly.index.to_timestamp("M")
    monthly.name = "usd"
    expected = pd.date_range(START, END, freq="ME")
    missing = pd.DatetimeIndex(expected).difference(pd.DatetimeIndex(monthly.index))
    # Days before the FX extract starts cannot produce months before 1971;
    # within our window every month must exist.
    missing = missing[(missing >= START) & (missing <= END)]
    _require(len(missing) == 0, f"USD index months missing: {[str(m.date()) for m in missing[:5]]}")
    # Month-end lag: the last FX observation of a month must be within 7 days
    # of the month end (holiday straddles only).
    last_obs = frame.groupby(frame["date"].dt.to_period("M"))["date"].max()
    in_window = monthly.index[(monthly.index >= START) & (monthly.index <= END)]
    lo = last_obs.reindex(in_window.to_period("M"))
    _require(bool(lo.notna().all()), "a month with FX index value lacks raw FX observations")
    lag_days = (in_window - lo).dt.days
    _require(bool((lag_days.fillna(999) <= 7).all()),
             f"FX month-end lag exceeds 7 days: {int(lag_days.max())} days")
    return monthly


def build_primary(gold: pd.DataFrame, usd: pd.Series) -> pd.DataFrame:
    frame = gold.join(usd, how="inner")
    _require(len(frame) == len(gold), "gold/USD-index join lost months")
    out = pd.DataFrame(index=frame.index)
    out["open"] = frame["Price"]
    out["high"] = frame["Price"]
    out["low"] = frame["Price"]
    out["close"] = frame["Price"]
    out["usd"] = frame["usd"]
    return out


def build_replicate(usd: pd.Series) -> tuple[pd.DataFrame, dict[str, object]]:
    _require(BASEMAX_15M.is_file(), f"missing {BASEMAX_15M}; run build_longhistory_dataset.py first")
    bars = S.read_csv_utc(BASEMAX_15M)
    grouped = bars.groupby(bars.index.to_period("M"))
    repl = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
        }
    )
    repl.index = pd.DatetimeIndex(repl.index.to_timestamp("M"))
    repl = repl.sort_index()
    repl["usd"] = usd.reindex(repl.index)
    lost = int(repl["usd"].isna().sum())
    _require(lost == 0, f"{lost} replicate months lack a USD index value")
    # Consistency: high >= max(open, close), low <= min(open, close).
    bad = (
        (repl["high"] < repl[["open", "close"]].max(axis=1))
        | (repl["low"] > repl[["open", "close"]].min(axis=1))
        | (repl["high"] < repl["low"])
        | (repl[["open", "high", "low", "close", "usd"]] <= 0).any(axis=1)
    )
    _require(not bool(bad.any()), f"inconsistent replicate OHLC in {int(bad.sum())} months")
    meta = {
        "bars_15m_source_rows": int(len(bars)),
        "months": int(len(repl)),
        "start": str(repl.index[0].date()),
        "end": str(repl.index[-1].date()),
        "months_with_less_than_60_bars": int((grouped.size() < 60).sum()),
    }
    return repl, meta


def cross_source_check(primary: pd.DataFrame, replicate: pd.DataFrame) -> dict[str, object]:
    overlap = primary.index.intersection(replicate.index)
    _require(len(overlap) >= 200, f"cross-source overlap too small: {len(overlap)} months")
    a = primary.loc[overlap, "close"].to_numpy(dtype=float)
    b = replicate.loc[overlap, "close"].to_numpy(dtype=float)
    diff = a - b
    rel = diff / b
    corr = float(np.corrcoef(a, b)[0, 1])
    _require(corr > 0.99, f"cross-source correlation too low: {corr}")
    return {
        "overlap_months": int(len(overlap)),
        "pearson_close_correlation": round(corr, 6),
        "mean_abs_rel_diff": round(float(np.mean(np.abs(rel))), 6),
        "median_abs_rel_diff": float(np.median(np.abs(rel))),
        "max_abs_rel_diff": round(float(np.max(np.abs(rel))), 6),
        "note": (
            "World Bank monthly averages (LBMA-based) versus BaseMax broker-quotes monthly bars; "
            "an information check on the overlapping calendar, not an execution-price claim."
        ),
    }


def _ensure_sources() -> None:
    """Fetch and build upstream inputs when requested on a clean clone."""
    import subprocess

    if not GOLD_CSV.is_file() or not FX_CSV.is_file():
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "fetch_longhistory_monthly_sources.py")],
            check=True,
        )
    if not BASEMAX_15M.is_file():
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "fetch_longhistory_sources.py")],
            check=True,
        )
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "build_longhistory_dataset.py")],
            check=True,
        )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ensure-sources",
        action="store_true",
        help="fetch pinned raw sources and build BaseMax 15m dataset first if missing",
    )
    args = parser.parse_args(argv)
    if args.ensure_sources:
        _ensure_sources()
    if not GOLD_CSV.is_file() or not FX_CSV.is_file():
        raise SystemExit(
            "pinned monthly sources missing; run:\n"
            "  python scripts/fetch_longhistory_monthly_sources.py\n"
            "  python scripts/fetch_longhistory_sources.py\n"
            "  python scripts/build_longhistory_dataset.py\n"
            "  python scripts/build_longhistory_monthly_dataset.py\n"
            "(or pass --ensure-sources)"
        )
    gold = load_gold()
    daily = pd.read_csv(FX_CSV)
    daily["date"] = pd.to_datetime(daily["Date"])
    probes = quote_probes(daily)
    usd = usd_index_monthly(daily)
    primary = build_primary(gold, usd)
    replicate, repl_meta = build_replicate(usd)
    xsource = cross_source_check(primary, replicate)

    PROCESSED.mkdir(parents=True, exist_ok=True)
    primary_out = primary.copy()
    primary_out.index.name = "date"
    primary_out.to_csv(OUT_GOLD, index=True, date_format="%Y-%m-%d", lineterminator="\n")
    repl_out = replicate.copy()
    repl_out.index.name = "date"
    repl_out.to_csv(OUT_REPL, index=True, date_format="%Y-%m-%d", lineterminator="\n")

    evidence = {
        "schema": "qts.longhistory.monthly_data_quality.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "execution_convention": (
            "open=high=low=close=World-Bank monthly average price; decisions at month t fill at "
            "the open of month t+1 (the month t+1 published average = uniform-across-the-month TWAP); "
            "no interpolation, no synthetic bars, missing months fail the build"
        ),
        "sources": [
            {
                "source_id": "worldbank_gold_monthly",
                "repo": GOLD_REPO,
                "commit": GOLD_COMMIT,
                "path": "data/monthly.csv",
                "sha256": sha256_file(GOLD_CSV),
                "license_note": (
                    "Repository PDDL (maintainers' statement). Modern data: World Bank Commodity "
                    "Markets (Pink Sheet), freely available; 1833-1959 historical table not used."
                ),
            },
            {
                "source_id": "fed_h10_fx_daily",
                "repo": FX_REPO,
                "commit": FX_COMMIT,
                "path": "data/daily.csv",
                "sha256": sha256_file(FX_CSV),
                "license_note": (
                    "Repository PDDL (maintainers' statement) for gathered FRED/Federal Reserve H.10 "
                    "quotes; source data are US Federal Reserve daily FX rates."
                ),
            },
            {
                "source_id": "basemax_monthly_replicate",
                "repo": "https://github.com/BaseMax/XAUUSD-LSTM",
                "commit": "43f4177e701fdf3643cc02413e4337932af57401",
                "path": "processed/xauusd_basemax_utc_15m_20040611_20250228.csv",
                "sha256": sha256_file(BASEMAX_15M),
                "license_note": "See docs/research/longhistory_data_provenance_2026-10-10.md (research-only stream).",
            },
        ],
        "quote_convention": {
            "reading": "currency-per-USD",
            "basket": list(BASKET),
            "probes": probes,
            "note": (
                "The datasets/exchange-rates README claims USD/currency quotes for Australia, "
                "Ireland, New Zealand and the United Kingdom; the actual extract values fail the "
                "currency-per-USD probes if inverted, so all basket series are used as-is. The "
                "probe table is the evidence for that decision."
            ),
        },
        "primary_series": {
            "path": OUT_GOLD.name,
            "sha256": sha256_file(OUT_GOLD),
            "months": int(len(primary)),
            "start": str(primary.index[0].date()),
            "end": str(primary.index[-1].date()),
            "missing_months": 0,
            "usd_basket_size": len(BASKET),
        },
        "replicate_series": {
            "path": OUT_REPL.name,
            "sha256": sha256_file(OUT_REPL),
            **repl_meta,
        },
        "cross_source": xsource,
        "status": "OK",
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"primary: {primary.shape[0]} months {primary.index[0].date()}..{primary.index[-1].date()}")
    print(f"replicate: {replicate.shape[0]} months {replicate.index[0].date()}..{replicate.index[-1].date()}")
    print(f"cross-source corr: {xsource['pearson_close_correlation']}")
    print(f"evidence: {EVIDENCE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
