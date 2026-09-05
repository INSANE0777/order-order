"""The engine behind a browser.

Nothing here re-tests the engine; it tests that a page can reach it and that what comes back is the
same answer the command line gives. Two properties carry the weight:

  * **a verdict reaches the board as soon as it is decided**, because a phantom citation is settled in
    milliseconds and there is no reason for a reader to wait on the ones that need a model;
  * **the quote is located on the server and the paragraph comes back already cut in three**,
    because the normalisation that verified a quote is what has to find it again, and because
    Python counts characters where JavaScript counts UTF-16 units — an offset would agree only
    while nothing in the corpus lies outside the basic plane.
"""

from __future__ import annotations

import datetime as dt
import io
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from orderorder.db.models import CitationAlias, Judgment
from orderorder.engine.search import build_index
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted
from orderorder.web.api import create_app
from orderorder.web.jobs import Job, JobStore, watch

JUDGMENT = """1. Leave granted in the special leave petition filed by the appellant in this matter.

2. It was strenuously contended on behalf of the appellant that any misrepresentation whatsoever
vitiates consent in a commercial contract, however immaterial the misstatement may have been.

3. A misrepresentation of a material fact vitiates the consent of the contracting party only where
it induced the contract, and the burden of proving that inducement lies upon the party alleging it.

4. In view of the above, the appeals are dismissed with no order as to costs whatsoever.
"""


@pytest.fixture
def corpus(tmp_path):
    """A one-judgment knowledge base, and the way to open a session onto it.

    The app is handed this rather than reaching for the global session, and the difference is not
    cosmetic. Pointing `DATABASE_URL` at a temporary file and clearing the caches behind `get_session`
    looks equivalent and is not: anything that reloads the config module — `test_config` does, to
    prove `.env` is read from the working directory — leaves `db.session` holding a stale reference,
    and the fixture then clears a cache nobody reads. These tests passed alone and talked to whatever
    database the previous test had left behind when the suite ran together.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from orderorder.db.models import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'kb.sqlite').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def open_session():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    with open_session() as session:
        judgment = Judgment(
            canonical_key="TEST:0001:1",
            court="Supreme Court of India",
            title="ALPHA versus BETA",
            source="aws_open_data",
            source_id="TEST:0001:1",
            bench_strength=2,
            decided_on=dt.date(2019, 6, 1),
        )
        session.add(judgment)
        session.flush()
        session.add(
            CitationAlias(
                judgment_id=judgment.id,
                reporter="SCC",
                citation_string="(2019) 4 SCC 118",
                normalized="SCC:2019:4:118",
            )
        )
        store_extracted(
            session,
            judgment,
            ExtractedJudgment(source_path="x", page_count=4, headnote="", judgment=JUDGMENT),
        )
        session.commit()
        build_index(session)
        session.commit()
    yield open_session
    engine.dispose()


@pytest.fixture
def client(corpus):
    with TestClient(create_app(session_factory=corpus)) as c:
        yield c



BRIEF = (
    "1. A misrepresentation vitiates consent only where it induced the contract: "
    "(2019) 4 SCC 118, para 3.\n\n"
    "2. The point is settled by Mohanlal v. State, (2023) 7 SCC 4412.\n"
)


def _check(client, **kwargs) -> dict:
    """Start a job and wait for it, the way the page does but without the stream."""
    started = client.post("/api/verify", json={"text": BRIEF, "use_model": False, **kwargs})
    assert started.status_code == 200, started.text
    job = started.json()["job"]
    for _ in range(200):
        body = client.get(f"/api/jobs/{job}").json()
        if body["finished"]:
            return body
    raise AssertionError("the job never finished")


# --- the board -------------------------------------------------------------------------------------


def test_the_page_is_served(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "OrderOrder" in page.text


def test_the_status_line_says_what_is_held(client) -> None:
    body = client.get("/api/health").json()
    assert body["corpus_ready"] is True
    assert body["judgments_with_text"] == 1


def test_every_citation_in_the_brief_comes_back_graded(client) -> None:
    body = _check(client)
    assert body["error"] is None
    citations = [v["citation"] for v in body["verdicts"]]
    assert "(2019) 4 SCC 118" in citations
    assert "(2023) 7 SCC 4412" in citations
    assert all(v["grade"] in "ABCDEF" for v in body["verdicts"])


def test_a_phantom_citation_is_reported_as_one(client) -> None:
    body = _check(client)
    phantom = next(v for v in body["verdicts"] if v["citation"] == "(2023) 7 SCC 4412")
    assert phantom["grade"] == "F"
    assert 1 in [f["mode"] for f in phantom["findings"]]


def test_a_brief_with_nothing_in_it_is_refused(client) -> None:
    assert client.post("/api/verify", json={"text": "   "}).status_code == 400


def test_a_brief_longer_than_a_brief_is_refused(client) -> None:
    assert client.post("/api/verify", json={"text": "x" * 500_000}).status_code == 413


def test_a_job_nobody_started_is_not_invented(client) -> None:
    assert client.get("/api/jobs/nosuchjob").status_code == 404


# --- what the page does with a verdict ---------------------------------------------------------------


def test_the_judgment_comes_back_with_the_quote_located(client) -> None:
    """Located here, not in the browser: the normalisation that verified it is what finds it again."""
    quote = "vitiates the consent of the contracting party only where"
    body = client.get(f"/api/judgment/TEST:0001:1?highlight={quote}").json()
    assert body["title"] == "ALPHA versus BETA"
    marked = [p for p in body["paragraphs"] if p["quoted"]]
    assert len(marked) == 1
    assert marked[0]["quoted"].lower() == quote

    # The three parts put the paragraph back together exactly, which is the property the page needs
    # and the reason the split is done here: nothing has to agree about an offset across the wire.
    plain = client.get("/api/judgment/TEST:0001:1").json()
    whole = next(p for p in plain["paragraphs"] if p["seq"] == marked[0]["seq"])["body"]
    assert marked[0]["body"] + marked[0]["quoted"] + marked[0]["rest"] == whole


def test_a_quote_the_judgment_does_not_carry_highlights_nothing(client) -> None:
    body = client.get("/api/judgment/TEST:0001:1?highlight=a promissory estoppel binds the Crown").json()
    assert all(p["quoted"] == "" for p in body["paragraphs"])
    assert all(p["rest"] == "" for p in body["paragraphs"])


def test_a_judgment_the_corpus_does_not_hold(client) -> None:
    assert client.get("/api/judgment/INSC:1999:9").status_code == 404


def test_the_memo_is_offered_per_citation(client) -> None:
    body = _check(client)
    job = body["job"]
    memo = client.get(f"/api/jobs/{job}/memo/0")
    assert memo.status_code == 200
    assert "What was not checked" in memo.text
    assert client.get(f"/api/jobs/{job}/memo/99").status_code == 404


def test_the_report_and_the_annotated_brief_download(client) -> None:
    body = _check(client)
    job = body["job"]
    report = client.get(f"/api/jobs/{job}/report").text
    assert "Verification report" in report
    annotated = client.get(f"/api/jobs/{job}/annotated").text
    assert "(2019) 4 SCC 118" in annotated
    assert "Key" in annotated


# --- the other direction ------------------------------------------------------------------------------


def test_search_returns_the_line_not_only_the_case(client) -> None:
    body = client.get("/api/search?q=a misrepresentation vitiates consent where it induced").json()
    assert body["authorities"]
    best = body["authorities"][0]
    assert best["key"] == "TEST:0001:1"
    assert best["paragraph"] == "3"
    assert "vitiates the consent" in best["line"]


def test_searching_for_nothing_is_refused(client) -> None:
    assert client.get("/api/search?q=  ").status_code == 400


# --- the job store ------------------------------------------------------------------------------------


def test_a_watcher_is_told_about_each_verdict_then_told_it_is_over() -> None:
    """The board fills as the engine works; it does not wait for the slowest citation."""
    job = Job(id="j", text="", source="test", total=2)
    job.finish()  # already over, so `watch` drains and stops without blocking
    events = [name for name, _payload in watch(job)]
    assert events == ["done"]


def test_the_store_drops_the_oldest_rather_than_growing_for_ever() -> None:
    store = JobStore(limit=2)
    first = store.create("a", "test")
    store.create("b", "test")
    store.create("c", "test")
    assert len(store) == 2
    assert store.get(first.id) is None


# --- reading a brief out of a file ------------------------------------------------------------------


def _docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    from docx import Document

    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for row, cells in zip(grid.rows, table, strict=True):
            for cell, value in zip(row.cells, cells, strict=True):
                cell.text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_a_docx_brief_comes_back_as_text(client) -> None:
    data = _docx(["1. The appeal is allowed, as held in (2019) 4 SCC 118, para 3."])
    response = client.post(
        "/api/upload",
        files={"file": ("memorial.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "docx"
    assert "(2019) 4 SCC 118" in body["text"]


def test_a_table_of_authorities_is_read_too(client) -> None:
    """It is a table, and it is exactly where a reader wants every citation checked."""
    data = _docx(["Table of authorities"], table=[["Kasturi v. Iyyamperumal", "(2019) 4 SCC 118"]])
    body = client.post(
        "/api/upload",
        files={"file": ("memorial.docx", data, "application/octet-stream")},
    ).json()
    assert "(2019) 4 SCC 118" in body["text"]


def test_a_plain_text_brief_is_taken_as_it_is(client) -> None:
    body = client.post(
        "/api/upload", files={"file": ("brief.txt", BRIEF.encode("utf-8"), "text/plain")}
    ).json()
    assert body["kind"] == "text"
    assert body["text"] == BRIEF


def test_a_file_with_no_text_in_it_is_refused_rather_than_checked(client) -> None:
    """An empty extraction checked silently produces a page of nonsense nobody can explain."""
    data = _docx(["   "])
    response = client.post("/api/upload", files={"file": ("scan.docx", data, "application/octet-stream")})
    assert response.status_code == 422
    assert "scan" in response.json()["detail"] or "no text" in response.json()["detail"]


def test_a_file_that_is_not_what_it_claims_is_refused(client) -> None:
    response = client.post("/api/upload", files={"file": ("brief.pdf", b"not a pdf at all", "application/pdf")})
    assert response.status_code == 400


def test_the_old_doc_format_says_what_to_do_about_it(client) -> None:
    response = client.post("/api/upload", files={"file": ("brief.doc", b"\xd0\xcf\x11\xe0", "application/msword")})
    assert response.status_code == 400
    assert ".docx" in response.json()["detail"]


def test_a_file_larger_than_a_brief_is_refused(client) -> None:
    response = client.post(
        "/api/upload", files={"file": ("huge.txt", b"x" * 26_000_000, "text/plain")}
    )
    assert response.status_code == 413
