"""Learning the reporter citations the open data does not carry.

The danger here is not missing an alias; it is recording a wrong one, because a wrong alias makes the
resolver confidently name the wrong case, and confident wrongness is the thing this product exists to
prevent. So these tests are mostly about what is *refused*: an unclear title match, a citation two
judgments attach to different cases, a single mediocre sighting.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.citations.grammar import normalize_citation_string
from orderorder.db.models import CitationAlias, Judgment
from orderorder.ingest.aliases import (
    INFERRED,
    PAIRED,
    LearnStats,
    Sighting,
    TitleIndex,
    accept,
    citation_pairs,
    learn_aliases,
    match_title,
    pair_sightings,
)
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

PADDING = (
    "The appeal arises from a decree for specific performance and raises a question on the "
    "impleadment of a stranger to the contract, which has divided the High Courts for some years."
)


def _judgment(session, key: str, title: str, *, year: int, known_citation: str | None, text: str = ""):
    judgment = Judgment(
        canonical_key=key,
        court="Supreme Court of India",
        title=title,
        source="aws_open_data",
        source_id=key,
        bench_strength=2,
        decided_on=dt.date(year, 6, 1),
    )
    session.add(judgment)
    session.flush()
    if known_citation:
        session.add(
            CitationAlias(
                judgment_id=judgment.id,
                reporter="INSC",
                citation_string=known_citation,
                normalized=normalize_citation_string(known_citation),
            )
        )
    if text:
        store_extracted(
            session, judgment, ExtractedJudgment(source_path=key, page_count=4, headnote="", judgment=text)
        )
    return judgment


# --- pairing: what the corpus states outright ---------------------------------


def test_citations_a_colon_apart_are_one_case() -> None:
    """The Reports print footnotes exactly like this, and they are a gift: no inference at all."""
    runs = citation_pairs("The point is settled: see 2007 INSC 496 : (2007) 6 SCC 162 at paragraph 14.")
    assert len(runs) == 1
    assert [c.reporter for c in runs[0]] == ["INSC", "SCC"]


def test_citations_separated_by_words_are_two_cases() -> None:
    body = "This was held in 2007 INSC 496 and again, much later, in (2019) 4 SCC 1 on the same point."
    assert citation_pairs(body) == []


def test_a_run_of_three_reporters_is_one_case() -> None:
    runs = citation_pairs("See 2021 INSC 619 : (2022) 1 SCC 30 : 2021 SCC OnLine SC 704 for the rule.")
    assert len(runs) == 1
    assert len(runs[0]) == 3


def test_the_unknown_half_of_a_pair_becomes_an_alias(session) -> None:
    cited = _judgment(session, "INSC:2019:770", "GURMIT versus KIRAN", year=2019, known_citation="2019 INSC 770")
    _judgment(
        session,
        "INSC:2023:1",
        "LATER versus SOMEBODY",
        year=2023,
        known_citation="2023 INSC 1",
        text=f"1. Leave granted. {PADDING}\n\n2. The rule is in 2019 INSC 770 : (2019) 8 SCC 1. {PADDING}\n\n3. Dismissed.",
    )
    session.commit()

    aliases = {a.normalized: a.judgment_id for a in session.query(CitationAlias).all()}
    sightings = pair_sightings(session, aliases)
    assert [s.normalized for s in sightings] == [normalize_citation_string("(2019) 8 SCC 1")]
    assert sightings[0].judgment_id == cited.id
    assert sightings[0].score == 100.0


def test_a_pair_naming_two_known_judgments_is_a_parse_error_not_a_pairing(session) -> None:
    _judgment(session, "INSC:2019:770", "ALPHA versus BETA", year=2019, known_citation="2019 INSC 770")
    _judgment(session, "INSC:2020:5", "GAMMA versus DELTA", year=2020, known_citation="2020 INSC 5")
    _judgment(
        session,
        "INSC:2023:1",
        "LATER versus SOMEBODY",
        year=2023,
        known_citation="2023 INSC 1",
        text=f"1. Leave granted. {PADDING}\n\n2. See 2019 INSC 770 : 2020 INSC 5 on this. {PADDING}\n\n3. Dismissed.",
    )
    session.commit()

    aliases = {a.normalized: a.judgment_id for a in session.query(CitationAlias).all()}
    assert pair_sightings(session, aliases) == []


# --- party names: what the corpus implies -------------------------------------


@pytest.fixture
def titles() -> dict[str, str]:
    return {
        "a": "KASTURI versus IYYAMPERUMAL AND OTHERS",
        "b": "STATE OF KERALA versus MATHAI VERGHESE",
        "c": "STATE OF KERALA versus MATHEW VARGHESE",
    }


def test_a_clear_title_match_is_taken(titles) -> None:
    match = match_title("Kasturi v. Iyyamperumal", titles)
    assert match is not None and match[0] == "a"


def test_near_identical_party_names_are_still_told_apart(titles) -> None:
    """"Mathai Verghese" and "Mathew Varghese" are different cases a letter apart, and both are held.

    The matcher scores them 96.9 against 78.9, so the margin is ample and each name finds its own
    case. This is the property that makes learning aliases from party names safe at all.
    """
    assert match_title("State of Kerala v. Mathai Verghese", titles)[0] == "b"
    assert match_title("State of Kerala v. Mathew Varghese", titles)[0] == "c"


def test_two_cases_with_the_same_parties_are_refused() -> None:
    """The Supreme Court decides "State of Maharashtra v. Ramesh" more than once, years apart.

    Nothing in the party names chooses between them, so nothing is learned. Guessing here would
    attach one case's citation to another's, which is the failure this whole pass must not commit.
    """
    same = {
        "x": "STATE OF MAHARASHTRA versus RAMESH",
        "y": "STATE OF MAHARASHTRA versus RAMESH",
    }
    assert match_title("State of Maharashtra v. Ramesh", same) is None


def test_a_title_nothing_resembles_is_refused(titles) -> None:
    assert match_title("Union of India v. Some Company Limited", titles) is None


def test_titles_are_indexed_by_year_with_a_window_either_side(session) -> None:
    _judgment(session, "INSC:2019:1", "ALPHA versus BETA", year=2019, known_citation="2019 INSC 1")
    _judgment(session, "INSC:2021:1", "GAMMA versus DELTA", year=2021, known_citation="2021 INSC 1")
    session.commit()

    index = TitleIndex.build(session)
    assert len(index.window(2019)) == 1
    assert len(index.window(2020)) == 2  # a case decided in December is reported the next year
    assert index.window(1990) == {}


# --- accepting, and refusing ---------------------------------------------------


def _sighting(normalized: str, judgment_id: str, score: float, citing_id: str) -> Sighting:
    return Sighting(normalized, "(2015) 6 SCC 733", "SCC", judgment_id, score, citing_id)


def test_a_near_certain_single_sighting_is_accepted() -> None:
    stats = LearnStats()
    accepted = accept([_sighting("SCC:2015:6:733", "j1", 98.0, "c1")], stats)
    assert accepted["SCC:2015:6:733"].judgment_id == "j1"
    assert stats.accepted == 1


def test_a_mediocre_single_sighting_needs_corroboration() -> None:
    stats = LearnStats()
    assert accept([_sighting("SCC:2015:6:733", "j1", 93.0, "c1")], stats) == {}
    assert stats.rejected_uncorroborated == 1

    stats = LearnStats()
    corroborated = accept(
        [_sighting("SCC:2015:6:733", "j1", 93.0, "c1"), _sighting("SCC:2015:6:733", "j1", 93.0, "c2")],
        stats,
    )
    assert corroborated and stats.accepted == 1


def test_two_judgments_naming_different_cases_teaches_nothing() -> None:
    """One of them is wrong and there is no way to tell which, so neither is recorded."""
    stats = LearnStats()
    accepted = accept(
        [_sighting("SCC:2015:6:733", "j1", 99.0, "c1"), _sighting("SCC:2015:6:733", "j2", 99.0, "c2")],
        stats,
    )
    assert accepted == {}
    assert stats.rejected_conflict == 1


def test_the_same_judgment_twice_is_corroboration_not_conflict() -> None:
    stats = LearnStats()
    accepted = accept(
        [_sighting("SCC:2015:6:733", "j1", 94.0, "c1"), _sighting("SCC:2015:6:733", "j1", 95.0, "c2")],
        stats,
    )
    assert accepted["SCC:2015:6:733"].score == 95.0
    assert stats.rejected_conflict == 0


# --- end to end ----------------------------------------------------------------


def test_learning_records_both_kinds_and_says_which(session) -> None:
    cited = _judgment(
        session, "INSC:2019:770", "GURMIT SINGH BHATIA versus KIRAN KANT ROBINSON",
        year=2019, known_citation="2019 INSC 770",
    )
    _judgment(
        session,
        "INSC:2023:1",
        "LATER versus SOMEBODY",
        year=2023,
        known_citation="2023 INSC 1",
        text=(
            f"1. Leave granted. {PADDING}\n\n"
            f"2. The rule is stated in 2019 INSC 770 : (2019) 8 SCC 1. {PADDING}\n\n"
            "3. The appeal is dismissed with no order as to costs."
        ),
    )
    session.commit()

    stats = learn_aliases(session)
    assert stats.paired == 1

    learned = session.query(CitationAlias).filter(CitationAlias.source == PAIRED).all()
    assert len(learned) == 1
    assert learned[0].judgment_id == cited.id
    assert learned[0].normalized == normalize_citation_string("(2019) 8 SCC 1")


def test_a_dry_run_writes_nothing(session) -> None:
    _judgment(session, "INSC:2019:770", "GURMIT versus KIRAN", year=2019, known_citation="2019 INSC 770")
    _judgment(
        session,
        "INSC:2023:1",
        "LATER versus SOMEBODY",
        year=2023,
        known_citation="2023 INSC 1",
        text=f"1. Leave granted. {PADDING}\n\n2. See 2019 INSC 770 : (2019) 8 SCC 1. {PADDING}\n\n3. Dismissed.",
    )
    session.commit()
    before = session.query(CitationAlias).count()

    stats = learn_aliases(session, dry_run=True)
    assert stats.paired == 1
    assert session.query(CitationAlias).count() == before


def test_a_citation_already_known_is_not_learned_again(session) -> None:
    _judgment(session, "INSC:2019:770", "GURMIT versus KIRAN", year=2019, known_citation="2019 INSC 770")
    _judgment(
        session,
        "INSC:2023:1",
        "LATER versus SOMEBODY",
        year=2023,
        known_citation="2023 INSC 1",
        text=f"1. Leave granted. {PADDING}\n\n2. See 2019 INSC 770 alone here. {PADDING}\n\n3. Dismissed.",
    )
    session.commit()

    learn_aliases(session)
    assert session.query(CitationAlias).filter(CitationAlias.source.in_([PAIRED, INFERRED])).count() == 0
