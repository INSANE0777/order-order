"""The annotated brief and the verification report.

Both are built from the verdicts and nothing else, so what these tests hold is that nothing gets
lost between the verdict and the document: a citation the engine graded must appear, a marker must
land beside the citation it belongs to rather than beside the next one along, and a check that could
not run must be named rather than passed over in silence.
"""

from __future__ import annotations

from orderorder.engine.report import annotate_brief, verification_report
from orderorder.engine.verdict import (
    MODE_DEAD_LAW,
    MODE_WRONG_PINPOINT,
    CitationVerdict,
    Finding,
)

BRIEF = (
    "1. The appellant cannot be impleaded, as held in (2019) 4 SCC 1, para 7.\n\n"
    "2. A subsequent purchaser is a necessary party: see (2020) 9 SCC 42, para 3.\n"
)


def _verdict(citation: str, span: tuple[int, int] | None, **kwargs) -> CitationVerdict:
    base = {
        "citation_raw": citation,
        "proposition": "A proposition the brief advances.",
        "existence": "found",
        "judgment_title": "ALPHA versus BETA",
        "grade": "A",
        "span": span,
    }
    base.update(kwargs)
    return CitationVerdict(**base)


FIRST = _verdict(
    "(2019) 4 SCC 1",
    (BRIEF.index("(2019) 4 SCC 1"), BRIEF.index("(2019) 4 SCC 1") + len("(2019) 4 SCC 1")),
    grade="D",
    findings=[Finding(MODE_WRONG_PINPOINT, "pinpoint", "paragraph 7 is not where the words are")],
)
SECOND = _verdict(
    "(2020) 9 SCC 42",
    (BRIEF.index("(2020) 9 SCC 42"), BRIEF.index("(2020) 9 SCC 42") + len("(2020) 9 SCC 42")),
    grade="F",
    findings=[Finding(MODE_DEAD_LAW, "overruled", "overruled in 2022")],
)


# --- the annotated brief --------------------------------------------------------------------------


def test_a_flag_lands_beside_the_citation_it_belongs_to() -> None:
    """Inserting a marker moves everything after it, which is why the work goes back to front."""
    annotated = annotate_brief(BRIEF, [FIRST, SECOND])
    assert "(2019) 4 SCC 1 [!D 12], para 7" in annotated
    assert "(2020) 9 SCC 42 [!F 10], para 3" in annotated


def test_the_brief_survives_annotation_word_for_word() -> None:
    body = annotate_brief(BRIEF, [FIRST, SECOND]).split("\n---\n")[0]
    for marker in ("[!D 12]", "[!F 10]"):
        body = body.replace(f" {marker}", "")
    assert body.strip() == BRIEF.strip()


def test_a_citation_with_nothing_against_it_is_marked_so() -> None:
    clean = _verdict("(2021) 1 SCC 9", None, grade="A")
    assert "[ok]" in annotate_brief(BRIEF, [clean])


def test_a_citation_wanting_review_is_not_marked_as_clean() -> None:
    """Needing a person to look is not the same as passing, and must not read as it."""
    unsure = _verdict("(2021) 1 SCC 9", None, grade="C", needs_review=True)
    annotated = annotate_brief(BRIEF, [unsure])
    assert "[?C]" in annotated
    assert "[ok]" not in annotated


def test_the_same_failure_seen_twice_is_one_number() -> None:
    """"12,5,12" reads as three problems. It is two."""
    twice = _verdict(
        "(2019) 4 SCC 1",
        None,
        grade="E",
        findings=[
            Finding(MODE_WRONG_PINPOINT, "pinpoint", "not in the judgment"),
            Finding(MODE_DEAD_LAW, "overruled", "overruled in 2022"),
            Finding(MODE_WRONG_PINPOINT, "pinpoint", "the quote is elsewhere"),
        ],
    )
    assert "[!E 12,10]" in annotate_brief(BRIEF, [twice])


def test_a_verdict_that_could_not_be_placed_is_listed_not_dropped() -> None:
    """A citation graded and then quietly lost is the worst possible failure of a report."""
    unplaced = _verdict("(2018) 2 SCC 77", None, grade="F")
    annotated = annotate_brief(BRIEF, [FIRST, unplaced])
    assert "not located in this text" in annotated
    assert "(2018) 2 SCC 77" in annotated


def test_the_key_explains_every_marker_used() -> None:
    annotated = annotate_brief(BRIEF, [FIRST, SECOND])
    key = annotated.split("Key")[1]
    assert "(2019) 4 SCC 1" in key
    assert "(2020) 9 SCC 42" in key
    assert "overruled" in key


# --- the report -----------------------------------------------------------------------------------


def test_every_citation_reaches_the_report() -> None:
    report = verification_report([FIRST, SECOND], source="brief.txt")
    assert "brief.txt" in report
    assert report.count("### ") == 2
    for verdict in (FIRST, SECOND):
        assert verdict.citation_raw in report


def test_the_report_leads_with_the_count_that_decides_whether_to_file() -> None:
    report = verification_report([FIRST, SECOND])
    assert "2 citations checked" in report
    assert "2 graded D or worse" in report


def test_the_worst_citation_comes_first() -> None:
    report = verification_report([FIRST, SECOND])
    assert report.index("### (2020) 9 SCC 42") < report.index("### (2019) 4 SCC 1")


def test_a_verified_quote_is_shown_with_the_paragraph_it_came_from() -> None:
    supported = _verdict(
        "(2019) 4 SCC 1",
        None,
        support="full",
        quote="a misrepresentation vitiates consent only where it induced the contract",
        quote_verified=True,
        paragraph_label="3",
    )
    report = verification_report([supported])
    assert "Verified quote, paragraph 3" in report
    assert "vitiates consent only where it induced" in report


def test_the_report_says_what_was_not_checked() -> None:
    """A report of problems alone reads as a clean bill of health when it is short."""
    report = verification_report([_verdict("(2019) 4 SCC 1", None)])
    assert "What was not checked" in report


def test_the_grades_are_explained_where_they_are_used() -> None:
    report = verification_report([FIRST])
    assert "do not file this" in report
