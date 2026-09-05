"""Paragraph segmentation decides what a pinpoint can point at."""

from __future__ import annotations

from orderorder.ingest.segment import label_index, segment

JUDGMENT = """JUDGMENT

1. This appeal arises out of a suit for specific performance filed by the
respondent against the appellant.

2. The trial court decreed the suit. The High Court affirmed that decree.

23. A misrepresentation vitiates consent only where it induced the contract,
and the burden of proving inducement lies upon the party alleging it.

24. In the result, the appeal is allowed.
"""


def test_finds_numbered_paragraphs() -> None:
    paragraphs = segment(JUDGMENT)
    labels = [p.printed_label for p in paragraphs if p.printed_label]
    assert labels == ["1", "2", "23", "24"]


def test_labels_are_stripped_from_the_body() -> None:
    paragraphs = segment(JUDGMENT)
    by_label = label_index(paragraphs)
    assert by_label["23"].body.startswith("A misrepresentation vitiates consent")


def test_wrapped_lines_are_rejoined() -> None:
    by_label = label_index(segment(JUDGMENT))
    assert "\n" not in by_label["1"].body
    assert "filed by the respondent" in by_label["1"].body


def test_offsets_point_back_into_the_source() -> None:
    for paragraph in segment(JUDGMENT):
        assert JUDGMENT[paragraph.char_start : paragraph.char_end].strip()


def test_sequence_is_contiguous_and_starts_at_one() -> None:
    paragraphs = segment(JUDGMENT)
    assert [p.seq for p in paragraphs] == list(range(1, len(paragraphs) + 1))


def test_printed_labels_may_skip_numbers() -> None:
    """Paragraph 3 to 22 are missing here; sequence must not be confused with the printed label."""
    by_label = label_index(segment(JUDGMENT))
    assert by_label["23"].seq != 23


def test_bracketed_and_parenthesised_labels() -> None:
    text = "[5] The first point.\n\n(6) The second point.\n\nPara 7. The third point."
    labels = [p.printed_label for p in segment(text) if p.printed_label]
    assert labels == ["5", "6", "7"]


def test_unnumbered_text_still_segments() -> None:
    text = "The first paragraph has no number.\n\nNor does the second one."
    paragraphs = segment(text)
    assert len(paragraphs) == 2
    assert all(p.printed_label is None for p in paragraphs)


def test_hyphenated_line_break_is_repaired() -> None:
    text = "1. The misrepresen-\ntation was material to the bargain."
    body = segment(text)[0].body
    assert "misrepresentation" in body


def test_empty_input() -> None:
    assert segment("") == []


# --- quoted-passage detection -------------------------------------------------
#
# A court numbers its own paragraphs in order. A judgment that quotes another judgment at length
# reproduces that judgment's numbering, so a high label lands among lower ones. Attributing such a
# paragraph to the citing court is failure mode 5, so the break in sequence is worth detecting.

from orderorder.ingest.segment import find_out_of_sequence, label_value  # noqa: E402


def test_label_value_orders_sub_paragraphs() -> None:
    assert label_value("5") == 5.0
    assert label_value("5.1") == 5.01
    assert 5.0 < label_value("5.1") < 6.0
    assert label_value(None) is None
    assert label_value("preamble") is None


def test_out_of_sequence_label_is_flagged() -> None:
    """The real shape from [2019] 9 S.C.R. 593: paragraph 16 sits between 5.2 and 6."""
    text = "\n\n".join(
        [
            "1. First point of the court.",
            "5. We have heard the learned counsel.",
            "5.2 An identical question came before this Court.",
            "16. That apart, from a plain reading of the expression used.",
            "6. Now so far as the reliance placed upon the decision.",
            "7. In view of the above the appeals are dismissed.",
        ]
    )
    paragraphs = segment(text)
    flagged = find_out_of_sequence(paragraphs)
    quoted = {p.printed_label for p in paragraphs if p.seq in flagged}
    assert quoted == {"16"}


def test_ascending_labels_are_never_flagged() -> None:
    text = "\n\n".join(f"{n}. Paragraph number {n} of the judgment." for n in range(1, 9))
    assert find_out_of_sequence(segment(text)) == set()


def test_sub_paragraphs_do_not_trip_the_detector() -> None:
    text = "\n\n".join(
        ["1. First.", "2. Second.", "2.1 Second part one.", "2.2 Second part two.", "3. Third."]
    )
    assert find_out_of_sequence(segment(text)) == set()


def test_too_few_labels_to_judge() -> None:
    assert find_out_of_sequence(segment("9. Only one labelled paragraph here.")) == set()


def _flagged_labels(text: str) -> set[str]:
    paragraphs = segment(text)
    flagged = find_out_of_sequence(paragraphs)
    return {p.printed_label for p in paragraphs if p.seq in flagged}


def test_a_quoted_block_that_climbs_past_the_court_does_not_poison_the_rest() -> None:
    """The failure that the walk-forwards rule could not survive.

    A judgment numbering itself 1 to 6.5 quotes ten paragraphs numbered 1 to 10. Carrying a mark of
    where the numbering has reached pushes that mark to 10, and the court's own 6.6 onwards then falls
    below it — one quotation condemning the whole tail of the judgment.
    """
    own = ["1.", "2.", "3.", "4.", "5.", "6.", "6.1", "6.2", "6.3", "6.4", "6.5"]
    quotation = [f"{n}." for n in range(1, 11)]
    rest = ["6.6", "6.7", "7.", "7.1", "8.", "9.", "10."]
    text = "\n\n".join(
        f"{label} Sentence belonging to paragraph {label} of this judgment."
        for label in own + quotation + rest
    )
    flagged = find_out_of_sequence(segment(text))
    # Exactly the quotation, and nothing of the court's own before or after it. The labels alone
    # cannot say this - 7, 8, 9 and 10 appear in both - so it is the positions that are checked.
    quoted_positions = set(range(len(own) + 1, len(own) + len(quotation) + 1))
    assert flagged == quoted_positions


def test_the_courts_own_numbering_wins_even_when_the_quotation_is_longer() -> None:
    """Length alone does not decide: the court's numbering is the one that starts the judgment.

    Here the quoted block borrows the judgment's closing paragraphs to finish on, so the ascending run
    through the quotation is the longer of the two. It is still not the court's.
    """
    own = [str(n) for n in range(2, 12)]
    quotation = ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9"]
    rest = [str(n) for n in range(12, 20)]
    text = "\n\n".join(
        f"{label}. Sentence belonging to paragraph {label}."
        if "." not in label
        else f"{label} Sentence belonging to paragraph {label}."
        for label in own + quotation + rest
    )
    assert _flagged_labels(text) == set(quotation)


def test_the_courts_own_paragraphs_win_a_tie_with_their_own_quotation() -> None:
    """A judgment that quotes its own earlier paragraphs back offers two runs of equal length."""
    text = "\n\n".join(
        f"{label}. Sentence belonging to paragraph {label}."
        for label in ["1", "2", "3", "4", "5", "3", "4", "5", "6", "7"]
    )
    paragraphs = segment(text)
    flagged = find_out_of_sequence(paragraphs)
    # The three flagged are the second 3, 4 and 5 — the later copies, not the court's own.
    assert sorted(flagged) == [6, 7, 8]


def test_numbering_too_damaged_to_read_says_nothing() -> None:
    """Column-formatted reports extract out of order; there the labels carry no signal at all."""
    text = "\n\n".join(
        f"{label}. Sentence belonging to paragraph {label}."
        # Three columns of a printed report read out of order: each block descends, so no ascending
        # run through the judgment is any more credible than another.
        for label in ["5", "4", "3", "2", "1", "10", "9", "8", "7", "6", "15", "14", "13", "12", "11"]
    )
    assert find_out_of_sequence(segment(text)) == set()
