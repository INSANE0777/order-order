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
from sqlalchemy import event

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


# --- what the run costs before it starts ------------------------------------------------------------


def test_the_limit_bounds_the_query_and_not_just_the_result(session, tmp_path) -> None:
    """A bound on the work has to be a bound on the read.

    Slicing afterwards returns the right judgments and pays for every row to do it -- 3.1 KB of ORM
    object each, measured, which is tens of gigabytes across the High Courts before one PDF is
    fetched. Returning three rows proves nothing about that, so this reads the SQL that was issued.
    """
    for n in range(10):
        _judgment(session, f"INSC:2019:{n}", year=2019)
    session.commit()

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        rows = bulk.judgments_needing_text(session, limit=3)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(rows) == 3
    reads = [s for s in statements if "FROM judgment" in s]
    assert reads, "the resume list issued no query"
    assert any("LIMIT" in s.upper() for s in reads), reads


def test_a_year_filter_still_honours_the_limit(session, tmp_path) -> None:
    """`years` reads a JSON field, so SQL cannot carry it; the scan has to stop at the limit instead."""
    for n in range(6):
        _judgment(session, f"INSC:2019:{n}", year=2019)
    for n in range(6):
        _judgment(session, f"INSC:2020:{n}", year=2020)
    session.commit()

    rows = bulk.judgments_needing_text(session, years=[2020], limit=2)
    assert len(rows) == 2
    assert all(j.canonical_key.startswith("INSC:2020") for j in rows)


def test_every_judgment_is_returned_exactly_once_when_the_queue_is_bounded() -> None:
    """The schedule must not lose or repeat work just because it stopped submitting everything.

    Order is not part of the contract and never was: results arrive as they finish, so a slow PDF
    does not hold up the ones behind it. `ingest_text_bulk` looks each one up by key for that reason.
    What must hold is that every judgment comes back, and none of them twice.
    """
    judgments = [_Stub(f"INSC:2019:{n}") for n in range(25)]
    keys = [key for key, _, _ in bulk._as_they_finish(_immediate, judgments, depth=4)]
    assert sorted(keys) == sorted(j.canonical_key for j in judgments)
    assert len(keys) == len(set(keys))


def test_the_queue_never_grows_with_the_corpus() -> None:
    """The whole point: memory is a function of the workers, not of how much there is to do."""
    high_water = 0
    live = 0

    def submit(judgment):
        nonlocal high_water, live
        live += 1
        high_water = max(high_water, live)
        return _immediate(judgment)

    judgments = [_Stub(f"INSC:2019:{n}") for n in range(500)]
    for _ in bulk._as_they_finish(submit, judgments, depth=8):
        live -= 1
    assert high_water <= 8, f"{high_water} in flight with a depth of 8"


def test_a_queue_depth_of_zero_still_makes_progress() -> None:
    """A pool of one worker with a depth that rounds to nothing must not deadlock on an empty queue."""
    judgments = [_Stub("INSC:2019:1"), _Stub("INSC:2019:2")]
    assert len(list(bulk._as_they_finish(_immediate, judgments, depth=0))) == 2


class _Stub:
    """A judgment as the scheduler sees it: three attributes and nothing else."""

    def __init__(self, key: str) -> None:
        self.canonical_key = key
        self.source_id = "2019_1_1_1"
        self.decided_on = dt.date(2019, 6, 1)
        self.extra = {"year": "2019"}


def _immediate(judgment):
    """Submit that has already finished, so the schedule is what is under test and not the pool."""
    future = bulk.Future()
    future.set_result((judgment.canonical_key, None, "stub"))
    return future
