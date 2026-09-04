"""Persisting an extracted judgment, and reading its paragraphs back for the locator."""

from __future__ import annotations

from sqlalchemy import select

from orderorder.db.models import Judgment, JudgmentTextVersion, Opinion, Paragraph
from orderorder.engine.locator import locate
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import load_paragraphs, store_extracted, text_sha256

JUDGMENT_TEXT = """The Judgment of the Court was delivered by
M. R. SHAH , J.

1. Feeling aggrieved by the impugned judgment, the appellant preferred these appeals.

2. The facts of the case leading to these appeals in nutshell are as under.

3. A misrepresentation vitiates consent only where it induced the contract to sell.

4. In view of the above, the appeals are dismissed with no order as to costs.
"""

HEADNOTE = "Code of Civil Procedure, 1908 - Or.1, r.10.\nHELD: The plaintiff is the dominus litis."


def _judgment(session) -> Judgment:
    j = Judgment(
        canonical_key="INSC:2019:770",
        court="Supreme Court of India",
        title="GURMIT SINGH BHATIA versus KIRAN KANT ROBINSON",
        source="aws_open_data",
        source_id="2019_9_593_605",
    )
    session.add(j)
    session.flush()
    return j


def _extracted(judgment_text: str = JUDGMENT_TEXT, headnote: str = HEADNOTE) -> ExtractedJudgment:
    return ExtractedJudgment(
        source_path="2019_9_593_605",
        page_count=13,
        headnote=headnote,
        judgment=judgment_text,
        author="M. R. SHAH",
    )


def test_stores_version_paragraphs_and_opinions(session) -> None:
    judgment = _judgment(session)
    result = store_extracted(session, judgment, _extracted())
    session.commit()

    # Five, not four: the "Judgment of the Court was delivered by" line is an unlabelled opening
    # paragraph and is kept, because it names the authoring judge.
    assert result.paragraphs == 5
    assert not result.replaced

    version = session.scalars(select(JudgmentTextVersion)).one()
    assert version.version_key == "scr_pdf"
    assert version.preferred
    assert not version.ocr_derived
    assert version.sha256 == text_sha256(JUDGMENT_TEXT)
    assert version.char_count == len(JUDGMENT_TEXT)

    labels = [p.printed_label for p in session.scalars(select(Paragraph).order_by(Paragraph.seq)).all()]
    assert labels == [None, "1", "2", "3", "4"]


def test_headnote_is_recorded_as_its_own_opinion(session) -> None:
    """The publisher's summary is kept, but never as the court's voice."""
    judgment = _judgment(session)
    store_extracted(session, judgment, _extracted())
    session.commit()

    kinds = {o.kind for o in session.scalars(select(Opinion)).all()}
    assert "headnote" in kinds
    assert "majority" in kinds

    bodies = " ".join(p.body for p in session.scalars(select(Paragraph)).all())
    assert "HELD:" not in bodies
    assert "dominus litis" not in bodies


def test_author_is_attached_to_the_majority_opinion(session) -> None:
    judgment = _judgment(session)
    store_extracted(session, judgment, _extracted())
    session.commit()
    majority = session.scalars(select(Opinion).where(Opinion.kind == "majority")).one()
    assert majority.author == "M. R. SHAH"


def test_paragraphs_are_linked_to_an_opinion(session) -> None:
    judgment = _judgment(session)
    store_extracted(session, judgment, _extracted())
    session.commit()
    assert all(p.opinion_id for p in session.scalars(select(Paragraph)).all())


def test_reingesting_replaces_rather_than_duplicates(session) -> None:
    judgment = _judgment(session)
    store_extracted(session, judgment, _extracted())
    session.commit()
    second = store_extracted(session, judgment, _extracted())
    session.commit()

    assert second.replaced
    assert len(session.scalars(select(JudgmentTextVersion)).all()) == 1
    assert len(session.scalars(select(Paragraph)).all()) == 5


def test_replace_false_keeps_the_existing_version(session) -> None:
    judgment = _judgment(session)
    first = store_extracted(session, judgment, _extracted())
    session.commit()
    second = store_extracted(session, judgment, _extracted(), replace=False)
    assert second.text_version_id == first.text_version_id
    assert not second.replaced


def test_dissent_becomes_a_separate_opinion(session) -> None:
    text = (
        JUDGMENT_TEXT
        + "\n\nR. F. NARIMAN, J. (dissenting)\n\n5. I respectfully disagree with the majority.\n"
    )
    judgment = _judgment(session)
    store_extracted(session, judgment, _extracted(judgment_text=text))
    session.commit()

    dissent = session.scalars(select(Opinion).where(Opinion.kind == "dissenting")).one()
    assert "NARIMAN" in dissent.author


def test_round_trip_feeds_the_locator(session) -> None:
    """Paragraphs read back from the database must locate exactly as they do in memory."""
    judgment = _judgment(session)
    store_extracted(session, judgment, _extracted())
    session.commit()

    paragraphs = load_paragraphs(session, judgment.id)
    assert len(paragraphs) == 5

    result = locate(paragraphs, "misrepresentation vitiates consent inducement", claimed_pinpoint="3")
    assert result.best.printed_label == "3"
    assert result.pinpoint.status == "ok"


def test_load_paragraphs_for_a_judgment_without_text(session) -> None:
    judgment = _judgment(session)
    session.commit()
    assert load_paragraphs(session, judgment.id) == []


def test_bench_strength_is_corrected_from_the_coram(session) -> None:
    """The metadata names only the presiding judge; the printed coram names the whole bench."""
    judgment = _judgment(session)
    judgment.bench_strength = 1
    judgment.judges = ["D.Y. CHANDRACHUD"]
    session.flush()

    extracted = _extracted()
    extracted.coram = ["DHANANJAYA Y. CHANDRACHUD", "M. R. SHAH"]
    result = store_extracted(session, judgment, extracted)
    session.commit()

    assert result.bench_corrected
    assert judgment.bench_strength == 2
    assert judgment.judges == ["DHANANJAYA Y. CHANDRACHUD", "M. R. SHAH"]


def test_bench_strength_is_not_reduced_by_a_partial_coram(session) -> None:
    judgment = _judgment(session)
    judgment.bench_strength = 5
    session.flush()

    extracted = _extracted()
    extracted.coram = ["Only One Judge"]
    result = store_extracted(session, judgment, extracted)
    session.commit()

    assert not result.bench_corrected
    assert judgment.bench_strength == 5
