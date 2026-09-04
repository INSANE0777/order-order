"""The citator: is this authority still good law?

Failure mode 10. Two rules carry the weight here and both are pinned below. Treatment is read from
the sentence carrying the citation, because a paragraph cites four cases and treats them differently.
And a bench cannot overrule one at least as large as itself — a rule of arithmetic, not language,
which no cue phrase may override.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.citations.grammar import normalize_citation_string
from orderorder.db.models import CitationAlias, Judgment
from orderorder.engine.citator import (
    apply_bench_rule,
    build_citator,
    classify_treatment,
    edges_in_judgment,
    treatment_of,
)
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted


def _judgment(session, key: str, title: str, *, bench: int, year: int, scc: str, text: str = "") -> Judgment:
    judgment = Judgment(
        canonical_key=key,
        court="Supreme Court of India",
        title=title,
        source="aws_open_data",
        source_id=key,
        bench_strength=bench,
        decided_on=dt.date(year, 6, 1),
    )
    session.add(judgment)
    session.flush()
    # The alias key must be the grammar's own, not one invented here: an edge is found by looking up
    # exactly what the grammar makes of the citation printed in the citing judgment.
    session.add(
        CitationAlias(
            judgment_id=judgment.id,
            reporter="SCC",
            citation_string=scc,
            normalized=normalize_citation_string(scc),
        )
    )
    if text:
        store_extracted(
            session, judgment, ExtractedJudgment(source_path=key, page_count=4, headnote="", judgment=text)
        )
    return judgment


# --- treatment from the words -------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "sentence"),
    [
        ("overruled", "The decision in Dolat Ram v. State of Haryana is hereby overruled."),
        ("overruled", "We hold that the said decision does not lay down the correct law."),
        ("overruled", "That judgment is no longer good law."),
        ("referred_to_larger_bench", "We refer the question to a larger Bench."),
        ("referred_to_larger_bench", "The matter requires reconsideration."),
        ("doubted", "With respect, we differ from the view taken in that case."),
        ("doubted", "We are unable to agree with the reasoning in Baluram."),
        ("distinguished", "That decision is clearly distinguishable on facts."),
        ("distinguished", "The judgment relied upon has no application to the facts of this case."),
        ("followed", "The issue is squarely covered by the decision in Kasturi."),
        ("relied_on", "Reliance was placed upon the decision in Robin Ramjibhai Patel."),
        ("affirmed", "The view taken therein is affirmed."),
        ("referred", "The appellant cited (2019) 4 SCC 1 in the course of arguments."),
    ],
)
def test_treatment_is_read_from_the_sentence(expected: str, sentence: str) -> None:
    assert classify_treatment(sentence) == expected


# --- the bench rule -----------------------------------------------------------


def test_a_smaller_bench_cannot_overrule_a_larger_one() -> None:
    """Two judges saying a three-judge decision is wrong have doubted it, not overruled it.

    Reporting an overruling that did not happen would be worse than missing one: an advocate would
    drop a binding authority on the strength of it.
    """
    assert apply_bench_rule("overruled", 2, 3) == ("doubted", "overruled")
    assert apply_bench_rule("overruled", 3, 3) == ("doubted", "overruled")


def test_a_larger_bench_may_overrule() -> None:
    assert apply_bench_rule("overruled", 5, 3) == ("overruled", None)
    assert apply_bench_rule("overruled", 7, 5) == ("overruled", None)


def test_an_unknown_bench_is_not_second_guessed() -> None:
    """With a bench strength missing there is no arithmetic to do, so the words stand."""
    assert apply_bench_rule("overruled", None, 3) == ("overruled", None)
    assert apply_bench_rule("overruled", 2, None) == ("overruled", None)


def test_the_rule_touches_nothing_but_overruling() -> None:
    assert apply_bench_rule("doubted", 2, 7) == ("doubted", None)
    assert apply_bench_rule("distinguished", 2, 7) == ("distinguished", None)
    assert apply_bench_rule("followed", 2, 7) == ("followed", None)


# --- edges and reports --------------------------------------------------------


@pytest.fixture
def corpus(session):
    """An earlier three-judge decision, and two later judgments that disagree with it."""
    earlier = _judgment(
        session, "INSC:2015:111", "KASTURI versus IYYAMPERUMAL", bench=3, year=2015, scc="(2015) 6 SCC 733"
    )
    _judgment(
        session,
        "INSC:2021:222",
        "SMALLER BENCH versus SOMEBODY",
        bench=2,
        year=2021,
        scc="(2021) 1 SCC 1",
        text=(
            "1. Leave granted. The appeal arises from a decree for specific performance passed by the "
            "High Court, which the appellant challenges on the ground of limitation and on the ground "
            "that the suit was not maintainable in its present form.\n\n"
            f"2. We are unable to agree with the reasoning in {earlier.title.title()}, "
            f"(2015) 6 SCC 733, which in our respectful view does not address the question now before "
            "us. The point is one of some general importance and we say no more about it here.\n\n"
            "3. The appeal is dismissed with no order as to costs."
        ),
    )
    _judgment(
        session,
        "INSC:2023:333",
        "LARGER BENCH versus SOMEBODY",
        bench=5,
        year=2023,
        scc="(2023) 2 SCC 2",
        text=(
            "1. Leave granted. This reference was occasioned by a conflict between two lines of "
            "authority on the impleadment of strangers to a contract in a suit for specific "
            "performance, and it falls to this Bench to resolve it.\n\n"
            f"2. Having considered the matter, the decision in {earlier.title.title()}, "
            "(2015) 6 SCC 733, is hereby overruled. The contrary view is restored and shall be "
            "followed by all courts.\n\n"
            "3. The reference is answered accordingly."
        ),
    )
    session.commit()
    build_citator(session)
    return session, earlier


def test_edges_are_extracted_with_their_treatment(corpus) -> None:
    session, earlier = corpus
    report = treatment_of(session, earlier.id)
    assert report.citing_count == 2
    assert {e.treatment for e in report.edges} == {"overruled", "doubted"}


def test_the_worst_treatment_decides_the_status(corpus) -> None:
    session, earlier = corpus
    report = treatment_of(session, earlier.id)
    assert report.status == "overruled"
    assert report.is_doubtful
    assert "INSC:2023:333" in (report.note or "")


def test_the_bench_rule_is_applied_when_the_report_is_built(session) -> None:
    """A two-judge bench claiming to overrule a three-judge one is recorded as doubt."""
    earlier = _judgment(
        session, "INSC:2015:111", "KASTURI versus IYYAMPERUMAL", bench=3, year=2015, scc="(2015) 6 SCC 733"
    )
    _judgment(
        session,
        "INSC:2021:222",
        "SMALLER versus SOMEBODY",
        bench=2,
        year=2021,
        scc="(2021) 1 SCC 1",
        text=(
            "1. Leave granted. The appeal concerns the impleadment of a stranger to the contract in a "
            "suit for specific performance, a question on which the authorities are not uniform.\n\n"
            "2. In our considered view the decision in Kasturi Versus Iyyamperumal, (2015) 6 SCC 733, "
            "is hereby overruled, since it does not accord with the scheme of Order 1 Rule 10 CPC as "
            "we understand it.\n\n"
            "3. The appeal is allowed."
        ),
    )
    session.commit()
    build_citator(session)

    report = treatment_of(session, earlier.id)
    assert report.status == "doubted"
    edge = report.worst
    assert edge is not None and edge.downgraded_from == "overruled"
    assert "cannot overrule" in (report.note or "")


def test_a_judgment_nobody_has_cited_is_reported_as_such(session) -> None:
    """Not the same as "no negative treatment exists": the corpus is not the whole of the law."""
    lonely = _judgment(session, "INSC:2016:999", "NOBODY versus NOBODY", bench=2, year=2016, scc="(2016) 1 SCC 9")
    session.commit()
    report = treatment_of(session, lonely.id)
    assert report.status == "good_law"
    assert report.citing_count == 0
    assert "which is not the same as none ever having done so" in (report.note or "")


def test_a_judgment_does_not_cite_itself(session) -> None:
    judgment = _judgment(
        session,
        "INSC:2019:1",
        "ALPHA versus BETA",
        bench=2,
        year=2019,
        scc="(2019) 1 SCC 1",
        text=(
            "1. Leave granted. This appeal concerns the interpretation of Section 19 of the Contract "
            "Act and the circumstances in which consent may be said to have been caused by a "
            "misrepresentation made by the other party to the agreement.\n\n"
            "2. The present case, reported as (2019) 1 SCC 1, requires no further elaboration on the "
            "point, the position being settled by a long line of authority which we need not set out.\n\n"
            "3. The appeal is dismissed."
        ),
    )
    session.commit()
    from orderorder.engine.citator import alias_map
    from orderorder.ingest.aliases import _paragraphs_of

    edges = edges_in_judgment(judgment, _paragraphs_of(session, judgment.id), alias_map(session))
    assert edges == []


def test_the_report_says_how_much_of_the_law_it_searched(corpus) -> None:
    session, earlier = corpus
    report = treatment_of(session, earlier.id)
    assert report.corpus_size == 2  # the two judgments whose text is held
