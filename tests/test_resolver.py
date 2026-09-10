"""The resolver decides whether a cited case exists. A wrong answer here is a phantom verdict."""

from __future__ import annotations

import pandas as pd
import pytest

from orderorder.citations.grammar import parse_citation
from orderorder.ingest.metadata import import_parquet
from orderorder.resolver import (
    Resolution,
    check_party_names,
    resolve,
    resolve_by_parties,
    resolve_exact,
)


@pytest.fixture
def loaded(session, metadata_frame: pd.DataFrame, tmp_path):
    path = tmp_path / "metadata.parquet"
    metadata_frame.to_parquet(path)
    import_parquet(session, path)
    session.commit()
    return session


def test_exact_alias_resolves(loaded) -> None:
    result = resolve_exact(loaded, "INSC:2019:770")
    assert result.found
    assert result.canonical_key == "INSC:2019:770"
    assert result.score == 100.0


def test_parallel_citation_resolves_to_the_same_judgment(loaded) -> None:
    """The SCR citation and the neutral citation are the same case."""
    by_scr = resolve_exact(loaded, "SCR:2019:9:593")
    by_neutral = resolve_exact(loaded, "INSC:2019:770")
    assert by_scr.found and by_neutral.found
    assert by_scr.judgment_id == by_neutral.judgment_id


def test_citation_parsed_from_text_then_resolved(loaded) -> None:
    citation = parse_citation("[2019] 9 S.C.R. 593")
    result = resolve(loaded, citation)
    assert result.found
    assert result.canonical_key == "INSC:2019:770"


def test_unknown_citation_is_not_found(loaded) -> None:
    """A well-formed citation that matches nothing is what a phantom verdict is built on."""
    citation = parse_citation("(2019) 99 SCC 9999")
    result = resolve(loaded, citation)
    assert not result.found
    assert result.status == "not_found"
    assert "no judgment carries the alias" in result.note


def test_party_names_rescue_a_wrong_citation(loaded) -> None:
    """Right case, wrong citation string: the mis-cite path."""
    citation = parse_citation("Gurmit Singh Bhatia v. Kiran Kant Robinson, (2019) 99 SCC 9999")
    assert citation.party_names
    result = resolve(loaded, citation)
    assert result.found
    assert result.method == "party_name"
    assert result.canonical_key == "INSC:2019:770"
    assert "not in the corpus" in result.note


def test_anonymised_brief_titles_are_a_review_not_a_pass() -> None:
    """"State of U.P. v. Anr." against "STATE OF ORISSA versus BALRAM SAHU" scores 57 and passes.

    The September 2026 holdout planted a mis-cite of exactly this shape twice (measured scores 57
    and 61, just above the 55 floor -- token matching inflates "state of" against any title
    containing those words) and the engine graded both A. The strings cannot detect the wrongness,
    so the honest answer is a review request rather than a silent pass.
    """
    resolution = Resolution(
        status="found",
        method="exact",
        judgment_id="j1",
        canonical_key="INSC:2009:77",
        matched_title="STATE OF ORISSA AND ORS. versus BALRAM SAHU",
    )
    checked = check_party_names(resolution, "The State Of Karnataka v. Anr.")
    assert not checked.name_mismatch
    assert checked.review is not None and "anonymised" in checked.review


def test_anonymised_titles_agreeing_are_also_a_review() -> None:
    resolution = Resolution(
        status="found",
        method="exact",
        judgment_id="j1",
        canonical_key="INSC:1981:189",
        matched_title="THE STATE OF KARNATAKA versus ANR.",
    )
    checked = check_party_names(resolution, "State Of Karnataka v. Anr.")
    assert not checked.name_mismatch
    assert checked.review is not None


def test_distinct_titles_still_disagree() -> None:
    """The anonymised-title review must not soften the plain mismatch into a review."""
    resolution = Resolution(
        status="found",
        method="exact",
        judgment_id="j1",
        canonical_key="INSC:2019:770",
        matched_title="GURMIT SINGH BHATIA versus KIRAN KANT ROBINSON AND OTHERS",
    )
    checked = check_party_names(resolution, "State Of U.p. v. Anr.")
    assert checked.name_mismatch
    assert checked.review is None


def test_party_match_below_threshold_is_not_found(loaded) -> None:
    result = resolve_by_parties(loaded, "Completely Unrelated Party v. Another Stranger")
    assert not result.found


def test_party_match_is_year_filtered(loaded) -> None:
    assert resolve_by_parties(loaded, "Gurmit Singh Bhatia v. Kiran Kant Robinson", year=2019).found
    assert not resolve_by_parties(loaded, "Gurmit Singh Bhatia v. Kiran Kant Robinson", year=1999).found


def test_resolution_carries_candidates_for_review(loaded) -> None:
    result = resolve_by_parties(loaded, "Gurmit Singh Bhatia v. Kiran Kant Robinson")
    assert result.candidates
    assert result.candidates[0].canonical_key == "INSC:2019:770"
    assert result.candidates[0].score >= 88.0
