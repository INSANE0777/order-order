"""Repairing text already in the database when extraction is corrected after the fact.

Re-reading nine thousand PDFs to apply a one-line fix is hours of work the database already holds the
answer to. What these repairs must guarantee is that they leave the corpus in the state a fresh
extraction would have produced, and that running one twice changes nothing the second time.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from orderorder.db.models import Judgment, Paragraph
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.repair import strip_publisher_trailers, strip_signoffs
from orderorder.ingest.store import store_extracted

WITH_TRAILER = """1. Leave granted in both the special leave petitions.

2. A misrepresentation vitiates consent only where it induced the contract, and the burden of proving
inducement lies upon the party alleging it before the trial court.

3. In view of the above the appeals are allowed. No order as to costs.
Result of the case: Appeals allowed.
Headnotes prepared by: Divya Pandey, Hony. Associate Editor
"""

WITH_SIGNOFF = """1. Leave granted.

2. The question is whether a notice under Section 106 was mandatory in this case.

3. It was, and its absence is fatal to the suit. The appeal is accordingly dismissed.
Ankit Gyan Appeal dismissed.
(Assisted by : Rahul Rathi, LCRA)
"""

CLEAN = """1. Leave granted.

2. A notice under Section 106 of the Transfer of Property Act is mandatory before a suit.

3. The appeal is allowed and the decree of the trial court is restored in its entirety.
"""


def _store(session, key: str, text: str) -> Judgment:
    judgment = Judgment(
        canonical_key=key,
        court="Supreme Court of India",
        title=f"{key} ALPHA versus BETA",
        source="aws_open_data",
        source_id=key,
        bench_strength=2,
        decided_on=dt.date(2019, 6, 1),
    )
    session.add(judgment)
    session.flush()
    # Stored as it was before extraction knew where the court stops.
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path=key, page_count=4, headnote="", judgment=text),
    )
    session.commit()
    return judgment


def _bodies(session, judgment: Judgment) -> list[str]:
    version = judgment.versions[0]
    return [
        p.body
        for p in session.scalars(
            select(Paragraph).where(Paragraph.text_version_id == version.id).order_by(Paragraph.seq)
        ).all()
    ]


@pytest.fixture
def corpus(session):
    _store(session, "INSC:2019:1", WITH_TRAILER)
    _store(session, "INSC:2019:2", WITH_SIGNOFF)
    _store(session, "INSC:2019:3", CLEAN)
    return session


def test_the_publisher_trailer_is_cut_out_of_stored_text(corpus) -> None:
    judgment = corpus.scalars(select(Judgment).where(Judgment.canonical_key == "INSC:2019:1")).one()
    assert any("Headnotes prepared by" in body for body in _bodies(corpus, judgment))

    result = strip_publisher_trailers(corpus)
    assert result.trimmed == 1
    assert result.characters > 0

    bodies = _bodies(corpus, judgment)
    assert not any("Headnotes prepared by" in body for body in bodies)
    assert not any("Result of the case" in body for body in bodies)
    assert bodies[-1].endswith("No order as to costs.")


def test_the_signoff_is_cut_out_of_the_last_paragraph(corpus) -> None:
    judgment = corpus.scalars(select(Judgment).where(Judgment.canonical_key == "INSC:2019:2")).one()
    result = strip_signoffs(corpus)
    assert result.trimmed == 1

    bodies = _bodies(corpus, judgment)
    assert "Ankit Gyan" not in bodies[-1]
    assert "Assisted by" not in bodies[-1]
    assert bodies[-1].endswith("The appeal is accordingly dismissed.")


def test_a_judgment_with_nothing_to_repair_is_untouched(corpus) -> None:
    judgment = corpus.scalars(select(Judgment).where(Judgment.canonical_key == "INSC:2019:3")).one()
    before = _bodies(corpus, judgment)
    strip_publisher_trailers(corpus)
    strip_signoffs(corpus)
    assert _bodies(corpus, judgment) == before


def test_running_a_repair_twice_changes_nothing_the_second_time(corpus) -> None:
    """A repair is run against a live corpus, possibly more than once. It has to be safe to repeat."""
    strip_publisher_trailers(corpus)
    strip_signoffs(corpus)
    judgments = corpus.scalars(select(Judgment)).all()
    after_once = {j.canonical_key: _bodies(corpus, j) for j in judgments}

    assert strip_publisher_trailers(corpus).trimmed == 0
    assert strip_signoffs(corpus).trimmed == 0
    assert {j.canonical_key: _bodies(corpus, j) for j in judgments} == after_once


def test_offsets_shrink_by_exactly_what_was_cut(corpus) -> None:
    """A verified quote is highlighted by character offset, so the span has to follow the body.

    The span covers the source lines and the printed label with them, so it is never the body's
    length; what it must be is shorter by exactly the characters removed.
    """
    judgment = corpus.scalars(select(Judgment).where(Judgment.canonical_key == "INSC:2019:2")).one()
    version = judgment.versions[0]

    def spans() -> dict[int, tuple[int, int, int]]:
        return {
            p.seq: (p.char_start, p.char_end, len(p.body))
            for p in corpus.scalars(
                select(Paragraph).where(Paragraph.text_version_id == version.id)
            ).all()
        }

    before = spans()
    strip_signoffs(corpus)
    after = spans()

    for seq, (start, end, length) in after.items():
        was_start, was_end, was_length = before[seq]
        assert start == was_start
        assert was_end - end == was_length - length
