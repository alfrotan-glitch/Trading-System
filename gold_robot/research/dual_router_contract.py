"""Deterministic arbitration contract for TESTER-only dual Retest/Sweep modes.

This is a simple independent selector for unit tests and documentation,
NOT a substitute for native MQL5 signal/entry/fees or an edge estimate.
"""
from __future__ import annotations

from dataclasses import dataclass

RETEST = 1
SWEEP = 3


@dataclass(frozen=True)
class Candidate:
    style: int
    side: int
    executable: bool = True


def choose(mode: int, candidates: list[Candidate]) -> tuple[int, int] | None:
    """Return one (style,side), or abstain on 0/2+ eligible setups.

    Mode 1 considers all buy/sell candidates for both strategies.
    Mode 2 is post-hoc BUY Retest / SELL Sweep and must never be presented
    as an independently validated edge. The execution layer still owns risk.
    """
    if mode not in (1, 2):
        raise ValueError("Dual router unavailable outside isolated research modes 1/2")
    styles = [c.style for c in candidates]
    if len(styles) != len(set(styles)) or any(style not in (RETEST, SWEEP) for style in styles):
        raise ValueError("Ambiguous or unsupported strategy identity")
    if any(c.side not in (-1, 0, 1) for c in candidates):
        raise ValueError("Invalid BUY/SELL side")
    valid = [c for c in candidates
             if c.executable and c.side
             and (mode == 1 or
                  (c.style == RETEST and c.side == 1) or
                  (c.style == SWEEP and c.side == -1))]
    if len(valid) != 1:
        return None
    c = valid[0]
    return (c.style, c.side)
