"""The second reading: what does the claim assert that the quote does not state?

This exists because of three citations the engine bound to paragraphs that did not support them.
Every quote was genuine, verbatim, correctly attributed and from good law, so nothing structural was
wrong with any of them -- the first model had simply answered `full` where the honest answer was
`partial` or `none`. The example that runs through this file is the real one:

    claim: a subsequent purchaser ... is a *necessary party* to a suit for specific performance
    quote: two things are necessary *for the adjudication* -- readiness and willingness, and whether
           the transferee had prior knowledge

One is about who must be joined; the other about what must be decided. Only reading the two texts
against each other finds that, which is what this does.

The properties that matter are the asymmetry -- it may lower support and never raise it -- and that
every way of failing to get an answer is treated as no answer rather than as agreement.
"""

from __future__ import annotations

import pytest

from orderorder.engine.challenge import GAP, NOT_RUN, UPHELD, challenge
from orderorder.engine.locator import Candidate
from orderorder.engine.schemas import ChallengeAssessment, ScopeAssessment
from orderorder.engine.scope import assess_scope

CLAIM = "A subsequent purchaser who holds a prior agreement to sell is a necessary party to the suit"
BODY = (
    "In a suit for specific performance where the property has been sold to a subsequent purchaser, "
    "two things are necessary for the adjudication, namely whether the plaintiff remained ready and "
    "willing to perform his part of the contract, and whether the subsequent transferee had prior "
    "knowledge of the earlier agreement executed in favour of the plaintiff."
)
QUOTE = "two things are necessary for the adjudication"


class Says:
    """A model that returns what it is told to, or raises."""

    def __init__(self, answer=None, *, raises: type[Exception] | None = None) -> None:
        self._answer = answer
        self._raises = raises

    def invoke(self, _prompt):
        if self._raises is not None:
            raise self._raises("no")
        return self._answer


@pytest.fixture
def candidates() -> list[Candidate]:
    return [Candidate(seq=69, printed_label="69", score=10.0, matched_terms=[], body=BODY)]


def _first_reading(**kwargs) -> Says:
    base = {"support": "full", "quote": QUOTE, "paragraph_label": "69", "confidence": 0.9}
    base.update(kwargs)
    return Says(ScopeAssessment(**base))


def _second_reading(**kwargs) -> Says:
    base = {"states_the_claim": True, "missing": [], "reason": None}
    base.update(kwargs)
    return Says(ChallengeAssessment(**base))


# --- the reading on its own -------------------------------------------------------------------------


def test_a_gap_is_reported_with_what_is_missing() -> None:
    reading = challenge(
        CLAIM,
        QUOTE,
        _second_reading(
            states_the_claim=False,
            missing=["that the subsequent purchaser must be joined as a party"],
            reason="the sentence is about what must be decided, not who must be joined",
        ),
    )
    assert reading.status == GAP
    assert reading.found_a_gap
    assert "who must be joined" in reading.describe()


def test_a_quote_that_states_the_claim_is_upheld() -> None:
    reading = challenge(CLAIM, QUOTE, _second_reading())
    assert reading.status == UPHELD
    assert not reading.found_a_gap
    assert reading.describe() == ""


def test_yes_with_a_list_of_omissions_is_a_gap() -> None:
    """A model that says the sentence states the claim and then lists what it omits contradicts itself."""
    reading = challenge(CLAIM, QUOTE, _second_reading(states_the_claim=True, missing=["joinder"]))
    assert reading.status == GAP


def test_no_model_is_no_answer_rather_than_agreement() -> None:
    reading = challenge(CLAIM, QUOTE, None)
    assert reading.status == NOT_RUN
    assert not reading.found_a_gap


def test_an_outage_is_no_answer_rather_than_a_gap() -> None:
    """An unreachable provider is not evidence against a citation."""
    reading = challenge(CLAIM, QUOTE, Says(raises=ConnectionError))
    assert reading.status == NOT_RUN
    assert not reading.found_a_gap


def test_a_malformed_answer_is_no_answer() -> None:
    assert challenge(CLAIM, QUOTE, Says("not a schema at all")).status == NOT_RUN


def test_nothing_to_challenge_is_not_a_gap() -> None:
    assert challenge(CLAIM, "", _second_reading(states_the_claim=False)).status == NOT_RUN


# --- what it does to a verdict ----------------------------------------------------------------------


def test_full_support_drops_to_partial_when_the_second_reading_finds_a_gap(candidates) -> None:
    """The case this was built for."""
    verdict = assess_scope(
        CLAIM,
        candidates,
        _first_reading(),
        challenge_model=_second_reading(
            states_the_claim=False,
            missing=["that the purchaser must be joined"],
            reason="the sentence is about what must be decided, not who must be joined",
        ),
    )
    assert verdict.support == "partial"
    assert verdict.needs_review
    assert "second reading" in (verdict.review_reason or "")
    assert verdict.challenge is not None
    assert verdict.challenge.found_a_gap


def test_an_upheld_quote_is_left_exactly_as_it_was(candidates) -> None:
    verdict = assess_scope(CLAIM, candidates, _first_reading(), challenge_model=_second_reading())
    assert verdict.support == "full"
    assert not verdict.needs_review
    assert verdict.challenge is not None
    assert verdict.challenge.status == UPHELD


def test_the_second_reading_can_never_raise_support(candidates) -> None:
    """A broken or absent challenge makes the engine more cautious, never less."""
    generous = _second_reading(states_the_claim=True)
    verdict = assess_scope(CLAIM, candidates, _first_reading(support="partial"), challenge_model=generous)
    assert verdict.support == "partial"


def test_an_unverified_quote_is_never_challenged(candidates) -> None:
    """Nothing to read back: the quote failed the string check, and support is already gone."""
    verdict = assess_scope(
        CLAIM,
        candidates,
        _first_reading(quote="a sentence that is not in this judgment anywhere at all"),
        challenge_model=_second_reading(states_the_claim=False, missing=["everything"]),
    )
    assert verdict.support == "none"
    assert verdict.challenge is None


def test_a_refusal_is_never_challenged(candidates) -> None:
    """The extra call is only worth paying where a mistake would become a citation."""
    verdict = assess_scope(
        CLAIM,
        candidates,
        _first_reading(support="none", quote=None),
        challenge_model=_second_reading(states_the_claim=False, missing=["everything"]),
    )
    assert verdict.challenge is None


def test_an_outage_in_the_second_reading_leaves_the_first_standing(candidates) -> None:
    verdict = assess_scope(
        CLAIM, candidates, _first_reading(), challenge_model=Says(raises=ConnectionError)
    )
    assert verdict.support == "full"
    assert verdict.challenge is not None
    assert verdict.challenge.status == NOT_RUN


def test_the_gap_reaches_the_advocate(candidates) -> None:
    """A downgrade nobody can read is a downgrade nobody can act on."""
    verdict = assess_scope(
        CLAIM,
        candidates,
        _first_reading(),
        challenge_model=_second_reading(
            states_the_claim=False,
            missing=["joinder"],
            reason="the sentence is about what must be decided, not who must be joined",
        ),
    )
    assert "who must be joined" in (verdict.gap or "")
