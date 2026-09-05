"""Measuring the search direction.

The instrument has to be harder on the engine than the engine is on itself. Two things could make
this flatter: a query that is not really a query, and a hit that is not really a hit. Both are pinned
here — the fragment is never chosen for how well it retrieves, and a line counts only if it is the
sentence the proposition came from rather than one that merely overlaps it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, Judgment
from orderorder.engine.search import build_index
from orderorder.evaluation.retrieval import (
    FRAGMENT,
    FRAGMENT_WORDS,
    VERBATIM,
    Outcome,
    RetrievalItem,
    RetrievalReport,
    _fragment,
    build_items,
    format_retrieval,
    run_item,
)
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

HOLDING = """1. Leave granted in the special leave petition filed by the appellant in this matter.

2. It was strenuously contended on behalf of the appellant that any misrepresentation whatsoever
vitiates consent in a commercial contract, however immaterial the misstatement may have been.

3. A misrepresentation of a material fact vitiates the consent of the contracting party only where
it induced the contract, and the burden of proving that inducement lies upon the party alleging it.

4. The doctrine of frustration has no application where the parties have expressly allocated the
risk of the supervening event between themselves in the contract they made.

5. The question of limitation was not argued before the High Court and cannot be raised for the
first time in an appeal by special leave against that judgment.

6. Nothing said above should be understood as expressing any view upon the counterclaim, which the
trial court will decide on its own merits in accordance with law.

7. In view of the above, the appeals are dismissed with no order as to costs whatsoever.
"""

UNRELATED = """1. Leave granted in this matter which arises from an eviction decree.

2. A notice under Section 106 of the Transfer of Property Act is mandatory before a suit for
eviction is instituted, and its absence is fatal to the suit however strong the merits.

3. The requirement is not a mere formality and cannot be dispensed with on the ground that the
tenant had notice of the landlord's intention from some other source altogether.

4. The decree of the trial court was accordingly without jurisdiction and the High Court ought to
have said so instead of remitting the matter for a fresh trial.

5. The findings recorded on the question of default are not disturbed and will bind the parties in
any fresh proceeding that the landlord may choose to institute.

6. The tenant is accordingly entitled to succeed and the appeal is allowed with costs throughout.
"""


def _add(session, key: str, title: str, text: str, *, year: int) -> Judgment:
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
    session.add(
        CitationAlias(
            judgment_id=judgment.id,
            reporter="SCC",
            citation_string=f"({year}) 4 SCC 118",
            normalized=f"SCC:{year}:4:118",
        )
    )
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path=key, page_count=4, headnote="", judgment=text),
    )
    return judgment


@pytest.fixture
def corpus(session):
    _add(session, "INSC:2019:1", "ALPHA versus BETA", HOLDING, year=2019)
    _add(session, "INSC:2020:2", "GAMMA versus DELTA", UNRELATED, year=2020)
    session.commit()
    build_index(session)
    return session


# --- the queries ----------------------------------------------------------------------------------


def test_a_fragment_is_a_run_from_the_middle_of_the_line() -> None:
    sentence = (
        "A misrepresentation of a material fact vitiates the consent of the contracting party only "
        "where it induced the contract and the burden of proving inducement lies upon the party."
    )
    fragment = _fragment(sentence)
    assert fragment is not None
    assert len(fragment.split()) == FRAGMENT_WORDS
    assert fragment in sentence
    # Not the opening words, which would make the query a prefix rather than a half-memory.
    assert not sentence.startswith(fragment)


def test_a_window_of_case_numbers_is_not_offered_as_a_query() -> None:
    """"(A2, A4, A 7, AS, and A 11)" is not something anyone searches for."""
    sentence = (
        "It was submitted by counsel that their (A2, A4, A 7, AS, and A 11) position at the "
        "material time was such that no inference of common intention could properly arise."
    )
    fragment = _fragment(sentence)
    assert fragment is not None
    readable = sum(1 for w in fragment.split() if w.strip(".,;:()[]").isalpha())
    assert readable >= 8


def test_a_sentence_too_short_to_shorten_yields_no_fragment() -> None:
    assert _fragment("The appeal is allowed.") is None


def test_items_carry_the_answer_before_the_search_runs(corpus) -> None:
    items = build_items(corpus, judgments=2, per_judgment=1, seed_value=7)
    assert items
    for item in items:
        assert item.judgment_key in {"INSC:2019:1", "INSC:2020:2"}
        assert item.paragraph_label
        assert item.kind in {VERBATIM, FRAGMENT}
        assert item.query in item.sentence


# --- the search -----------------------------------------------------------------------------------


def test_a_line_finds_its_own_paragraph(corpus) -> None:
    item = RetrievalItem(
        judgment_key="INSC:2019:1",
        paragraph_label="3",
        sentence=(
            "A misrepresentation of a material fact vitiates the consent of the contracting party "
            "only where it induced the contract, and the burden of proving that inducement lies "
            "upon the party alleging it."
        ),
        query=(
            "A misrepresentation of a material fact vitiates the consent of the contracting party "
            "only where it induced the contract, and the burden of proving that inducement lies "
            "upon the party alleging it."
        ),
        kind=VERBATIM,
    )
    outcome = run_item(corpus, item)
    assert outcome.judgment_rank == 1
    assert outcome.paragraph_rank == 1
    assert outcome.line_matched


def test_counsels_submission_is_not_offered_as_the_source(corpus) -> None:
    """Paragraph 2 states the rule more baldly than the court does, and is not authority for it."""
    item = RetrievalItem(
        judgment_key="INSC:2019:1",
        paragraph_label="2",
        sentence="any misrepresentation whatsoever vitiates consent in a commercial contract",
        query="any misrepresentation whatsoever vitiates consent in a commercial contract",
        kind=VERBATIM,
    )
    outcome = run_item(corpus, item)
    assert outcome.paragraph_rank is None


def test_a_proposition_the_corpus_does_not_hold_finds_nothing_of_its_own(corpus) -> None:
    item = RetrievalItem(
        judgment_key="INSC:1999:9",
        paragraph_label="4",
        sentence="A promissory estoppel cannot be invoked against a statute in terms.",
        query="A promissory estoppel cannot be invoked against a statute in terms.",
        kind=VERBATIM,
    )
    outcome = run_item(corpus, item)
    assert outcome.judgment_rank is None
    assert outcome.paragraph_rank is None
    assert not outcome.line_matched


# --- the scoring ----------------------------------------------------------------------------------


def _outcome(kind: str, judgment_rank, paragraph_rank, line_matched=False) -> Outcome:
    item = RetrievalItem("INSC:2019:1", "3", "a sentence", "a sentence", kind)
    return Outcome(item, judgment_rank, paragraph_rank, line_matched, None, 0.1)


def test_recall_counts_the_rank_against_the_cutoff() -> None:
    report = RetrievalReport(
        outcomes=[
            _outcome(VERBATIM, 1, 1),
            _outcome(VERBATIM, 4, 7),
            _outcome(VERBATIM, None, None),
            _outcome(VERBATIM, 2, 3),
        ]
    )
    assert report.judgment_recall(VERBATIM, 1) == 0.25
    assert report.judgment_recall(VERBATIM, 5) == 0.75
    assert report.paragraph_recall(VERBATIM, 5) == 0.5
    assert report.paragraph_recall(VERBATIM, 10) == 0.75


def test_the_two_query_shapes_are_scored_apart() -> None:
    report = RetrievalReport(outcomes=[_outcome(VERBATIM, 1, 1), _outcome(FRAGMENT, None, None)])
    assert report.judgment_recall(VERBATIM, 1) == 1.0
    assert report.judgment_recall(FRAGMENT, 1) == 0.0


def test_line_accuracy_is_measured_only_where_the_paragraph_was_found() -> None:
    """A search that never reached the paragraph cannot have named the wrong line in it."""
    report = RetrievalReport(
        outcomes=[
            _outcome(VERBATIM, 1, 1, line_matched=True),
            _outcome(VERBATIM, 1, 2, line_matched=False),
            _outcome(VERBATIM, None, None),
        ]
    )
    assert report.line_accuracy(VERBATIM) == 0.5


def test_a_kind_with_no_queries_reports_nothing_rather_than_zero() -> None:
    report = RetrievalReport(outcomes=[_outcome(VERBATIM, 1, 1)])
    assert report.judgment_recall(FRAGMENT, 1) is None
    assert FRAGMENT not in "\n".join(format_retrieval(report))
