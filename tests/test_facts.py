"""Failure mode 11: everything checks out and the case still does not apply.

The last of the twelve, and the only one the judgment cannot answer alone — it needs the facts of the
matter now before the court, which nobody but the user has.

Declaring an authority inapplicable is the strong claim in this engine. An advocate who believes it
drops a case they were entitled to win, so it is the one answer required to quote the judgment's own
statement of the fact said to distinguish it. These tests are mostly about that requirement.
"""

from __future__ import annotations

from orderorder.engine.facts import (
    INAPPLICABLE,
    NOT_ASSESSED,
    STRONG,
    assess_applicability,
)
from orderorder.engine.locator import Candidate
from orderorder.engine.schemas import ApplicabilityAssessment

JUDGMENT = (
    "The appellant purchased the suit property during the pendency of the suit and in violation of "
    "an injunction granted by the trial court. A stranger to the contract claiming under an "
    "independent title cannot be impleaded in a suit for specific performance."
)
CLAIM = "A stranger to the contract cannot be impleaded in a suit for specific performance."
FACTS = "Our client purchased the property two years before the suit was filed, with no injunction in force."


def _candidate() -> Candidate:
    return Candidate(seq=7, printed_label="7", score=1.0, matched_terms=[], body=JUDGMENT)


class StubModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def invoke(self, prompt: str):
        self.calls += 1
        return self.answer


def test_without_the_matters_facts_the_question_is_not_asked(model=None) -> None:
    """No facts, no comparison. An engine that answered anyway would answer a question nobody asked."""
    verdict = assess_applicability(CLAIM, "", [_candidate()], StubModel(None))
    assert verdict.status == NOT_ASSESSED
    assert not verdict.needs_review  # nothing was withheld; nothing was requested
    assert "not supplied" in (verdict.review_reason or "")


def test_without_a_model_it_says_so(  ) -> None:
    verdict = assess_applicability(CLAIM, FACTS, [_candidate()], None)
    assert verdict.status == NOT_ASSESSED
    assert verdict.needs_review


def test_a_grounded_finding_of_inapplicability_stands() -> None:
    model = StubModel(
        ApplicabilityAssessment(
            status="inapplicable",
            distinguishing_facts=["the purchase here preceded the suit and no injunction was in force"],
            paragraph_label="7",
            quote="The appellant purchased the suit property during the pendency of the suit",
            reason="The cited case turned on a purchase made during the suit, which is absent here.",
            confidence=0.8,
        )
    )
    verdict = assess_applicability(CLAIM, FACTS, [_candidate()], model)
    assert verdict.status == INAPPLICABLE
    assert verdict.quote_verified
    assert verdict.is_problem
    assert verdict.paragraph_label == "7"


def test_an_inapplicability_that_cannot_be_quoted_is_not_recorded() -> None:
    """The model invents the distinguishing fact. An advocate would drop a good case on it."""
    model = StubModel(
        ApplicabilityAssessment(
            status="inapplicable",
            distinguishing_facts=["the cited case concerned agricultural land"],
            quote="The suit property was agricultural land held under a tenancy",
            confidence=0.95,
        )
    )
    verdict = assess_applicability(CLAIM, FACTS, [_candidate()], model)
    assert verdict.status == NOT_ASSESSED
    assert not verdict.quote_verified
    assert not verdict.is_problem
    assert verdict.needs_review


def test_inapplicability_without_any_quote_is_not_recorded() -> None:
    model = StubModel(ApplicabilityAssessment(status="inapplicable", quote=None, confidence=0.9))
    verdict = assess_applicability(CLAIM, FACTS, [_candidate()], model)
    assert verdict.status == NOT_ASSESSED
    assert verdict.needs_review


def test_saying_the_case_applies_needs_no_quote() -> None:
    """Only the strong claim has to be grounded: saying an authority applies takes nothing away."""
    model = StubModel(
        ApplicabilityAssessment(
            status="strong",
            shared_facts=["both concern a stranger to the contract claiming an independent title"],
            confidence=0.85,
        )
    )
    verdict = assess_applicability(CLAIM, FACTS, [_candidate()], model)
    assert verdict.status == STRONG
    assert not verdict.is_problem
    assert verdict.was_assessed


def test_low_confidence_asks_for_review_without_losing_the_answer() -> None:
    model = StubModel(
        ApplicabilityAssessment(
            status="inapplicable",
            quote="The appellant purchased the suit property during the pendency of the suit",
            confidence=0.2,
        )
    )
    verdict = assess_applicability(CLAIM, FACTS, [_candidate()], model)
    assert verdict.status == INAPPLICABLE
    assert verdict.needs_review


def test_a_provider_outage_is_reported_as_unassessed() -> None:
    class Failing:
        def invoke(self, prompt: str):
            raise RuntimeError("all providers exhausted")

    verdict = assess_applicability(CLAIM, FACTS, [_candidate()], Failing())
    assert verdict.status == NOT_ASSESSED
    assert verdict.needs_review
    assert not verdict.is_problem


def test_no_located_paragraph_means_no_comparison() -> None:
    model = StubModel(ApplicabilityAssessment(status="inapplicable", confidence=0.9))
    verdict = assess_applicability(CLAIM, FACTS, [], model)
    assert verdict.status == NOT_ASSESSED
    assert model.calls == 0


def test_the_verdict_carries_the_finding_and_drops_one_grade() -> None:
    from orderorder.engine.verdict import MODE_DISTINGUISHABLE, build_verdict
    from orderorder.resolver import Resolution

    model = StubModel(
        ApplicabilityAssessment(
            status="inapplicable",
            distinguishing_facts=["the purchase here preceded the suit"],
            quote="The appellant purchased the suit property during the pendency of the suit",
            reason="The cited case turned on a purchase during the suit.",
            confidence=0.8,
        )
    )
    applicability = assess_applicability(CLAIM, FACTS, [_candidate()], model)
    found = Resolution(status="found", method="exact", judgment_id="j1", canonical_key="K", score=100.0)
    verdict = build_verdict("(2019) 4 SCC 1", CLAIM, found, applicability=applicability)

    finding = next(f for f in verdict.findings if f.mode == MODE_DISTINGUISHABLE)
    assert "purchase here preceded the suit" in str(finding)
    assert verdict.grade == "B"
