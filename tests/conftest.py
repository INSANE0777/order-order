"""Shared fixtures. Tests run against an in-memory SQLite database and never touch the network."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from orderorder.db.models import Base, CitationAlias, Judgment
from orderorder.engine.search import build_index
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted
from orderorder.web.api import create_app


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def metadata_frame() -> pd.DataFrame:
    """Two rows shaped exactly like the AWS Open Data parquet, verified against the 2019 file."""
    return pd.DataFrame(
        [
            {
                "title": "GURMIT SINGH BHATIA versus KIRAN KANT ROBINSON AND OTHERS",
                "petitioner": "GURMIT SINGH BHATIA",
                "respondent": "KIRAN KANT ROBINSON AND OTHERS",
                "description": "",
                "judge": "D.Y. CHANDRACHUD, HEMANT GUPTA",
                "author_judge": None,
                "citation": "[2019] 9 S.C.R. 593",
                "case_id": "2019 INSC 770",
                "cnr": "ESCR010010152019",
                "decision_date": "17-07-2019",
                "disposal_nature": "Disposed off",
                "court": "Supreme Court of India",
                "available_languages": "ENG,HIN,PUN",
                "raw_html": "<select></select>",
                "path": "2019_9_593_605",
                "nc_display": "2019INSC770",
                "scraped_at": "2025-06-12T21:51:49",
                "year": "2019",
            },
            {
                "title": "STATE OF KERALA versus SOMEONE ELSE",
                "petitioner": "STATE OF KERALA",
                "respondent": "SOMEONE ELSE",
                "description": "",
                "judge": "R.F. NARIMAN",
                "author_judge": None,
                "citation": "[2019] 5 S.C.R. 579",
                "case_id": "",
                "cnr": "ESCR010010162019",
                "decision_date": "10-04-2019",
                "disposal_nature": "Dismissed",
                "court": "Supreme Court of India",
                "available_languages": "ENG",
                "raw_html": "<select></select>",
                "path": "2019_5_579_617",
                "nc_display": "",
                "scraped_at": "2025-06-12T21:51:49",
                "year": "2019",
            },
        ]
    )


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
