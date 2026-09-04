"""Voice and opinion attribution: whose words is the brief relying on?

The cases here are the two failure modes that are invisible when a paragraph is read on its own: a
submission of counsel recited by the court (mode 5) and a passage from a dissent (mode 6). The tests
pin the rule that decides them, because the label a citation is marked down for has to be defensible
against the text rather than against a model's opinion.
"""

from __future__ import annotations

from orderorder.engine.locator import Candidate
from orderorder.engine.schemas import VoiceAssessment
from orderorder.engine.voice import attribute_voice, relied_on

ARGUMENT_THEN_ANSWER = (
    "Learned senior counsel appearing on behalf of the appellant submitted that a misrepresentation "
    "vitiates consent in every commercial contract, however slight the misstatement. We are unable to "
    "accept this submission. A misrepresentation vitiates consent only where it induced the contract."
)
COUNSEL_ONLY = (
    "It was strenuously contended that a misrepresentation vitiates consent in every commercial "
    "contract, and that the burden lies upon the party denying it."
)
COURT_ONLY = (
    "A misrepresentation vitiates consent only where it induced the contract, and the burden of "
    "proving inducement lies upon the party alleging it."
)


def _candidate(body: str, *, label: str = "5", opinion_kind: str | None = "majority", **kwargs) -> Candidate:
    return Candidate(
        seq=int(label) if label.isdigit() else 1,
        printed_label=label,
        score=1.0,
        matched_terms=["misrepresentation"],
        body=body,
        opinion_kind=opinion_kind,
        **kwargs,
    )


class StubModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def invoke(self, prompt: str):
        self.calls += 1
        return self.answer


def test_the_court_speaking_is_the_court() -> None:
    verdict = attribute_voice(_candidate(COURT_ONLY))
    assert verdict.voice == "court_majority"
    assert verdict.is_the_court
    assert not verdict.is_problem


def test_counsels_submission_is_not_the_court() -> None:
    verdict = attribute_voice(_candidate(COUNSEL_ONLY))
    assert verdict.voice == "counsel_argument"
    assert verdict.is_problem
    assert verdict.cue and "contended" in verdict.cue.lower()


def test_the_cue_nearest_the_quote_governs() -> None:
    """A paragraph that recites an argument and then rejects it carries two voices.

    The sentence the brief relies on comes after the court has taken the paragraph back, so it is the
    court's. Reading the paragraph as a whole would call the holding an argument.
    """
    body = ARGUMENT_THEN_ANSWER
    quote_start = body.index("A misrepresentation vitiates consent only")
    verdict = attribute_voice(_candidate(body), quote_start=quote_start)
    assert verdict.voice == "court_majority"


def test_a_quote_from_the_recited_argument_is_still_counsels() -> None:
    body = ARGUMENT_THEN_ANSWER
    quote_start = body.index("vitiates consent in every commercial contract")
    verdict = attribute_voice(_candidate(body), quote_start=quote_start)
    assert verdict.voice == "counsel_argument"
    assert verdict.is_problem


def test_without_a_quote_the_whole_paragraph_is_read_and_review_is_asked() -> None:
    """No verified quote means no way to tell which half of the paragraph was relied on."""
    verdict = attribute_voice(_candidate(COUNSEL_ONLY))
    assert verdict.needs_review


def test_a_dissent_is_reported_as_a_dissent() -> None:
    verdict = attribute_voice(_candidate(COURT_ONLY, opinion_kind="dissenting"))
    assert verdict.voice == "court_dissent"
    assert verdict.is_dissent
    assert not verdict.is_the_court
    # A dissent is the court speaking, so it is not a misattribution; it is a different finding.
    assert not verdict.is_problem


def test_a_concurrence_is_still_the_court() -> None:
    verdict = attribute_voice(_candidate(COURT_ONLY, opinion_kind="concurring"))
    assert verdict.voice == "court_concurring"
    assert verdict.is_the_court


def test_the_headnote_is_the_publishers_words() -> None:
    verdict = attribute_voice(_candidate(COURT_ONLY, opinion_kind="headnote"))
    assert verdict.voice == "headnote"
    assert verdict.is_problem
    assert verdict.method == "opinion"


def test_the_court_below_is_not_this_court() -> None:
    body = "The High Court held that the plaintiff was the dominus litis and could not be compelled."
    verdict = attribute_voice(_candidate(body))
    assert verdict.voice == "lower_court"
    assert verdict.is_problem


def test_a_quoted_precedent_is_flagged_until_endorsement_is_known() -> None:
    body = (
        "In Kesavananda Bharati v. State of Kerala, (1973) 4 SCC 225, this Court observed that the "
        "power to amend does not include the power to destroy the basic structure."
    )
    verdict = attribute_voice(_candidate(body))
    assert verdict.voice == "quoted_precedent"
    assert verdict.endorsed is None
    assert verdict.is_problem
    assert verdict.needs_review


def test_quoted_with_approval_is_the_courts_own() -> None:
    """Words a court adopts become its own, and the text says so without a model being asked."""
    body = (
        "In Kesavananda Bharati v. State of Kerala, (1973) 4 SCC 225, this Court observed that the "
        "basic structure cannot be destroyed. We respectfully agree with that statement of the law."
    )
    quote_start = body.index("the basic structure cannot be destroyed")
    verdict = attribute_voice(_candidate(body), quote_start=quote_start)
    assert verdict.voice == "quoted_precedent"
    assert verdict.endorsed is True
    assert not verdict.is_problem


def test_out_of_sequence_numbering_suggests_a_block_quotation() -> None:
    verdict = attribute_voice(_candidate(COURT_ONLY, label="118", likely_quoted=True))
    assert verdict.voice == "quoted_precedent"
    assert verdict.method == "sequence"
    assert verdict.needs_review


def test_the_model_answers_endorsement_only() -> None:
    body = (
        "In Gurmit Singh v. Kiran Kant, [2019] 9 S.C.R. 593, this Court held that the plaintiff is "
        "the dominus litis and cannot be compelled to add parties."
    )
    model = StubModel(VoiceAssessment(voice="court", endorsed=True, reason="The bench applied it."))
    verdict = attribute_voice(_candidate(body), model=model)
    assert model.calls == 1
    # The model said "court". It does not get to overrule the cue: the voice stays as the text shows,
    # and the model's answer changes only whether the quoted words were adopted.
    assert verdict.voice == "quoted_precedent"
    assert verdict.endorsed is True
    assert not verdict.is_problem


def test_a_model_failure_leaves_the_rule_finding_standing() -> None:
    class Failing:
        def invoke(self, prompt: str):
            raise RuntimeError("rate limited")

    body = "In A v. B, (2019) 1 SCC 1, this Court held that the appeal was maintainable."
    verdict = attribute_voice(_candidate(body), model=Failing())
    assert verdict.voice == "quoted_precedent"
    assert verdict.endorsed is None
    assert verdict.needs_review


def test_unknown_opinion_boundaries_are_reported_as_unclear() -> None:
    verdict = attribute_voice(_candidate(COURT_ONLY, opinion_kind=None))
    assert verdict.voice == "unclear"
    assert verdict.needs_review


def test_only_a_definite_paragraph_is_attributed() -> None:
    """A paragraph that merely ranked well is not attributed, because a guess must not become a label."""
    ranked = _candidate(COURT_ONLY, label="7")
    pinpointed = _candidate(COUNSEL_ONLY, label="9", is_claimed_pinpoint=True)

    assert relied_on([ranked, pinpointed], "7") is ranked  # the verified quote wins
    assert relied_on([ranked, pinpointed], None) is pinpointed  # else what the brief cited
    assert relied_on([ranked], None) is None  # a top-ranked guess is not enough


def test_a_cue_broken_across_a_line_reads_as_one_cue() -> None:
    """PDF text wraps mid-phrase; a finding that quotes the cue should not show the line break."""
    body = "It is submitted by the learned\nAdvocate for the appellant that the decree is a nullity."
    verdict = attribute_voice(_candidate(body))
    assert verdict.voice == "counsel_argument"
    assert verdict.cue == "learned Advocate"


def test_a_case_referred_to_as_supra_is_still_a_quoted_precedent() -> None:
    """Indian judgments refer back with "(supra)", which sits between the case name and the verb."""
    body = (
        "In Khet Singh vs. Union of India (supra) this Court held that even if there is any sort of "
        "procedural illegality in conducting the search, the evidence collected will not become "
        "inadmissible."
    )
    verdict = attribute_voice(_candidate(body))
    assert verdict.voice == "quoted_precedent"


def test_a_paragraph_carrying_two_voices_asks_for_review_when_nothing_pins_the_quote() -> None:
    """The court answered the argument, so the voice is the court's — but which half was relied on?

    With a verified quote the question is settled by where the quote sits. Without one, reporting a
    clean "court" would hide that half the paragraph is somebody else's words.
    """
    verdict = attribute_voice(_candidate(ARGUMENT_THEN_ANSWER))
    assert verdict.voice == "court_majority"
    assert verdict.needs_review
    assert verdict.cue == "on behalf of the appellant"
    # With the quote located, the same paragraph is answered without hesitation.
    settled = attribute_voice(
        _candidate(ARGUMENT_THEN_ANSWER),
        quote_start=ARGUMENT_THEN_ANSWER.index("A misrepresentation vitiates consent only"),
    )
    assert settled.voice == "court_majority"
    assert not settled.needs_review


def test_the_court_below_acting_at_a_distance_from_its_verb() -> None:
    """"The High Court has vide the impugned judgement held ..." — real wording from 2024 INSC 1027."""
    body = (
        "The High Court has vide the impugned judgement held Articles 13 and 14 of the Concession "
        "Agreement to be bad in law and directed NTBCL to cease the imposition of user fees."
    )
    verdict = attribute_voice(_candidate(body))
    assert verdict.voice == "lower_court"
    assert verdict.is_problem


def test_an_earlier_bench_named_before_the_case_is_still_a_quoted_precedent() -> None:
    """The commonest form of all, and the one a brief most often passes off as the holding.

    Taken from 2024 INSC: the reporter repeats the whole citation in brackets after the short name,
    so the cue has to survive lower-case letters inside those brackets.
    """
    body = (
        "A two-Judge Bench of this Court in Dolat Ram v. State of Haryana [Dolat Ram v. State of "
        "Haryana, (1995) 1 SCC 349 : 1995 SCC (Cri) 237] laid down the grounds for cancellation of "
        "bail which are: (i) interference with the due course of administration of justice."
    )
    verdict = attribute_voice(_candidate(body))
    assert verdict.voice == "quoted_precedent"
    assert verdict.is_problem


def test_a_constitution_bench_quoted_by_a_later_court() -> None:
    body = (
        "The Constitution Bench of this Court in Kesavananda Bharati v. State of Kerala held that the "
        "basic structure of the Constitution cannot be destroyed by an amendment."
    )
    assert attribute_voice(_candidate(body)).voice == "quoted_precedent"
