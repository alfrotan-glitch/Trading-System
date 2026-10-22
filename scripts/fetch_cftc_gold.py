"""Download CFTC GOLD 088691 Disaggregated Futures-Only history, no API key.

Requires network access to official CFTC publicreporting endpoint.
Raw records stay gitignored under data/raw/; a content hash and source URL are
recorded. Failure must stop the experiment instead of substituting a proxy.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qts.research.edgelab.cot_disaggregated import (
    GOLD_MARKET_CODE,
    OFFICIAL_CFTC_DATASET,
    REQUIRED_COLUMNS,
    parse_official_gold,
)

ROOT = Path("data/raw/edgelab/cftc_gold")
URL = f"https://publicreporting.cftc.gov/resource/{OFFICIAL_CFTC_DATASET}.json"
SELECT = ",".join(REQUIRED_COLUMNS)


def main() -> None:
    params = {
        "$select": SELECT,
        "$where": f"cftc_contract_market_code='{GOLD_MARKET_CODE}'",
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": "5000",
    }
    url = URL + "?" + urlencode(params)
    request = Request(
        url, headers={"Accept": "application/json", "User-Agent": "QTS-Gold-Research/1.0"}
    )
    with urlopen(request, timeout=90) as reply:  # nosec B310
        raw = reply.read(6_000_000)
    try:
        rows = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RuntimeError("official CFTC endpoint did not return valid JSON") from exc
    if not isinstance(rows, list):
        raise RuntimeError(f"CFTC returned a non-list response: {type(rows).__name__}")
    series = parse_official_gold(rows)
    ROOT.mkdir(parents=True, exist_ok=True)
    raw_path = ROOT / "gold_disaggregated_futures_only.json"
    tmp = raw_path.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(raw_path)
    manifest = {
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "url": url,
        "dataset": OFFICIAL_CFTC_DATASET,
        "contract_code": GOLD_MARKET_CODE,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "observations": len(series),
        "first_report": str(series.index.min()),
        "last_report": str(series.index.max()),
        "timing_warning": "Tuesday positions, normal Friday publication; actual release timestamps absent",
    }
    (ROOT / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
