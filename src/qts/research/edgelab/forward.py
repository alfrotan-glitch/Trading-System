"""Forward observation for Edge Lab candidates.

A backtest holdout can be spent exactly once. Once it has been read, it is
in-sample for every later hypothesis, and no amount of re-analysis restores it.
The only remaining source of genuinely unseen evidence is **time**: record a
candidate's signal today, with its definition frozen, and score it against the
returns that follow.

That is what this module exists for, and it is deliberately conservative:

* **Definitions are hashed.** A candidate is stored with a SHA-256 of its signal
  source and parameters. Editing the rule after registration changes the hash and
  is rejected, so a candidate cannot be quietly improved while its track record is
  presented as continuous.
* **Observations are append-only.** Re-running a log for the same date rewrites
  nothing; the ledger is JSONL and each line carries the date, the frozen signal,
  and the price it was recorded at.
* **The ledger never claims more than it has.** ``score()`` reports the number of
  observations, the achieved t-statistic, and how many further observations would
  be needed to reach the 2.5 threshold at the observed effect size. No projection
  is presented as a result.

Scoring uses consecutive close-to-close gold returns and compares against
buy-and-hold, matching the decomposition used everywhere else in the lab. Costs
are charged at the same assumed basis points, and are reported as assumed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from qts.config.paths import artifact_path

#: Observations older than this mean the macro inputs have not been refreshed.
MAX_MACRO_STALENESS_DAYS = 7

MIN_ALPHA_T = 2.5


@dataclass(frozen=True)
class Candidate:
    """A frozen, registered strategy definition.

    ``signal`` maps a bars frame to a position series in [0, 1]. It is hashed by
    source so the registry can prove the rule has not changed since registration.
    """

    id: str
    name: str
    family: str
    rationale: str
    params: dict
    signal: Callable[[pd.DataFrame], pd.Series]

    def definition_hash(self) -> str:
        """Hash of the callable's source plus parameters — the freeze mechanism."""
        try:
            src = self.signal.__code__.co_code  # bytecode: changes if logic changes
            names = src + repr(sorted(self.params.items())).encode()
        except AttributeError:  # pragma: no cover - builtins have no __code__
            names = repr(self.params).encode()
        return hashlib.sha256(names).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "family": self.family,
            "rationale": self.rationale,
            "params": self.params,
            "definition_hash": self.definition_hash(),
        }


def _registry_path(explicit: str | Path | None = None) -> Path:
    return artifact_path("edgelab_candidates", explicit)


def _ledger_path(explicit: str | Path | None = None) -> Path:
    return artifact_path("edgelab_forward_ledger", explicit)


def register(candidate: Candidate, path: str | Path | None = None) -> dict:
    """Register a candidate. Refuses to overwrite a different definition."""
    p = _registry_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"candidates": {}}
    existing = doc["candidates"].get(candidate.id)
    record = candidate.as_dict()
    record["registered_at"] = (
        existing["registered_at"] if existing else datetime.now(UTC).isoformat()
    )
    if existing and existing["definition_hash"] != record["definition_hash"]:
        raise ValueError(
            f"candidate {candidate.id!r} is already registered with a different "
            f"definition ({existing['definition_hash']} -> {record['definition_hash']}). "
            "Changing a candidate after registration invalidates its track record; "
            "register a new id instead."
        )
    doc["candidates"][candidate.id] = record
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return record


def registered(path: str | Path | None = None) -> dict[str, dict]:
    p = _registry_path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("candidates", {})


def log_observation(
    candidate: Candidate,
    as_of: datetime | pd.Timestamp,
    signal: float,
    gold_close: float,
    path: str | Path | None = None,
) -> dict:
    """Append one frozen observation. Idempotent per (candidate, date).

    A second call for the same date with a different signal raises rather than
    silently rewriting history: the point of a forward ledger is that early
    entries cannot be revised after the outcome is known.
    """
    if not 0.0 <= float(signal) <= 1.0:
        raise ValueError(f"signal {signal!r} outside [0, 1]")
    if not gold_close > 0:
        raise ValueError("gold_close must be positive")

    p = _ledger_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    date = pd.Timestamp(as_of).normalize().date().isoformat()
    entry = {
        "date": date,
        "candidate_id": candidate.id,
        "definition_hash": candidate.definition_hash(),
        "signal": round(float(signal), 6),
        "gold_close": round(float(gold_close), 6),
        "logged_at": datetime.now(UTC).isoformat(),
    }

    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            prev = json.loads(line)
            if prev["date"] == date and prev["candidate_id"] == candidate.id:
                if abs(prev["signal"] - entry["signal"]) > 1e-6:
                    raise ValueError(
                        f"observation for {candidate.id} on {date} already recorded "
                        f"with signal {prev['signal']}; refusing to revise history"
                    )
                return prev
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def load_ledger(path: str | Path | None = None) -> pd.DataFrame:
    p = _ledger_path(path)
    if not p.exists():
        return pd.DataFrame(columns=["date", "candidate_id", "signal", "gold_close"])
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["candidate_id", "date"]).reset_index(drop=True)


def score(df: pd.DataFrame) -> pd.DataFrame:
    """Score every candidate in a ledger against realised gold returns.

    Returns one row per candidate with observations, span, mean signal, realised
    strategy return net of assumed costs, and the alpha t-statistic against
    buy-and-hold. ``observations_for_significance`` is the honest answer to "how
    much longer" — ``ceil((2.5 / t)^2 * n)`` — and is refused when it cannot be
    computed rather than guessed.
    """
    if df.empty:
        return pd.DataFrame()
    out = []
    for cid, g in df.groupby("candidate_id"):
        g = g.sort_values("date")
        if len(g) < 3:
            # Keep the full column set so downstream sorting/reporting is uniform;
            # a candidate with one observation simply has no measurable statistics.
            out.append(
                {
                    "candidate_id": cid,
                    "observations": len(g),
                    "span_days": int((g["date"].iloc[-1] - g["date"].iloc[0]).days),
                    "years": round((g["date"].iloc[-1] - g["date"].iloc[0]).days / 365.25, 2),
                    "mean_signal": round(float(g["signal"].mean()), 3),
                    "total_return": float("nan"),
                    "sharpe": float("nan"),
                    "t_stat": float("nan"),
                    "alpha_ann": float("nan"),
                    "alpha_t": float("nan"),
                    "beta": float("nan"),
                    "observations_for_significance": None,
                    "status": "insufficient",
                }
            )
            continue
        px = g["gold_close"].to_numpy(dtype=float)
        ret = px[1:] / px[:-1] - 1.0
        held = g["signal"].to_numpy(dtype=float)[:-1]
        gross = held * ret
        turnover = np.abs(np.diff(np.concatenate([[0.0], held])))
        # Costs are ASSUMED at the ECN reference; reported as assumed, never measured.
        from qts.research.edgelab import CostModel

        per_side = CostModel().per_side_bps() / 1e4
        net = gross - turnover * per_side

        bar_years = (g["date"].iloc[-1] - g["date"].iloc[0]).days / 365.25
        bars_per_year = 252.0
        sd = float(np.std(net, ddof=1)) if len(net) > 2 else 0.0
        sharpe = float(np.mean(net) / sd * math.sqrt(bars_per_year)) if sd > 0 else 0.0
        t_stat = float(np.mean(net) / (sd / math.sqrt(len(net)))) if sd > 0 else 0.0

        bench = ret
        var_b = float(np.var(bench, ddof=1))
        beta = float(np.cov(net, bench, ddof=1)[0, 1] / var_b) if var_b > 0 else 0.0
        alpha = float(np.mean(net) - beta * np.mean(bench))
        resid = net - beta * bench
        resid_sd = float(np.std(resid, ddof=1)) if len(resid) > 2 else 0.0
        alpha_t = float(alpha / (resid_sd / math.sqrt(len(net)))) if resid_sd > 0 else 0.0

        need = None
        if abs(alpha_t) > 1e-9:
            need = int(math.ceil((MIN_ALPHA_T / abs(alpha_t)) ** 2 * len(net)))

        out.append(
            {
                "candidate_id": cid,
                "observations": int(len(g)),
                "span_days": int((g["date"].iloc[-1] - g["date"].iloc[0]).days),
                "years": round(bar_years, 2),
                "mean_signal": round(float(g["signal"].mean()), 3),
                "total_return": round(float(np.prod(1 + net) - 1), 4),
                "sharpe": round(sharpe, 3),
                "t_stat": round(t_stat, 2),
                "alpha_ann": round(alpha * bars_per_year, 4),
                "alpha_t": round(alpha_t, 2),
                "beta": round(beta, 3),
                "observations_for_significance": need,
                "status": "accumulating" if alpha_t < MIN_ALPHA_T else "reached_threshold",
            }
        )
    return pd.DataFrame(out).sort_values("alpha_t", ascending=False).reset_index(drop=True)


def staleness_warning(as_of: pd.Timestamp, last_macro: pd.Timestamp) -> str | None:
    """Warn when macro inputs are too old for the signal to be meaningful."""
    gap = (pd.Timestamp(as_of) - pd.Timestamp(last_macro)).days
    if gap > MAX_MACRO_STALENESS_DAYS:
        return (
            f"macro inputs are {gap} days stale (limit {MAX_MACRO_STALENESS_DAYS}). "
            "The signal reflects old data; refresh DXY and the 10-year yield before "
            "treating this observation as a forward test."
        )
    return None
