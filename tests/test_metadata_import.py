"""Importing the open-data metadata builds the spine the resolver depends on."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from orderorder.db.models import CitationAlias, Judgment
from orderorder.ingest.metadata import (
    canonical_key,
    import_parquet,
    parse_decision_date,
    parse_judges,
    row_to_judgment,
)


def test_parse_judges_splits_and_cleans() -> None:
    assert parse_judges("D.Y. CHANDRACHUD, HEMANT GUPTA") == ["D.Y. CHANDRACHUD", "HEMANT GUPTA"]
    assert parse_judges("HON'BLE MR. JUSTICE R.F. NARIMAN") == ["R.F. NARIMAN"]
    assert parse_judges("") == []
    assert parse_judges(None) == []


def test_bench_strength_is_the_judge_count(metadata_frame: pd.DataFrame) -> None:
    judgment, _ = row_to_judgment(metadata_frame.iloc[0])
    assert judgment.bench_strength == 2
    judgment, _ = row_to_judgment(metadata_frame.iloc[1])
    assert judgment.bench_strength == 1


def test_parse_decision_date_handles_the_source_format() -> None:
    assert parse_decision_date("17-07-2019").isoformat() == "2019-07-17"
    assert parse_decision_date("2019-07-17").isoformat() == "2019-07-17"
    assert parse_decision_date("") is None
    assert parse_decision_date("not a date") is None


def test_canonical_key_prefers_the_neutral_citation() -> None:
    assert canonical_key("2019 INSC 770", "2019_9_593_605", "2019") == "INSC:2019:770"


def test_canonical_key_falls_back_to_the_source_path() -> None:
    assert canonical_key("", "2019_5_579_617", "2019") == "SCP:2019:2019_5_579_617"
    assert canonical_key(None, None, "2019") is None


def test_row_produces_both_aliases(metadata_frame: pd.DataFrame) -> None:
    _, aliases = row_to_judgment(metadata_frame.iloc[0])
    normalized = {a[2] for a in aliases}
    assert normalized == {"INSC:2019:770", "SCR:2019:9:593"}


def test_import_writes_judgments_and_aliases(session, metadata_frame, tmp_path) -> None:
    path = tmp_path / "metadata.parquet"
    metadata_frame.to_parquet(path)

    stats = import_parquet(session, path)
    session.commit()

    assert stats.rows == 2
    assert stats.judgments_added == 2
    assert stats.aliases_added == 3  # first row has two citations, second has one

    judgments = session.scalars(select(Judgment)).all()
    assert {j.canonical_key for j in judgments} == {"INSC:2019:770", "SCP:2019:2019_5_579_617"}

    first = session.scalars(select(Judgment).where(Judgment.canonical_key == "INSC:2019:770")).one()
    assert first.court == "Supreme Court of India"
    assert first.decided_on.isoformat() == "2019-07-17"
    assert first.neutral_citation == "2019 INSC 770"
    assert first.judges == ["D.Y. CHANDRACHUD", "HEMANT GUPTA"]
    assert first.extra["cnr"] == "ESCR010010152019"


def test_import_is_idempotent(session, metadata_frame, tmp_path) -> None:
    path = tmp_path / "metadata.parquet"
    metadata_frame.to_parquet(path)

    import_parquet(session, path)
    session.commit()
    second = import_parquet(session, path)
    session.commit()

    assert second.judgments_added == 0
    assert second.aliases_added == 0
    assert second.judgments_skipped == 2
    assert len(session.scalars(select(Judgment)).all()) == 2
    assert len(session.scalars(select(CitationAlias)).all()) == 3


def test_limit_applies(session, metadata_frame, tmp_path) -> None:
    path = tmp_path / "metadata.parquet"
    metadata_frame.to_parquet(path)
    stats = import_parquet(session, path, limit=1)
    assert stats.rows == 1
    assert stats.judgments_added == 1
