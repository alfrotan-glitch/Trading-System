"""Build the macro conditioning series used by the Edge Lab.

Input is a pinned FRED ``DFII10`` transcription committed under
``data/raw/macro/<repo>-<sha>/``. Pinning the commit matters: a moving ``HEAD``
would make yesterday's backtest unreproducible today.

Quality checks are hard failures, not warnings. A macro series that is silently
truncated or that has a duplicated date would misalign every signal built on it,
and the resulting numbers would look perfectly plausible.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

RAW_GLOB = "data/raw/macro/*/data/raw/fred_DFII10.csv"
# Pinned so the input can be re-fetched byte-for-byte even if the repo moves.
PINNED = {
    "repository": "AsjalAbdullahButt/Gold_Forecast_Results",
    "commit": "caf4a1e012954880363e399234a8e9bad5a62237",
    "path": "data/raw/fred_DFII10.csv",
    "fetch": "https://codeload.github.com/AsjalAbdullahButt/Gold_Forecast_Results/tar.gz/caf4a1e012954880363e399234a8e9bad5a62237",
}
OUT_DIR = Path("data/research/macro")
MANIFEST = OUT_DIR / "provenance.json"


def main() -> None:
    files = sorted(Path().glob(RAW_GLOB))
    if not files:
        raise SystemExit(f"no raw DFII10 csv found under {RAW_GLOB}")
    src = files[-1]
    raw = src.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()

    df = pd.read_csv(src)
    if list(df.columns[:2]) != ["observation_date", "DFII10"]:
        raise SystemExit(f"unexpected columns: {list(df.columns)}")

    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
    df["DFII10"] = pd.to_numeric(df["DFII10"], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["observation_date", "DFII10"])
    dropped = before - len(df)
    df = df.sort_values("observation_date")
    dupes = int(df["observation_date"].duplicated().sum())
    if dupes:
        raise SystemExit(f"{dupes} duplicated observation dates — refusing to build")

    s = df.set_index("observation_date")["DFII10"].astype(float)
    jumps = s.diff().abs()
    # A 10y real yield does not move 2pp in a day; that would be a unit or splice error.
    if float(jumps.max()) > 2.0:
        raise SystemExit(f"implausible daily jump {jumps.max():.3f}pp in real yield")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    s.to_frame("dfii10").to_parquet(OUT_DIR / "dfii10_daily.parquet")

    manifest = {
        "series": "FRED DFII10 — 10-Year Treasury Inflation-Indexed Security, constant maturity",
        "source": PINNED,
        "source_file": str(src),
        "sha256": sha256,
        "rows": int(len(s)),
        "dropped_non_numeric": dropped,
        "duplicates": dupes,
        "span": [str(s.index.min().date()), str(s.index.max().date())],
        "max_abs_daily_change_pp": float(jumps.max()),
        "min": float(s.min()),
        "max": float(s.max()),
        "note": (
            "US government data redistributed by FRED. Used only as a conditioning "
            "variable. Values are lagged one business day before use so a bar's "
            "signal cannot contain that same day's close."
        ),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
