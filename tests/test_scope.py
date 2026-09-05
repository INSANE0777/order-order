"""The scope comparator: does the paragraph support the claim, and how far.

These tests run a stub model, so they need no API key and no network. That is the point of the design:
the model's answer is data to be checked, so a stub that returns a chosen answer exercises exactly the
logic that protects the verdict. The cases that matter most are the dishonest ones, where the model
claims support it cannot ground.
"""

from __future__ import annotations

from orderorder.engine.locator import Candidate
from orderorder.engine.schemas import AtomicClaim, ClaimDecomposition, ScopeAssessment
from orderorder.engine.scope import MIN_CONFIDENCE_FOR_SUPPORT, assess_scope, decompose_claim

PARAGRAPH = (
    "A misrepresentation vitiates consent only where it induced the contract, and the burden of "
    "proving inducement lies upon the party alleging it."
)
OTHER = "The plaintiff is the dominus litis and cannot be compelled to implead an unwilling party."

CANDIDATES = [
    Candidate(seq=3, printed_label="3", score=9.1, matched_terms=["misrepresentation"], body=PARAGRAPH),
    Candidate(seq=5, printed_label="5", score=2.0, matched_terms=["party"], body=OTHER),
]

CLAIM = "A misrepresentation vitiates consent."


class StubModel:
    """Returns a prepared answer and records the prompt it was given."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return self.answer


def _assessment(**kwargs) -> ScopeAssessment:
    base = {
        "paragraph_label": "3",
        "quote": "A misrepresentation vitiates consent only where it induced the contract",
        "support": "partial",
        "dropped_conditions": ["where the misrepresentation induced the contract"],
        "court_modality": "must",
        "gap": "The court confined the rule to inducement; the brief states it unconditionally.",
        "narrowed_proposition": "A misrepresentation that induced the contract vitiates consent.",
        "confidence": 0.9,
    }
    base.update(kwargs)
    return ScopeAssessment(**base)


# --- the honest path ----------------------------------------------------------


def test_partial_support_with_a_real_quote_is_accepted() -> None:
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(_assessment()))
    assert verdict.support == "partial"
    assert verdict.quote_verified
    assert verdict.quote_match_type == "exact"
    assert verdict.matched_paragraph_label == "3"
    assert not verdict.needs_review


def test_overstatement_is_reported_with_the_dropped_condition() -> None:
    """The central case: the court held it only on a condition the brief leaves out."""
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(_assessment()))
    assert verdict.overstated
    assert verdict.dropped_conditions == ["where the misrepresentation induced the contract"]
    assert "unconditionally" in verdict.gap
    assert verdict.narrowed_proposition.startswith("A misrepresentation that induced")


def test_offsets_point_at_the_quote_in_the_paragraph() -> None:
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(_assessment()))
    assert PARAGRAPH[verdict.char_start : verdict.char_end] == verdict.quote


def test_full_support_is_preserved() -> None:
    """Full support means the paragraph states the claim as broadly as the brief does.

    So the answer has to be coherent: no dropped condition, no gap, and nothing to narrow. An answer
    that says `full` and offers a narrowing in the same breath contradicts itself, and
    `test_scope_incoherence` covers what the engine does with that.
    """
    verdict = assess_scope(
        CLAIM,
        CANDIDATES,
        StubModel(
            _assessment(support="full", dropped_conditions=[], gap=None, narrowed_proposition=None)
        ),
    )
    assert verdict.support == "full"
    assert verdict.is_supported
    assert not verdict.overstated


# --- the dishonest paths, which the checking exists for -----------------------


def test_invented_quote_downgrades_the_claim() -> None:
    """A model that claims support with a sentence not in the judgment must not be believed."""
    fabricated = _assessment(
        quote="A misrepresentation always renders the contract void from the very beginning",
        support="full",
    )
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(fabricated))
    assert verdict.model_support == "full"
    assert verdict.support == "none"
    assert not verdict.quote_verified
    assert verdict.needs_review
    assert "does not appear in the judgment" in verdict.review_reason


def test_support_claimed_without_a_quote_is_downgraded() -> None:
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(_assessment(quote=None, support="full")))
    assert verdict.support == "none"
    assert verdict.quote_match_type == "missing"
    assert verdict.needs_review


def test_quote_too_short_to_verify_is_downgraded() -> None:
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(_assessment(quote="vitiates consent")))
    assert verdict.support == "none"
    assert verdict.quote_match_type == "too_short"
    assert verdict.needs_review


def test_near_miss_paraphrase_is_not_accepted() -> None:
    """One word changed. Born-digital text never fuzzy-matches, so this must fail."""
    near = _assessment(quote="A misrepresentation vitiates consent whenever it preceded the contract")
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(near))
    assert verdict.support == "none"
    assert not verdict.quote_verified


def test_right_quote_wrong_paragraph_is_recorded() -> None:
    """The quote is real but the model named the wrong paragraph: a pinpoint error, not a fabrication."""
    misplaced = _assessment(paragraph_label="5")
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(misplaced))
    assert verdict.support == "partial"
    assert verdict.quote_verified
    assert verdict.wrong_pinpoint
    assert verdict.matched_paragraph_label == "3"


def test_low_confidence_is_flagged_for_review() -> None:
    low = _assessment(confidence=MIN_CONFIDENCE_FOR_SUPPORT - 0.1)
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(low))
    assert verdict.needs_review
    assert "confidence" in verdict.review_reason


def test_malformed_model_output_is_handled() -> None:
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel("not a schema instance"))
    assert verdict.support == "none"
    assert verdict.model_support == "malformed"
    assert verdict.needs_review


# --- no support claimed -------------------------------------------------------


def test_none_needs_no_quote() -> None:
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(_assessment(support="none", quote=None)))
    assert verdict.support == "none"
    assert verdict.quote_match_type == "not_required"
    assert not verdict.needs_review


def test_contradicted_is_preserved() -> None:
    verdict = assess_scope(CLAIM, CANDIDATES, StubModel(_assessment(support="contradicted", quote=None)))
    assert verdict.support == "contradicted"
    assert not verdict.is_supported


# --- degraded and empty conditions -------------------------------------------


def test_without_a_model_nothing_is_asserted() -> None:
    verdict = assess_scope(CLAIM, CANDIDATES, None)
    assert verdict.support == "none"
    assert verdict.needs_review
    assert "no language model is configured" in verdict.review_reason


def test_without_candidates_nothing_is_asserted() -> None:
    """Retrieving nothing means the question was never put, not that the judgment fails to support it."""
    verdict = assess_scope(CLAIM, [], StubModel(_assessment()))
    assert verdict.model_support == "not_assessed"
    assert verdict.needs_review
    assert "was not assessed" in verdict.review_reason


# --- the prompt ---------------------------------------------------------------


def test_prompt_carries_the_claim_and_the_candidates() -> None:
    model = StubModel(_assessment())
    assess_scope(CLAIM, CANDIDATES, model)
    prompt = model.prompts[0]
    assert CLAIM in prompt
    assert "[paragraph 3]" in prompt
    assert "vitiates consent" in prompt


def test_prompt_tells_the_model_its_quote_will_be_checked() -> None:
    model = StubModel(_assessment())
    assess_scope(CLAIM, CANDIDATES, model)
    assert "checked against the judgment" in model.prompts[0]


# --- claim decomposition ------------------------------------------------------


def test_decomposition_splits_a_compound_proposition() -> None:
    answer = ClaimDecomposition(
        claims=[
            AtomicClaim(text="Fraud vitiates all solemn acts."),
            AtomicClaim(text="A party may avoid the contract."),
        ]
    )
    claims = decompose_claim(
        "Fraud vitiates all solemn acts and a party may avoid the contract.", StubModel(answer)
    )
    assert len(claims) == 2


def test_decomposition_without_a_model_keeps_one_claim() -> None:
    claims = decompose_claim("Fraud vitiates all solemn acts.", None)
    assert len(claims) == 1
    assert claims[0].text == "Fraud vitiates all solemn acts."


def test_decomposition_falls_back_when_the_model_returns_nothing() -> None:
    claims = decompose_claim("Fraud vitiates.", StubModel(ClaimDecomposition(claims=[])))
    assert len(claims) == 1
