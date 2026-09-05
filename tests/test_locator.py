"""Locating the supporting paragraph, and checking the pinpoint a brief claimed.

The pinpoint tests reproduce the Delhi High Court incident of September 2025, where a petition cited
paragraphs 73 and 74 of a judgment containing 27 paragraphs.
"""

from __future__ import annotations

from orderorder.engine.locator import check_pinpoint, locate, verify_in_candidates
from orderorder.ingest.segment import segment

JUDGMENT = """1. Feeling aggrieved by the impugned judgment, the appellant preferred these appeals.

2. The facts of the case leading to these appeals in nutshell are as under.

2.1 The original plaintiffs filed a suit for specific performance of the agreement to sell.

3. A misrepresentation vitiates consent only where it induced the contract, and the burden
of proving inducement lies upon the party alleging it.

4. In view of the above, we are in complete agreement with the view taken by the High Court.
"""

PARAGRAPHS = segment(JUDGMENT)


def test_the_corpus_segments_as_expected() -> None:
    assert [p.printed_label for p in PARAGRAPHS] == ["1", "2", "2.1", "3", "4"]


def test_locates_the_supporting_paragraph() -> None:
    result = locate(PARAGRAPHS, "a misrepresentation vitiates consent where it induced the contract")
    assert result.best is not None
    assert result.best.printed_label == "3"


def test_candidates_are_ranked_best_first() -> None:
    result = locate(PARAGRAPHS, "specific performance agreement to sell plaintiffs suit")
    assert result.best.printed_label == "2.1"
    assert result.candidates[0].score >= result.candidates[-1].score


def test_query_terms_are_reported() -> None:
    result = locate(PARAGRAPHS, "misrepresentation vitiates consent")
    assert "misrepresentation" in result.query_terms


def test_pinpoint_that_exists_is_ok() -> None:
    check = check_pinpoint(PARAGRAPHS, "3")
    assert check.status == "ok"
    assert not check.is_problem


def test_sub_paragraph_pinpoint_is_ok() -> None:
    assert check_pinpoint(PARAGRAPHS, "2.1").status == "ok"


def test_pinpoint_beyond_the_judgment_is_caught() -> None:
    """The Delhi High Court case: paragraph 73 of a judgment that stops well short of it."""
    check = check_pinpoint(PARAGRAPHS, "73")
    assert check.status == "out_of_range"
    assert check.is_problem
    assert "stops at" in check.note
    assert check.highest_label == "4"


def test_pinpoint_inside_the_range_but_absent_is_caught() -> None:
    gappy = segment("1. First point.\n\n2. Second point.\n\n9. Ninth point.\n\n10. Tenth point.")
    check = check_pinpoint(gappy, "5")
    assert check.status == "not_in_judgment"
    assert check.is_problem


def test_no_pinpoint_claimed() -> None:
    check = check_pinpoint(PARAGRAPHS, None)
    assert check.status == "none_claimed"
    assert not check.is_problem


def test_cited_paragraph_is_always_a_candidate() -> None:
    """Even when it does not match the proposition, so the verdict can say it does not support it."""
    result = locate(PARAGRAPHS, "misrepresentation vitiates consent", claimed_pinpoint="1")
    labels = [c.printed_label for c in result.candidates]
    assert "1" in labels
    assert any(c.is_claimed_pinpoint for c in result.candidates)


def test_cited_paragraph_is_not_promoted_above_a_better_match() -> None:
    result = locate(PARAGRAPHS, "misrepresentation vitiates consent inducement", claimed_pinpoint="1")
    assert result.best.printed_label == "3"


def test_verify_in_candidates_finds_the_right_paragraph() -> None:
    result = locate(PARAGRAPHS, "misrepresentation vitiates consent")
    quote = "A misrepresentation vitiates consent only where it induced the contract"
    candidate, match = verify_in_candidates(quote, result.candidates)
    assert candidate is not None
    assert candidate.printed_label == "3"
    assert match.found
    assert match.match_type == "exact"


def test_invented_quote_matches_no_candidate() -> None:
    """A model that invents a plausible sentence must not be able to ground it."""
    result = locate(PARAGRAPHS, "misrepresentation vitiates consent")
    candidate, match = verify_in_candidates(
        "A misrepresentation always renders the contract void from the beginning", result.candidates
    )
    assert candidate is None
    assert not match.found


def test_empty_judgment_is_safe() -> None:
    result = locate([], "anything at all")
    assert result.candidates == []
    assert result.best is None


# --- the pinpoint that exists but is not the one -------------------------------------------------

CLAIM_FROM_THREE = (
    "A misrepresentation vitiates consent only where it induced the contract, and the burden "
    "of proving inducement lies upon the party alleging it."
)


def test_a_pinpoint_naming_a_paragraph_the_words_are_not_in_is_caught() -> None:
    """The commonest wrong pinpoint: the paragraph exists, the words are three paragraphs away."""
    check = check_pinpoint(PARAGRAPHS, "1", CLAIM_FROM_THREE)
    assert check.status == "wrong_paragraph"
    assert check.is_problem
    assert check.exists  # it is a real paragraph; it is the wrong one
    assert check.found_at == "3"
    assert check.anchor and "vitiates consent only where it induced" in check.anchor


def test_the_right_pinpoint_stays_ok() -> None:
    assert check_pinpoint(PARAGRAPHS, "3", CLAIM_FROM_THREE).status == "ok"


def test_a_paraphrase_is_not_evidence_of_a_wrong_pinpoint() -> None:
    """Advocates paraphrase. Without a verbatim run there is nothing to say, and nothing is said."""
    paraphrase = "Consent is vitiated by a false statement that caused the party to enter the bargain."
    assert check_pinpoint(PARAGRAPHS, "1", paraphrase).status == "ok"


def test_without_a_proposition_the_check_only_asks_whether_the_paragraph_exists() -> None:
    """The pinpoint check is used where no claim is in hand, and must not invent a finding there."""
    assert check_pinpoint(PARAGRAPHS, "1").status == "ok"


def test_a_pinpoint_that_does_not_exist_is_still_reported_as_such() -> None:
    """Not-there beats wrong-paragraph: naming paragraph 73 of a five-paragraph judgment is worse."""
    check = check_pinpoint(PARAGRAPHS, "73", CLAIM_FROM_THREE)
    assert check.status == "out_of_range"
    assert not check.exists


def test_the_wrong_pinpoint_reaches_the_candidate_ranking() -> None:
    result = locate(PARAGRAPHS, CLAIM_FROM_THREE, claimed_pinpoint="1")
    assert result.pinpoint.status == "wrong_paragraph"
    assert result.best is not None and result.best.printed_label == "3"
