#!/usr/bin/env python3
"""Print current benchmark and broker-cost status without replaying old metrics.

Historical benchmark evidence is retained for audit, but this utility no longer
prints its performance figures as if they were current results. No market data
is read or strategy is evaluated here.
"""

from __future__ import annotations


def main() -> None:
    print("Benchmark status: ARCHIVED RESULTS ONLY — no current evaluation run.")
    print("Current research verdict: NO_VALIDATED_EDGE; no benchmark is claim-eligible.")
    print("Account-specific spread, commission, slippage, and financing: UNMEASURED.")
    print("Published broker specifications and historical quote archives are not account costs.")
    print("LIVE remains LOCKED; real-capital exposure remains zero.")
    print("Historical evidence remains in data/evidence/benchmark_candidates.json.")


if __name__ == "__main__":
    main()
