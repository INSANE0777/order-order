"""Failure mode 3: the court the brief names is not the court that decided it.

The record settles this without reading the judgment, so the tests are about reading the brief's own
sentence correctly and about the asymmetry that governs the whole engine: overstatement is a finding,
understatement is not, and silence in the record is "not checked" rather than "wrong".
"""

from __future__ import annotations

import pytest

from orderorder.engine.hierarchy import (
    HIGH_COURT,
    NOT_ASSESSED,
    OK,
    OVERSTATED_BENCH,
    SUPREME_COURT,
    WRONG_COURT,
    check_hierarchy,
    read_attribution,
)

SC = "Supreme Court of India"
HC = "High Court of Delhi"


# --- reading the brief ---------------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "text"),
    [
        (SUPREME_COURT, "as the Supreme Court held in that case"),
        (SUPREME_COURT, "the Hon'ble Supreme Court of India has settled the point"),
        (SUPREME_COURT, "the Apex Court observed as follows"),
        (HIGH_COURT, "the High Court held that the suit was maintainable"),
        (HIGH_COURT, "the Delhi High Court took a contrary view"),
        (None, "it was held that the plaintiff is the dominus litis"),
    ],
)
def test_the_court_the_brief_names(expected: str | None, text: str) -> None:
    assert read_attribution(text).court == expected


def test_this_court_is_not_read_as_a_claim() -> None:
    """In a brief "this Court" is the court being addressed, not the court that decided the authority.

    Reading it either way would invent findings on the commonest phrase in Indian advocacy.
    """
    assert read_attribution("as this Court held in Kasturi").court is None


def test_a_fronted_procedural_participle_makes_the_court_a_recital() -> None:
    """"Rejecting the plea, the High Court opined that ..." is the brief recounting the case below.

    The words belong to the citation's own narration of its history -- the September 2026 holdout
    lifted exactly such a sentence from a Supreme Court judgment and the attribution check read the
    recited High Court view as the brief's claim about the cited case, which flagged a clean
    citation as failure mode 3. A narrated view is not an attribution; the real one follows.
    """
    proposition = (
        "Rejecting the plea, the High Court opined that since the appellant did not produce the "
        "clarificatory notification along with the writ petition, no occasion arose to consider it"
    )
    assert read_attribution(proposition).court is None


@pytest.mark.parametrize(
    ("expected", "text"),
    [
        # No participle at all: the plainest real attribution.
        (HIGH_COURT, "the High Court has held that the suit was maintainable"),
        # A comma lead-in that is not a procedural participle does not make it a recital.
        (HIGH_COURT, "In the circumstances, the High Court has held that the suit was maintainable"),
        # The same shape as the false positive, with a different fronted action: still a recital.
        (None, "Setting aside the decree, the High Court opined that the plaintiff was not ready "
               "and willing to perform his part of the contract"),
    ],
)
def test_the_recital_rule_and_its_limits(expected: str | None, text: str) -> None:
    assert read_attribution(text).court == expected


@pytest.mark.parametrize(
    ("expected", "text"),
    [
        (5, "a Constitution Bench has settled the question"),
        (3, "a three-Judge Bench of this Court considered the point"),
        (3, "a three Judge Bench took the same view"),
        (7, "a seven-Judge Bench laid down the rule"),
        (2, "a Division Bench of the High Court held"),
        (None, "the court held that the appeal must fail"),
    ],
)
def test_the_bench_the_brief_claims(expected: int | None, text: str) -> None:
    assert read_attribution(text).bench == expected


# --- comparing it with the record ----------------------------------------------


def test_a_high_court_decision_called_the_supreme_court() -> None:
    """The graver claim: it turns persuasive authority into binding authority."""
    check = check_hierarchy("as the Supreme Court held, the suit was maintainable", HC, 2)
    assert check.status == WRONG_COURT
    assert check.is_problem
    assert "decided by High Court of Delhi" in (check.note or "")


def test_two_judges_called_a_constitution_bench() -> None:
    check = check_hierarchy("a Constitution Bench has settled this question", SC, 2)
    assert check.status == OVERSTATED_BENCH
    assert check.is_problem
    assert check.claimed_bench == 5
    assert check.actual_bench == 2


def test_a_correct_attribution_is_not_a_finding() -> None:
    assert check_hierarchy("as the Supreme Court held", SC, 2).status == OK
    assert check_hierarchy("a three-Judge Bench held", SC, 3).status == OK


def test_understating_the_bench_harms_nobody() -> None:
    """A brief calling a five-judge decision "a two-Judge Bench" is being modest about its own case."""
    check = check_hierarchy("a Division Bench of this Court held", SC, 5)
    assert check.status == OK
    assert not check.is_problem


def test_saying_nothing_about_the_court_is_not_a_finding() -> None:
    check = check_hierarchy("the plaintiff is the dominus litis", SC, 2)
    assert check.status == NOT_ASSESSED
    assert not check.is_problem


def test_an_unrecorded_bench_strength_is_not_checked_rather_than_wrong() -> None:
    """Silence in the record is silence. It is not evidence that the brief overstated."""
    check = check_hierarchy("a Constitution Bench has settled this", SC, None)
    assert check.status == NOT_ASSESSED
    assert not check.is_problem
    assert "no bench strength" in (check.note or "")


def test_an_unrecorded_court_is_not_checked() -> None:
    check = check_hierarchy("as the Supreme Court held", None, 2)
    assert check.status == OK
    assert not check.is_problem


# --- in the verdict ------------------------------------------------------------


def test_the_verdict_carries_the_finding_and_floors_the_grade() -> None:
    from orderorder.engine.verdict import MODE_WRONG_COURT, build_verdict
    from orderorder.resolver import Resolution

    found = Resolution(status="found", method="exact", judgment_id="j1", canonical_key="K", score=100.0)
    check = check_hierarchy("a Constitution Bench has settled this", SC, 2)
    verdict = build_verdict("(2019) 4 SCC 1", "a Constitution Bench has settled this", found, hierarchy=check)

    assert any(f.mode == MODE_WRONG_COURT for f in verdict.findings)
    assert verdict.grade == "D"
