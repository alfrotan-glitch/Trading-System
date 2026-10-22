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
    #: Lifecycle status. ``candidate`` means it cleared the pre-registered gate on
    #: development data and is accumulating evidence. ``rejected`` means later
    #: analysis invalidated it; the definition and its history are kept so the
    #: record is auditable, but no forward evidence should be collected for it.
    status: str = "candidate"
    rejected_reason: str = ""

    def definition_hash(self) -> str:
        """Hash of the callable's source plus parameters — the freeze mechanism."""
        # co_code ALONE does not encode literal constants or helper behavior:
        # "return 0" and "return 1" can have identical bytecode. Hash
        # code semantics, argument defaults and local function dependencies,
        # without path/line-number noise that varies across Windows installs.
        def freeze(obj: object, visited: set[int]) -> object:
            from types import CodeType, FunctionType

            if isinstance(obj, CodeType):
                return {
                    "ops": obj.co_code.hex(),
                    "constants": [freeze(c, visited) for c in obj.co_consts],
                    "names": obj.co_names,
                    "vars": obj.co_varnames,
                    "free": obj.co_freevars,
                    "kwonly": obj.co_kwonlyargcount,
                    "posonly": obj.co_posonlyargcount,
                    "args": obj.co_argcount,
                }
            if isinstance(obj, FunctionType):
                if id(obj) in visited:
                    return {"recursive": obj.__qualname__}
                visited.add(id(obj))
                code = obj.__code__
                helpers: dict[str, object] = {}
                for name in code.co_names:
                    value = obj.__globals__.get(name)
                    if isinstance(value, FunctionType) and value.__module__ == obj.__module__:
                        helpers[name] = freeze(value, visited)
                    elif type(value) in (bool, int, float, str, tuple):
                        helpers[name] = repr(value)
                return {
                    "code": freeze(code, visited),
                    "defaults": repr(obj.__defaults__),
                    "kwdefaults": repr(obj.__kwdefaults__),
                    "helpers": helpers,
                }
            return repr(obj)

        frozen = {"signal": freeze(self.signal, set()), "parameters": self.params}
        payload = json.dumps(frozen, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "family": self.family,
            "rationale": self.rationale,
            "params": self.params,
            "definition_hash": self.definition_hash(),
            "status": self.status,
            "rejected_reason": self.rejected_reason,
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
    *,
    price_basis: str | None = None,
    source_kind: str | None = None,
    source_id: str | None = None,
    enforce_forward: bool = False,
) -> dict:
    """Append one frozen observation. Idempotent per (candidate, date).

    A second call for the same date with a different signal raises rather than
    silently rewriting history: the point of a forward ledger is that early
    entries cannot be revised after the outcome is known.
    """
    if not math.isfinite(float(signal)) or not 0.0 <= float(signal) <= 1.0:
        raise ValueError(f"signal {signal!r} outside [0, 1] or non-finite")
    if not math.isfinite(float(gold_close)) or not gold_close > 0:
        raise ValueError("gold_close must be positive and finite")

    if enforce_forward:
        reg = registered().get(candidate.id)
        if candidate.status != "candidate" or not reg:
            raise ValueError("prospective logging requires an active, registered candidate")
        if reg.get("definition_hash") != candidate.definition_hash():
            raise ValueError("candidate definition was changed after registration")
        try:
            freeze = pd.Timestamp(reg["registered_at"])
            if freeze.tzinfo is None:
                raise ValueError("UTC freeze required")
            freeze = freeze.tz_convert("UTC")
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("candidate registration lacks a valid UTC freeze") from exc
        obs_date = pd.Timestamp(as_of)
        if pd.isna(obs_date):
            raise ValueError("observation date is invalid")
        observed = obs_date.date()
        now = datetime.now(UTC).date()
        if observed <= freeze.date() or observed > now or (now - observed).days > 3:
            raise ValueError("only newly observed dates AFTER registration may be logged")
        if price_basis != "m15_utc_close":
            raise ValueError("forward observation requires executable M15 UTC close")
        if source_kind not in PROSPECTIVE_SOURCES or not source_id:
            raise ValueError("verified source identity required for prospective observation")

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
    if enforce_forward:
        entry.update(
            price_basis=price_basis,
            source_kind=source_kind,
            source_id=source_id,
        )

    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            prev = json.loads(line)
            if prev["date"] == date and prev["candidate_id"] == candidate.id:
                if (
                    abs(float(prev["signal"]) - entry["signal"]) > 1e-6
                    or abs(float(prev.get("gold_close", 0)) - entry["gold_close"]) > 1e-6
                    or prev.get("definition_hash") != entry["definition_hash"]
                    or (enforce_forward and any(
                        prev.get(k) != entry[k]
                        for k in ("price_basis", "source_kind", "source_id")
                    ))
                ):
                    raise ValueError(
                        f"observation for {candidate.id} on {date} already recorded "
                        "with different signal, price, definition or provenance; "
                        "refusing to revise history"
                    )
                return prev
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry



#: Provenance classes that may support *prospective research*. An operator
#: typing a price or replaying a historical CSV cannot self-attest to these.
PROSPECTIVE_SOURCES = ("MT5_DEMO_COMPLETED_BAR", "VERIFIED_EXTERNAL_UTC_CLOSE")


def prospective_integrity(
    candidate: Candidate,
    registration: dict | None,
    entries: pd.DataFrame,
) -> dict:
    """Audit whether the ledger is actually prospective, NOT whether it has alpha.

    Legacy unverified JSONL rows may still be used for exploratory statistics;
    they may NOT turn into forward-validation evidence merely by raising a t.
    This is an eligibility audit, not proof that a purported broker source is
    genuine, that costs are measured, or that a strategy is profitable.
    """
    failures: list[str] = []
    if candidate.status != "candidate":
        failures.append("candidate is not active")
    if not registration:
        failures.append("candidate definition was never registered")
    elif registration.get("definition_hash") != candidate.definition_hash():
        failures.append("registered definition hash differs from current strategy")
    registered_at: pd.Timestamp | None = None
    if registration:
        try:
            registered_at = pd.Timestamp(registration["registered_at"])
            if pd.isna(registered_at) or registered_at.tzinfo is None:
                raise ValueError("missing time zone")
            registered_at = registered_at.tz_convert("UTC")
        except (KeyError, ValueError, TypeError):
            failures.append("registration has no auditable UTC freeze timestamp")
            registered_at = None

    if entries.empty:
        failures.append("no forward observations")
        return {"eligible_for_review": False, "issues": failures, "verified_rows": 0}

    if "candidate_id" in entries:
        entries = entries.loc[entries["candidate_id"] == candidate.id]
    if entries.empty:
        failures.append("no observations for candidate")
        return {"eligible_for_review": False, "issues": failures, "verified_rows": 0}

    required = {
        "date", "signal", "gold_close", "definition_hash", "logged_at",
        "price_basis", "source_kind", "source_id",
    }
    missing = required.difference(entries.columns)
    if missing:
        failures.append(f"ledger lacks provenance fields: {sorted(missing)}")
        return {"eligible_for_review": False, "issues": failures, "verified_rows": 0}

    if entries["date"].duplicated().any():
        failures.append("duplicate observation date")
    verified_rows = 0
    for row in entries.to_dict(orient="records"):
        try:
            day = pd.Timestamp(row["date"])
            recorded = pd.Timestamp(row["logged_at"])
            if pd.isna(day) or pd.isna(recorded) or recorded.tzinfo is None:
                raise ValueError("missing UTC timestamp")
            recorded = recorded.tz_convert("UTC")
            day = day.tz_localize("UTC") if day.tzinfo is None else day.tz_convert("UTC")
            if registered_at is None or day.date() <= registered_at.date():
                raise ValueError("price date is not after the frozen registration")
            if recorded < registered_at:
                raise ValueError("entry predates candidate registration")
            age = (recorded.date() - day.date()).days
            if age < 0 or age > 3:
                raise ValueError("price was logged retrospectively or before its date")
            if row["definition_hash"] != candidate.definition_hash():
                raise ValueError("ledger definition does not match frozen strategy")
            if row["price_basis"] != "m15_utc_close":
                raise ValueError("non-executable or unverified price basis")
            if row["source_kind"] not in PROSPECTIVE_SOURCES or not str(row["source_id"]):
                raise ValueError("missing recognised price-source identity")
            signal, price = float(row["signal"]), float(row["gold_close"])
            if not (math.isfinite(signal) and 0 <= signal <= 1):
                raise ValueError("invalid signal")
            if not (math.isfinite(price) and price > 0):
                raise ValueError("invalid reference price")
            verified_rows += 1
        except (ValueError, TypeError, OverflowError, KeyError) as exc:
            failures.append(f"invalid forward entry on {row.get('date')}: {exc}")
    return {
        "eligible_for_review": not failures and verified_rows >= 30,
        "verified_rows": verified_rows,
        "issues": failures + (["fewer than 30 attributable observations"] if verified_rows < 30 else []),
        "note": "Passing this provenance audit is NOT profitability validation.",
    }


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
        # Forward scores must use the SAME realistic ECN research assumptions
        # named by the API, not the obsolete optimistic harness default.
        # Neither model measures the owner's actual broker costs.
        from qts.research.edgelab import CostModel

        per_side = CostModel.realistic_ecn().per_side_bps() / 1e4
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
