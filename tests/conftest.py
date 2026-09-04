"""Shared fixtures. Tests run against an in-memory SQLite database and never touch the network."""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from orderorder.db.models import Base


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
