"""Cross-source and cross-section replication for Edge Lab findings.

A result that exists on one broker's price series and not on another's is a
property of that feed, not of the market. This module loads the independent
MT5 export (`ejtraderLabs/historical-data`, Apache-2.0, pinned commit) so that
every gold finding can be re-measured on a second price series before it is
believed.

Two distinct checks, and the difference matters:

* **Cross-source** — same instrument (XAUUSD), same window, different broker.
  This tests whether a result is a *measurement artefact*. It is the stronger
  test, because the underlying market is literally the same.
* **Cross-section** — same rule, different instruments. This tests whether a
  rule has general validity or is fitted to one series. It is the weaker test,
  because FX pairs share dominant factors: EURUSD, GBPUSD, EURGBP, EURJPY,
  USDJPY, GBPJPY, AUDJPY, USDCHF, USDCAD and EURCHF are far from independent.
  A sign count across them overstates the effective sample size, so any
  significance figure here must be read as an upper bound.

Prices in this export are scaled by 100 or 1000 depending on the instrument.
That is deliberately not corrected: every rule here works on returns and every
cost is quoted in basis points of notional, so both are scale-invariant. Adding
a per-instrument divisor would be a guess with no effect on the result.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PANEL_ROOT = Path("data/raw/longhistory")
PANEL_GLOB = "historical-data-*/"

#: Every instrument shares this window, which keeps comparisons like-for-like.
PANEL_START = "2012-11-14"
PANEL_END = "2022-03-04"

INSTRUMENTS = (
    "XAUUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
    "EURGBP",
    "EURCHF",
)


def _panel_dir() -> Path:
    matches = sorted(PANEL_ROOT.glob(PANEL_GLOB))
    if not matches:
        raise FileNotFoundError(
            f"no panel data under {PANEL_ROOT}/{PANEL_GLOB} — fetch "
            "https://codeload.github.com/ejtraderLabs/historical-data/tar.gz/"
            "fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd"
        )
    return matches[-1]


def load_instrument(name: str, end: str | None = None) -> pd.DataFrame:
    """Load one instrument's M15 bars, sorted and de-duplicated.

    Timestamps are the broker's server clock (market opens Monday 01:00, closes
    Friday 23:45), not UTC. Daily aggregates are therefore offset by a few hours
    relative to a true-UTC series. This is left as-is and reported rather than
    silently "corrected" with an unverified offset; it is one more reason a
    cross-source difference is weak evidence and a cross-source *match* is strong.
    """
    path = _panel_dir() / name / f"{name}m15.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.rename(columns={"Date": "ts", "tick_volume": "volume"})
    df = df.set_index("ts").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="first")]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def load_panel(end: str = "2018-12-31") -> dict[str, pd.DataFrame]:
    """All instruments, clipped to the pre-holdout part of the shared window.

    ``end`` defaults to the DEV boundary: the cross-section must not consume
    VAL or TEST to answer a question about whether a *rule family* works.
    """
    return {name: load_instrument(name, end=end) for name in INSTRUMENTS}
