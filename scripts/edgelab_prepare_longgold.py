"""Build the 51-year daily gold store and its macro conditioning series.

Why this exists: the M15 study had 17.8 years of DEV data, which put the
detection floor at Sharpe 0.59 — too high to see a realistically sized edge. A
longer history is the only honest way to gain power that does not come from
weakening the acceptance criteria.

Sources, each pinned and hashed:

* **Gold** — the LBMA Gold Price AM fix (10:30 London), from
  ``data/raw/longgold/metals/AU.csv``: 1968-01-02 to 2024-05-17. This is a
  *benchmark fixing*, not a continuously tradable quote: you cannot fill at the fix
  without being a fixing member. It is used to measure whether an effect exists,
  not to claim an executable price, and every result must survive the assumed bps
  cost anyway. The file is **truncated at 2019-12-31** on purpose: the 2020-2024
  window is a spent holdout and must not be reachable through ``load_long_gold``.
* **GS10** — 10-year Treasury constant-maturity yield, monthly, from
  ``data/raw/longgold/fred/treasury_10y.csv``.
* **CPI** — CPI-U all items, monthly, from ``data/raw/longgold/fred/cpi.csv``.

An earlier version of this script read a FRED mirror layout that no longer exists
in the tree, which made the 51-year store unbuildable and every round-3 result
unreproducible. It now reads the files that are actually present, and fails loudly
if they are not.

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

GOLD_CSV = RAW / "metals" / "AU.csv"
GS10_CSV = RAW / "fred" / "treasury_10y.csv"
CPI_CSV = RAW / "fred" / "cpi.csv"

#: The held-out window is deliberately excluded from the export.
LAST_BUILD_DATE = "2019-12-31"

#: Conservative macro release lag, in months. See module docstring.
MACRO_LAG_MONTHS = 2


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_two_col(path: Path) -> pd.DataFrame:
    """Read a two-column ``date,value`` CSV, tolerating upper-case headers."""
    df = pd.read_csv(path, na_values=["."])
    if len(df.columns) != 2:
        raise SystemExit(f"expected 2 columns in {path}, got {list(df.columns)}")
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().sort_values("date")


def load_gold() -> pd.Series:
    """Daily LBMA AM fix, truncated before the spent holdout window."""
    if not GOLD_CSV.exists():
        raise SystemExit(f"{GOLD_CSV} missing — cannot build the long history")
    df = _read_two_col(GOLD_CSV)
    df = df[df["date"] <= pd.Timestamp(LAST_BUILD_DATE)]
    dupes = int(df["date"].duplicated().sum())
    if dupes:
        raise SystemExit(f"{dupes} duplicated gold dates — refusing to build")
    s = df.set_index("date")["value"].astype(float)
    if (s <= 0).any():
        raise SystemExit("non-positive gold price present")
    jumps = s.pct_change().abs()
    # Gold has never moved >25% in a day on the fix; a larger jump is a splice error.
    if float(jumps.max()) > 0.25:
        raise SystemExit(f"implausible daily gold move {jumps.max():.1%} on {jumps.idxmax().date()}")
    return s


def load_monthly(path: Path) -> pd.Series:
    if not path.exists():
        raise SystemExit(f"{path} missing — cannot build the long history")
    df = _read_two_col(path)
    if df["date"].duplicated().any():
        raise SystemExit(f"duplicated monthly dates in {path}")
    return df.set_index("date")["value"].astype(float)


def build_macro() -> pd.DataFrame:
    """Monthly real-yield proxy and CPI year-on-year, release-lagged."""
    gs10 = load_monthly(GS10_CSV)
    cpi = load_monthly(CPI_CSV)
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
                "series": "LBMA Gold Price AM fix (10:30 London), USD/oz",
                "file": str(GOLD_CSV),
                "sha256": _sha256(GOLD_CSV),
                "note": "Benchmark fixing, not an executable quote.",
            },
            "gs10": {
                "series": "10-Year Treasury constant maturity, monthly",
                "file": str(GS10_CSV),
                "sha256": _sha256(GS10_CSV),
            },
            "cpi": {
                "series": "CPI-U all items, SA, monthly",
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
