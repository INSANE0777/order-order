"""Bulk text ingestion: resuming, accounting, and surviving bad judgments.

Thousands of PDFs mean some will be missing, some unparseable, and the run will be interrupted. What
these tests protect is that none of that loses work or ends the run: a judgment already ingested is
never fetched again, and a failure is recorded with its reason rather than raised.

No network: a stand-in fetcher supplies the parsed judgments, which is what the single-worker path
exists for.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import Judgment, JudgmentTextVersion
from orderorder.ingest import bulk
from orderorder.ingest.pdf import ExtractedJudgment

# Over the 500-character floor that `ExtractedJudgment.has_judgment` uses to tell a real judgment from
# a cover page that happened to parse.
JUDGMENT_TEXT = """1. Leave granted. The appellant challenges the judgment and order of the High Court
dated 3 July 2013, by which the writ petition preferred by the respondents came to be allowed and the
order of the trial court permitting the appellant's impleadment was set aside.

2. A misrepresentation vitiates consent only where it induced the contract, and the burden of proving
inducement lies upon the party alleging it. A mere inaccuracy in a recital, unaccompanied by proof
that the other party acted upon it, will not do. That has been the consistent position of this Court.

3. In view of the above and for the reasons stated above, the appeal is dismissed with no order as to
costs. Pending applications, if any, shall stand disposed of.
"""


def _judgment(session, key: str, *, year: int = 2019, source: str | None = "2019_1_1_1") -> Judgment:
    judgment = Judgment(
        canonical_key=key,
        court="Supreme Court of India",
        title=f"{key} versus SOMEBODY",
        source="aws_open_data",
        source_id=source,
        decided_on=dt.date(year, 6, 1),
        extra={"year": str(year)},
    )
    session.add(judgment)
    session.flush()
    return judgment


@pytest.fixture
def fake_fetch(monkeypatch):
    """Stand in for the network and the PDF parser. Keys ending in 'BAD' fail; 'EMPTY' parse to nothing."""
    calls: list[str] = []

    def fetch(canonical_key, source_id, year, corpus_dir):
        calls.append(canonical_key)
        if canonical_key.endswith("BAD"):
            return canonical_key, None, "PdfiumError: Failed to load page."
        if canonical_key.endswith("EMPTY"):
            return canonical_key, ExtractedJudgment(source_path=source_id, page_count=3, headnote="", judgment=""), None
        return (
            canonical_key,
            ExtractedJudgment(source_path=source_id, page_count=4, headnote="", judgment=JUDGMENT_TEXT),
            None,
        )

    monkeypatch.setattr(bulk, "_fetch_and_parse", fetch)
    return calls


def test_text_is_stored_and_counted(session, tmp_path, fake_fetch) -> None:
    judgments = [_judgment(session, "INSC:2019:1"), _judgment(session, "INSC:2019:2")]
    session.commit()

    result = bulk.ingest_text_bulk(session, judgments, tmp_path, workers=1)
    assert result.counts() == {"stored": 2}
    assert result.paragraphs == 6
    assert not result.failed


def test_a_missing_pdf_is_recorded_and_the_run_continues(session, tmp_path, fake_fetch) -> None:
    judgments = [
        _judgment(session, "INSC:2019:1"),
        _judgment(session, "INSC:2019:BAD"),
        _judgment(session, "INSC:2019:3"),
    ]
    session.commit()

    result = bulk.ingest_text_bulk(session, judgments, tmp_path, workers=1)
    assert result.counts() == {"stored": 2, "no_pdf": 1}
    assert len(result.stored) == 2
    assert result.failed[0].canonical_key == "INSC:2019:BAD"
    assert "Pdfium" in (result.failed[0].detail or "")


def test_a_pdf_that_yields_no_text_is_not_counted_as_stored(session, tmp_path, fake_fetch) -> None:
    judgments = [_judgment(session, "INSC:2019:EMPTY")]
    session.commit()

    result = bulk.ingest_text_bulk(session, judgments, tmp_path, workers=1)
    assert result.counts() == {"no_text": 1}
    assert session.query(JudgmentTextVersion).count() == 0


def test_judgments_already_holding_text_are_not_fetched_again(session, tmp_path, fake_fetch) -> None:
    """The resume rule: a run that dies at three thousand judgments carries on from there."""
    judgments = [_judgment(session, "INSC:2019:1"), _judgment(session, "INSC:2019:2")]
    session.commit()
    bulk.ingest_text_bulk(session, judgments, tmp_path, workers=1)
    fake_fetch.clear()

    remaining = bulk.judgments_needing_text(session)
    assert remaining == []
    assert bulk.ingest_text_bulk(session, remaining, tmp_path, workers=1).outcomes == []
    assert fake_fetch == []


def test_a_judgment_with_no_source_path_is_never_offered(session, tmp_path) -> None:
    _judgment(session, "INSC:2019:1", source=None)
    session.commit()
    assert bulk.judgments_needing_text(session) == []


def test_the_resume_list_can_be_narrowed_by_year_and_limit(session, tmp_path) -> None:
    _judgment(session, "INSC:2019:1", year=2019)
    _judgment(session, "INSC:2020:1", year=2020)
    _judgment(session, "INSC:2020:2", year=2020)
    session.commit()

    assert len(bulk.judgments_needing_text(session, years=[2020])) == 2
    assert len(bulk.judgments_needing_text(session, limit=1)) == 1
    assert bulk.judgments_needing_text(session, years=[1999]) == []


def test_progress_is_reported_for_every_judgment(session, tmp_path, fake_fetch) -> None:
    judgments = [_judgment(session, "INSC:2019:1"), _judgment(session, "INSC:2019:BAD")]
    session.commit()
    seen: list[tuple[str, int, int]] = []

    bulk.ingest_text_bulk(
        session, judgments, tmp_path, workers=1,
        on_result=lambda outcome, done, total: seen.append((outcome.status, done, total)),
    )
    assert [s[1] for s in seen] == [1, 2]
    assert all(s[2] == 2 for s in seen)


def test_failures_are_written_for_a_targeted_retry(session, tmp_path, fake_fetch) -> None:
    judgments = [_judgment(session, "INSC:2019:BAD"), _judgment(session, "INSC:2019:1")]
    session.commit()
    result = bulk.ingest_text_bulk(session, judgments, tmp_path, workers=1)

    path = tmp_path / "failures.tsv"
    assert bulk.write_failures(result, path) == 1
    assert list(bulk.read_failures(path)) == ["INSC:2019:BAD"]


def test_no_failures_writes_no_file(session, tmp_path, fake_fetch) -> None:
    judgments = [_judgment(session, "INSC:2019:1")]
    session.commit()
    result = bulk.ingest_text_bulk(session, judgments, tmp_path, workers=1)

    path = tmp_path / "failures.tsv"
    assert bulk.write_failures(result, path) == 0
    assert not path.exists()
    assert list(bulk.read_failures(path)) == []


def test_an_empty_run_is_not_an_error(session, tmp_path) -> None:
    result = bulk.ingest_text_bulk(session, [], tmp_path, workers=1)
    assert result.outcomes == []
    assert result.counts() == {}
