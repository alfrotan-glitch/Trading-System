"""Build the 51-year daily gold store and its macro conditioning series.

Why this exists: the M15 study had 17.8 years of DEV data, which put the
detection floor at Sharpe 0.59 — too high to see a realistically sized edge. A
longer history is the only honest way to gain power that does not come from
weakening the acceptance criteria.

Sources, each pinned and hashed:

* **Gold** — FRED ``GOLDAMGBD228NLBM``, the LBMA Gold Price AM fix, 1969-01-02 to
  2019-12-31 (13,305 observations). This is a *benchmark fixing*, not a
  continuously tradable quote: you cannot fill at the fix without being a fixing
  member. It is used to measure whether an effect exists, not to claim an
  executable price, and every result must survive the assumed bps cost anyway.
* **GS10** — 10-year Treasury constant-maturity yield, monthly, 1953-04 onward.
* **CPIAUCSL** — CPI-U all items, monthly, 1947-01 onward.

The real yield is built as ``GS10 - CPI_YoY``. It is a *proxy* for the true TIPS
real yield (which only exists from 2003), because TIPS did not exist before 1997.
The proxy is standard in the literature and is ex-post by construction: it uses
realised inflation, which a trader would not have had. It is therefore shifted
**two months** — one to respect the CPI release lag, one to keep it strictly
conservative. The honest description is "realised real yield, lagged", and it can
only understate a real-time signal, never overstate one.

Free of look-ahead by construction: the gold series is indexed by fixing date, and
every macro value attached to a bar was published strictly before that bar.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

RAW = Path("data/raw/longgold")
OUT = Path("data/research/longgold")
MANIFEST = OUT / "provenance.json"

GOLD_CSV = RAW / "gold" / "GOLDAMGBD228NLBM_1969-2020.csv"
GS10_CSV = RAW / "gs10" / "GS10.csv"
CPI_CSV = RAW / "cpi" / "CPIAUCSL.csv"

#: Conservative macro release lag, in months. See module docstring.
MACRO_LAG_MONTHS = 2


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_gold() -> pd.Series:
    """Daily LBMA AM fix. FRED uses '.' for missing observations."""
    df = pd.read_csv(GOLD_CSV, na_values=["."])
    if list(df.columns) != ["DATE", "GOLDAMGBD228NLBM"]:
        raise SystemExit(f"unexpected gold columns: {list(df.columns)}")
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df["GOLDAMGBD228NLBM"] = pd.to_numeric(df["GOLDAMGBD228NLBM"], errors="coerce")
    df = df.dropna().sort_values("DATE")
    dupes = int(df["DATE"].duplicated().sum())
    if dupes:
        raise SystemExit(f"{dupes} duplicated gold dates — refusing to build")
    s = df.set_index("DATE")["GOLDAMGBD228NLBM"].astype(float)
    if (s <= 0).any():
        raise SystemExit("non-positive gold price present")
    jumps = s.pct_change().abs()
    # Gold has never moved >25% in a day on the fix; a larger jump is a splice error.
    if float(jumps.max()) > 0.25:
        raise SystemExit(f"implausible daily gold move {jumps.max():.1%} on {jumps.idxmax().date()}")
    return s


def load_monthly(path: Path, column: str) -> pd.Series:
    df = pd.read_csv(path, na_values=["."])
    if list(df.columns) != ["DATE", column]:
        raise SystemExit(f"unexpected columns in {path}: {list(df.columns)}")
    df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
    df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna().sort_values("DATE")
    if df["DATE"].duplicated().any():
        raise SystemExit(f"duplicated monthly dates in {path}")
    return df.set_index("DATE")[column].astype(float)


def build_macro() -> pd.DataFrame:
    """Monthly real-yield proxy and CPI year-on-year, release-lagged."""
    gs10 = load_monthly(GS10_CSV, "GS10")
    cpi = load_monthly(CPI_CSV, "CPIAUCSL")
    cpi_yoy = (cpi / cpi.shift(12) - 1.0) * 100.0

    idx = gs10.index.intersection(cpi_yoy.index)
    macro = pd.DataFrame({"gs10": gs10.reindex(idx), "cpi_yoy": cpi_yoy.reindex(idx)})
    macro = macro.dropna()
    macro["real_yield"] = macro["gs10"] - macro["cpi_yoy"]

    # Shift the index forward so a value is only visible after publication.
    macro.index = macro.index + pd.DateOffset(months=MACRO_LAG_MONTHS)
    return macro


def attach_macro(gold: pd.Series, macro: pd.DataFrame) -> pd.DataFrame:
    """Gold OHLC (single fixing price) with lagged macro columns, daily."""
    frames = [macro["real_yield"], macro["cpi_yoy"], macro["gs10"]]
    aligned = []
    for s in frames:
        step = s.reindex(s.index.union(gold.index)).ffill().reindex(gold.index)
        aligned.append(step)
    df = pd.DataFrame(
        {
            "open": gold,
            "high": gold,
            "low": gold,
            "close": gold,
            "volume": 0.0,
            "real_yield": aligned[0],
            "cpi_yoy": aligned[1],
            "gs10": aligned[2],
        },
        index=gold.index,
    )
    # Warm-up: a signal needs 12 months of real yield and a 12-month CPI change.
    return df.dropna(subset=["real_yield"])


def main() -> None:
    gold = load_gold()
    macro = build_macro()
    bars = attach_macro(gold, macro)

    OUT.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(OUT / "xauusd_d1_lbma.parquet")

    years = (bars.index.max() - bars.index.min()).days / 365.25
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "bars": int(len(bars)),
        "span": [str(bars.index.min().date()), str(bars.index.max().date())],
        "years": round(years, 1),
        "macro_lag_months": MACRO_LAG_MONTHS,
        "sources": {
            "gold": {
                "series": "FRED GOLDAMGBD228NLBM — LBMA Gold Price AM fix, USD/oz",
                "file": str(GOLD_CSV),
                "sha256": _sha256(GOLD_CSV),
                "note": "Benchmark fixing, not an executable quote.",
            },
            "gs10": {
                "series": "FRED GS10 — 10-Year Treasury constant maturity, monthly",
                "file": str(GS10_CSV),
                "sha256": _sha256(GS10_CSV),
            },
            "cpi": {
                "series": "FRED CPIAUCSL — CPI-U all items, SA, monthly",
                "file": str(CPI_CSV),
                "sha256": _sha256(CPI_CSV),
            },
        },
        "construction": (
            "real_yield = GS10 - CPI_YoY, then index shifted +2 months. Ex-post "
            "realised real yield, deliberately lagged; can understate a real-time "
            "signal but cannot create one."
        ),
        "cost_note": "All trading costs are ASSUMED (bps), never measured.",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
