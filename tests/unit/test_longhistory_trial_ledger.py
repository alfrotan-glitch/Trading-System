"""Trial-ledger integrity: the multiple-testing denominators behind every DSR
in the long-history programme must be code-derived, chained, and identical
to what each committed final actually used. If a future cycle edits a count
by hand, this test fails before the number can be believed."""

import json
from pathlib import Path

import pytest

from qts.research.longhistory import ensemble_protocol as ENS
from qts.research.longhistory import hybrid_protocol as HYB
from qts.research.longhistory import intraday_protocol as INTRA
from qts.research.longhistory import monthly_protocol as MON
from qts.research.longhistory import protocol as DAILY
from qts.research.longhistory import reversal_protocol as REV
from qts.research.longhistory import seasonal_protocol as SEA
from qts.research.longhistory import volmanaged_protocol as VOLM
from qts.research.longhistory import weekly_hybrid_protocol as WHYB
from qts.research.longhistory import weekly_protocol as W1

EVIDENCE = Path(__file__).resolve().parents[2] / "data" / "evidence" / "longhistory"

# module -> (expected N_TRIALS, final evidence file or None)
CHAIN = [
    (DAILY, 26, None),
    (INTRA, 40, None),
    (SEA, 47, None),
    (REV, 50, None),
    (MON, 72, "monthly_research_final.json"),
    (ENS, 149, "ensemble_research_final.json"),
    (W1, 193, "weekly_research_final.json"),
    (HYB, 237, "hybrid_research_final.json"),
    (WHYB, 262, "weekly_hybrid_research_final.json"),
    (VOLM, 285, "volmanaged_research_final.json"),
]


def _num_trials_in(doc) -> set:
    found = set()

    def walk(o):
        if isinstance(o, dict):
            if "num_trials" in o:
                found.add(o["num_trials"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return found


def _evidence_cids(doc) -> set:
    found = set()

    def walk(o):
        if isinstance(o, dict):
            if o.get("cid"):
                found.add(o["cid"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return found


@pytest.mark.parametrize(("module", "expected_n", "fname"), CHAIN, ids=[c[0].__name__ for c in CHAIN])
def test_trial_count_chain(module, expected_n, fname):
    assert expected_n == module.N_TRIALS


@pytest.mark.parametrize(("module", "expected_n", "fname"), [c for c in CHAIN if c[2]], ids=[c[2] for c in CHAIN if c[2]])
def test_final_evidence_used_the_registered_trial_count(module, expected_n, fname):
    doc = json.loads((EVIDENCE / fname).read_text())
    assert _num_trials_in(doc) == {expected_n}


@pytest.mark.parametrize(("module", "expected_n", "fname"), [c for c in CHAIN if c[2]], ids=[c[2] for c in CHAIN if c[2]])
def test_evaluated_candidates_are_exactly_the_registered_candidates(module, expected_n, fname):
    doc = json.loads((EVIDENCE / fname).read_text())
    registered = {c.cid for c in module.CANDIDATES if c.role == "CANDIDATE"}
    assert _evidence_cids(doc) == registered
