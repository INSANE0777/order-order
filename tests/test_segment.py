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
