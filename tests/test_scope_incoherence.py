"""When the model contradicts itself, the reading that claims less is the one that stands.

Every case here came off one run: the first time the drafting surface met a live model, it bound
three propositions to paragraphs that did not support them and graded all three `full`. The quotes
were real, verbatim and correctly attributed -- quote-or-nothing held -- but the judgement about
*extent* was wrong, and the engine had the evidence to know it and threw the evidence away.

Three separate faults, all structural, none needing a model to detect:

  * confidence 0.0 skipped the confidence gate, because the gate was a truth test and zero is falsy;
  * the model wrote four hundred words of analysis into `narrowed_proposition`, which would have been
    set into a filed submission as the sentence to argue;
  * it answered `full` and offered a narrowing in the same breath, which cannot both be true.
"""

from __future__ import annotations

import pytest

from orderorder.engine.locator import Candidate
from orderorder.engine.schemas import ScopeAssessment
from orderorder.engine.scope import MIN_CONFIDENCE_FOR_SUPPORT, assess_scope

CLAIM = "A subsequent purchaser holding a prior agreement to sell is a necessary party to the suit"
BODY = (
    "In a suit for specific performance where the property has been sold to a subsequent purchaser, "
    "two things are necessary for the adjudication, namely whether the plaintiff remained ready and "
    "willing to perform his part of the contract, and whether the subsequent transferee had prior "
    "knowledge of the earlier agreement executed in favour of the plaintiff."
)
QUOTE = "two things are necessary for the adjudication"

# The analysis the model actually produced in the field meant for a rewritten claim, abridged. The
# point is its shape, not its words: it is prose about the claim, not a claim.
ESSAY = (
    "The claim states that a subsequent purchaser who holds a prior agreement to sell is a necessary "
    "party to a suit for specific performance. The quoted sentence states that two things are "
    "necessary for adjudication. The claim does not specify that the subsequent purchaser must be a "
    "necessary party, but rather that they are a necessary party to the suit. The claim is broader "
    "than the quoted sentence. The claim is not fully supported by the quoted sentence because the "
    "quoted sentence does not state that the subsequent purchaser must be a necessary party."
)


class Answers:
    """A model that returns exactly what it is told to."""

    def __init__(self, assessment: ScopeAssessment) -> None:
        self._assessment = assessment

    def invoke(self, _prompt) -> ScopeAssessment:
        return self._assessment


@pytest.fixture
def candidates() -> list[Candidate]:
    return [Candidate(seq=69, printed_label="69", score=10.0, matched_terms=[], body=BODY)]


def _assess(candidates, **kwargs):
    base = {
        "support": "full",
        "quote": QUOTE,
        "paragraph_label": "69",
        "confidence": 0.9,
    }
    base.update(kwargs)
    return assess_scope(CLAIM, candidates, Answers(ScopeAssessment(**base)))


# --- the falsy zero ---------------------------------------------------------------------------------


def test_zero_confidence_is_the_least_confident_answer_not_the_most(candidates) -> None:
    """The gate was `if confidence and confidence < threshold`, so 0.0 skipped it entirely."""
    verdict = _assess(candidates, confidence=0.0)
    assert verdict.needs_review
    assert "0.00" in (verdict.review_reason or "")


def test_a_confidence_just_under_the_threshold_still_asks_for_review(candidates) -> None:
    verdict = _assess(candidates, confidence=MIN_CONFIDENCE_FOR_SUPPORT - 0.01)
    assert verdict.needs_review


def test_a_confident_answer_passes_without_review(candidates) -> None:
    verdict = _assess(candidates, confidence=0.9)
    assert verdict.support == "full"
    assert not verdict.needs_review


# --- an essay where a proposition belongs -----------------------------------------------------------


def test_reasoning_in_the_rewrite_field_is_discarded(candidates) -> None:
    """`drafting.render` sets this into the submission. An essay must never reach that."""
    verdict = _assess(candidates, support="partial", narrowed_proposition=ESSAY)
    assert verdict.narrowed_proposition is None
    assert verdict.needs_review
    assert "reasoning rather than a proposition" in (verdict.review_reason or "")


def test_a_real_rewrite_survives(candidates) -> None:
    rewrite = "A subsequent purchaser with prior knowledge of the earlier agreement is relevant to the adjudication"
    verdict = _assess(candidates, support="partial", narrowed_proposition=rewrite)
    assert verdict.narrowed_proposition == rewrite
    assert verdict.support == "partial"


def test_the_limit_scales_with_the_claim(candidates) -> None:
    """A long claim earns a long rewrite; the check is proportion, not a fixed sentence length."""
    rewrite = " ".join(["word"] * 39)
    verdict = _assess(candidates, support="partial", narrowed_proposition=rewrite)
    assert verdict.narrowed_proposition == rewrite


# --- full, and narrowed, at the same time -----------------------------------------------------------


def test_full_support_offered_with_a_narrowing_is_recorded_as_partial(candidates) -> None:
    """If the paragraph states the claim as broadly as the brief, there is nothing to narrow."""
    rewrite = "A subsequent purchaser with prior knowledge is relevant to the adjudication"
    verdict = _assess(candidates, support="full", narrowed_proposition=rewrite)
    assert verdict.support == "partial"
    assert verdict.needs_review
    assert "would not do if the paragraph stated the claim as broadly" in (verdict.review_reason or "")


def test_the_narrowing_survives_the_downgrade(candidates) -> None:
    """The advocate needs the narrower sentence, which is the whole value of catching this."""
    rewrite = "A subsequent purchaser with prior knowledge is relevant to the adjudication"
    verdict = _assess(candidates, support="full", narrowed_proposition=rewrite)
    assert verdict.narrowed_proposition == rewrite


def test_full_support_with_no_narrowing_is_left_alone(candidates) -> None:
    verdict = _assess(candidates, support="full", narrowed_proposition=None)
    assert verdict.support == "full"


def test_partial_support_with_a_narrowing_is_not_downgraded_further(candidates) -> None:
    rewrite = "A subsequent purchaser with prior knowledge is relevant to the adjudication"
    verdict = _assess(candidates, support="partial", narrowed_proposition=rewrite)
    assert verdict.support == "partial"


# --- and the case that started it -------------------------------------------------------------------


def test_the_binding_that_would_have_been_written_into_a_draft(candidates) -> None:
    """Exactly what came back from the live run: full, zero confidence, an essay in the rewrite."""
    verdict = _assess(candidates, support="full", confidence=0.0, narrowed_proposition=ESSAY)
    assert verdict.needs_review
    assert verdict.narrowed_proposition is None
    # The quote is genuine and verifies; that was never the problem.
    assert verdict.quote_verified
