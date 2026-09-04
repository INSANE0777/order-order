"""Ratio or obiter, and the abstention that keeps it honest.

Failure mode 7. The rule these tests protect is that `unclear` costs a citation nothing: a
classification only counts when the court's own words carry it, or when a model's answer quotes a
sentence that verifies against the paragraph. Calling a holding a passing remark is as damaging as
calling a remark a holding, so the classifier abstains rather than guesses.
"""

from __future__ import annotations

from orderorder.engine.locator import Candidate
from orderorder.engine.schemas import WeightAssessment
from orderorder.engine.voice import VoiceVerdict
from orderorder.engine.weight import classify_weight, find_disposition
from orderorder.ingest.segment import SegParagraph

CLAIM = "A misrepresentation vitiates consent."
HOLDING = (
    "A misrepresentation vitiates consent only where it induced the contract, and the burden of "
    "proving inducement lies upon the party alleging it."
)
ASIDE = (
    "We may observe in passing that the practice of filing bulky compilations without an index "
    "deserves reconsideration by the Bar, though nothing turns on it in this appeal."
)
DECLINED = (
    "It is not necessary for us to decide whether a misrepresentation as to value stands on the same "
    "footing, since the appeal succeeds on the finding of inducement."
)

MAJORITY = VoiceVerdict(voice="court_majority", opinion_kind="majority")
COUNSEL = VoiceVerdict(voice="counsel_argument", cue="it was contended")


def _candidate(body: str, label: str = "12") -> Candidate:
    return Candidate(seq=12, printed_label=label, score=1.0, matched_terms=[], body=body)


class StubModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def invoke(self, prompt: str):
        self.calls += 1
        return self.answer


def test_the_court_declining_to_decide_is_obiter_without_a_model() -> None:
    verdict = classify_weight(_candidate(DECLINED), CLAIM, voice=MAJORITY)
    assert verdict.label == "obiter"
    assert verdict.method == "rule"
    assert verdict.is_obiter
    assert verdict.cue and "not necessary" in verdict.cue.lower()


def test_an_aside_announced_as_one_is_obiter() -> None:
    verdict = classify_weight(_candidate(ASIDE), CLAIM, voice=MAJORITY)
    assert verdict.label == "obiter"
    assert verdict.method == "rule"


def test_with_no_model_and_no_cue_the_answer_is_unclear_not_ratio() -> None:
    verdict = classify_weight(_candidate(HOLDING), CLAIM, voice=MAJORITY)
    assert verdict.label == "unclear"
    assert verdict.method == "not_assessed"
    assert not verdict.is_obiter


def test_counsels_argument_is_neither_ratio_nor_obiter() -> None:
    model = StubModel(WeightAssessment(label="obiter", quote=HOLDING[:40], confidence=0.9))
    verdict = classify_weight(_candidate(HOLDING), CLAIM, voice=COUNSEL, model=model)
    assert verdict.label == "unclear"
    assert verdict.method == "voice"
    assert model.calls == 0


def test_a_grounded_model_answer_is_kept() -> None:
    model = StubModel(
        WeightAssessment(
            label="ratio",
            necessary_to_outcome=True,
            quote="the burden of proving inducement lies upon the party alleging it",
            reason="The appeal turned on inducement.",
            confidence=0.8,
        )
    )
    verdict = classify_weight(_candidate(HOLDING), CLAIM, voice=MAJORITY, model=model)
    assert verdict.label == "ratio"
    assert verdict.quote_verified
    assert verdict.prompt_version == "weight-v1"
    assert not verdict.is_obiter


def test_an_ungrounded_obiter_answer_is_downgraded_to_unclear() -> None:
    """A model that cannot quote the sentence it relies on does not get to cost a citation a grade."""
    model = StubModel(
        WeightAssessment(
            label="obiter",
            quote="the court was merely thinking aloud about the matter",
            confidence=0.95,
        )
    )
    verdict = classify_weight(_candidate(HOLDING), CLAIM, voice=MAJORITY, model=model)
    assert verdict.label == "unclear"
    assert not verdict.quote_verified
    assert verdict.needs_review
    assert not verdict.is_obiter


def test_an_answer_without_a_quote_is_downgraded_to_unclear() -> None:
    model = StubModel(WeightAssessment(label="obiter", quote=None, confidence=0.9))
    verdict = classify_weight(_candidate(HOLDING), CLAIM, voice=MAJORITY, model=model)
    assert verdict.label == "unclear"
    assert verdict.needs_review


def test_a_quote_too_short_to_verify_is_downgraded() -> None:
    model = StubModel(WeightAssessment(label="obiter", quote="in passing", confidence=0.9))
    verdict = classify_weight(_candidate(HOLDING), CLAIM, voice=MAJORITY, model=model)
    assert verdict.label == "unclear"


def test_low_confidence_asks_for_review_without_losing_the_answer() -> None:
    model = StubModel(
        WeightAssessment(
            label="ratio",
            quote="the burden of proving inducement lies upon the party alleging it",
            confidence=0.2,
        )
    )
    verdict = classify_weight(_candidate(HOLDING), CLAIM, voice=MAJORITY, model=model)
    assert verdict.label == "ratio"
    assert verdict.needs_review


def test_a_provider_outage_is_reported_as_unassessed() -> None:
    class Failing:
        def invoke(self, prompt: str):
            raise RuntimeError("all providers exhausted")

    verdict = classify_weight(_candidate(HOLDING), CLAIM, voice=MAJORITY, model=Failing())
    assert verdict.label == "unclear"
    assert verdict.method == "not_assessed"
    assert not verdict.is_obiter


def test_the_disposition_paragraph_is_found_from_the_end() -> None:
    paragraphs = [
        SegParagraph(1, "1", "The appeals are listed for hearing on merits.", 0, 40),
        SegParagraph(2, "2", HOLDING, 41, 200),
        SegParagraph(3, "3", "For the reasons stated above, the appeals are dismissed.", 201, 260),
    ]
    disposition = find_disposition(paragraphs)
    assert disposition is not None
    assert disposition.printed_label == "3"


def test_no_disposition_paragraph_is_not_an_error() -> None:
    assert find_disposition([SegParagraph(1, "1", HOLDING, 0, 100)]) is None


def test_the_disposition_wording_courts_actually_use_is_recognised() -> None:
    """Read off real Supreme Court judgments, not invented: each of these ends a real one."""
    endings = [
        "In view of the aforesaid, the appeal succeeds and is hereby allowed.",
        "In view of the above, the appeal fails and is hereby dismissed.",
        "The Appeal stands allowed. Result of the case: Appeal allowed.",
        "We accordingly pass the following order: (i) The appeal is allowed;",
        "We are in complete agreement with the view taken by the High Court. No interference of "
        "this Court is called for.",
        "The impugned judgment of the High Court is accordingly set aside for not being sustainable in law.",
    ]
    for text in endings:
        assert find_disposition([SegParagraph(1, "1", text, 0, len(text))]) is not None, text
