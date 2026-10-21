"""Fetch official Cboe VIX and VIX3M daily histories for the gold research queue.

Command:
    python scripts/fetch_cboe_vix_curve.py

Downloaded raw files stay under data/raw/ (gitignored); source names and SHA256
are stored alongside them. No API keys and no invented observations. Data
availability is checked at runtime, not assumed from a URL in documentation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from qts.research.edgelab.vix_curve import read_cboe_history

OUT = Path("data/raw/edgelab/cboe_vix_curve")
HOSTS = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices",
    "https://cdn-api.cboe.com/api/global/us_indices/daily_prices",
)
NAMES = ("VIX", "VIX3M")


def fetch_one(name: str) -> tuple[str, bytes]:
    errors: list[str] = []
    for host in HOSTS:
        url = f"{host}/{name}_History.csv"
        try:
            req = Request(url, headers={"User-Agent": "QTS-Research/1.0", "Accept": "text/csv"})
            with urlopen(req, timeout=30) as response:
                content = response.read(3_000_000)
            # A 403 HTML response must never be saved as research observations.
            parsed = read_cboe_history(content.decode("utf-8-sig"), name=name)
            if len(parsed) < 500:
                raise ValueError(f"unexpectedly short {name} history: {len(parsed)} rows")
            return url, content
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{url}: {type(exc).__name__} {exc}")
    raise RuntimeError("Unable to retrieve and verify official Cboe history:\n" + "\n".join(errors))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    provenance: dict[str, object] = {"retrieved_at": datetime.now(UTC).isoformat(), "sources": {}}
    for name in NAMES:
        url, data = fetch_one(name)
        dst = OUT / f"{name}_History.csv"
        tmp = dst.with_suffix(".csv.tmp")
        tmp.write_bytes(data)
        tmp.replace(dst)
        parsed = read_cboe_history(data.decode("utf-8-sig"), name=name)
        provenance["sources"][name] = {
            "url": url,
            "file": str(dst),
            "sha256": hashlib.sha256(data).hexdigest(),
            "rows": len(parsed),
            "first": parsed.index.min().isoformat(),
            "last": parsed.index.max().isoformat(),
        }
    (OUT / "source_manifest.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
