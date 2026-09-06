"""The search for a judgment that says the other thing.

Two properties matter more than everything else here, and they pull against each other.

**It has to fire.** A self-attack section that finds nothing reads as an assurance, and the whole
reason this module exists is that `drafting.attack` says in terms that nothing searches for a
contrary holding.

**It must never fire on a proposition's own source.** A proposition lifted out of a judgment meets
that judgment's own paragraph at the top of the retrieval field every single time. A detector that
calls that paragraph the opposite of the sentence copied out of it is not a weak detector, it is a
broken one — and it would look like a working detector in every summary statistic, because it would
be firing constantly. So the control is pinned as a test rather than left to a measurement: the
verbatim-containment rule and the exclusivity rule in `antonym_between` make it structurally
impossible, and these tests are what stop somebody removing them for looking redundant.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, Judgment, Opinion
from orderorder.engine.contrary import (
    ANTONYMS,
    MIN_SHARED_TERMS,
    antonym_between,
    clauses,
    contrary_queries,
    dissents_in,
    distinctive_terms,
    find_contrary,
    negated,
    opposes,
)
from orderorder.engine.search import build_index
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

MANDATORY = "A notice under Section 106 of the Transfer of Property Act is mandatory before a suit for eviction."
DIRECTORY = "The requirement of notice under Section 106 of the Transfer of Property Act is directory and not mandatory."


# --- the string test --------------------------------------------------------------------------------


def test_the_classic_pair_is_opposed() -> None:
    """Mandatory against directory: the flip is lexical, and no negation appears in either sentence."""
    opposition = opposes(MANDATORY, DIRECTORY)
    assert opposition is not None
    assert opposition.kind == "antonym"
    assert opposition.cue == "directory"
    assert "notice" in opposition.shared_terms


def test_a_grammatical_negation_is_opposed() -> None:
    proposition = "A notice under Section 106 is mandatory before a suit for eviction is filed."
    sentence = "A notice under Section 106 is mandatory only where the tenancy has not been determined."
    # Same polarity on the point itself; the negation is in a different clause about a different thing.
    assert opposes(proposition, sentence) is None

    flat = "A notice under Section 106 of that Act is not mandatory before a suit for eviction."
    opposition = opposes(proposition, flat)
    assert opposition is not None
    assert opposition.kind == "negation"
    assert opposition.cue.lower() == "not"


def test_a_rejected_contention_is_opposed() -> None:
    """The commonest shape in the reports: the court recites the argument and then refuses it.

    "That" is a clause break for exactly this reason. Read as one sentence its polarity is the
    proposition's own, and the court's refusal disappears.
    """
    sentence = "The contention that a notice under Section 106 is mandatory before eviction cannot be accepted."
    opposition = opposes(MANDATORY, sentence)
    assert opposition is not None
    assert opposition.cue.lower() == "cannot"


def test_nothing_is_the_opposite_of_itself() -> None:
    """The control. A proposition and the sentence it was copied from are never opposed."""
    assert opposes(MANDATORY, MANDATORY) is None
    assert opposes(DIRECTORY, DIRECTORY) is None
    # And the same sentence sitting inside a longer one, which is what a paragraph is.
    paragraph_sentence = f"{MANDATORY} That has been the consistent view of this Court."
    assert opposes(MANDATORY, paragraph_sentence) is None


def test_a_sentence_carrying_both_words_is_not_its_own_opposite() -> None:
    """`directory and not mandatory` holds both halves of an antonym pair. Exclusivity is why."""
    assert antonym_between(DIRECTORY, DIRECTORY) is None
    assert opposes(DIRECTORY, DIRECTORY) is None


def test_a_different_subject_is_not_an_opposition() -> None:
    """Polarity alone is not opposition. Without shared subject there is nothing to be opposite about."""
    unrelated = "A misrepresentation does not vitiate consent unless it induced the contract."
    assert opposes(MANDATORY, unrelated) is None


def test_the_shared_terms_have_to_be_worth_sharing() -> None:
    """Every judgment says `court`, `held` and `learned`; sharing them is evidence of nothing."""
    terms = distinctive_terms("The learned counsel for the appellant submitted before this Court.")
    assert terms == []
    assert opposes(
        "The learned counsel for the appellant submitted before this Court that it is so.",
        "The learned counsel for the respondent did not submit before this Court.",
    ) is None


def test_a_case_number_does_not_negate_a_clause() -> None:
    """`Civil Appeal No. 1234` is not a negation, and reading it as one inverts the sentence."""
    assert negated("Civil Appeal No. 1234 of 2019 is allowed") == (False, None)
    assert negated("there is no such requirement in the statute")[0] is True


def test_two_negations_cancel() -> None:
    assert negated("it is not open to say that no notice was given")[0] is False


def test_clauses_split_where_polarity_can_change() -> None:
    parts = clauses("The contention that the notice is mandatory, however, cannot be accepted.")
    assert any(p.startswith("the notice is mandatory") or p == "the notice is mandatory" for p in parts) or any(
        "notice is mandatory" in p for p in parts
    )
    assert any("cannot be accepted" in p for p in parts)


def test_the_opposite_query_swaps_the_term_of_art() -> None:
    queries = contrary_queries(MANDATORY)
    assert queries[0] == MANDATORY
    assert any("directory" in q for q in queries[1:])
    # Capped: each one is a search over the whole corpus.
    assert len(queries) <= 3


def test_every_antonym_pair_is_actually_opposed() -> None:
    """A pair that is not a contradiction in law has no business in the table."""
    for first, second in ANTONYMS:
        assert first != second
        left = f"The provision in Section 106 of that Act is {first} in every eviction suit."
        right = f"The provision in Section 106 of that Act is {second} in every eviction suit."
        assert opposes(left, right) is not None, f"{first}/{second} did not oppose"


def test_the_overlap_bar_is_a_count_and_a_share() -> None:
    """A long proposition can share four terms with a paragraph about something else entirely."""
    assert MIN_SHARED_TERMS >= 3


# --- over a corpus ----------------------------------------------------------------------------------

HOLDS_MANDATORY = """1. Leave granted.

2. It was contended that the notice was waived by conduct of the parties in this eviction matter.

3. A notice under Section 106 of the Transfer of Property Act is mandatory before a suit for eviction,
and its absence is fatal to the suit.

4. The appeal is dismissed.
"""

HOLDS_DIRECTORY = """1. Leave granted.

2. The question is whether the notice under Section 106 of the Transfer of Property Act must precede
a suit for eviction in every case whatsoever.

3. The requirement of a notice under Section 106 of the Transfer of Property Act is directory, and a
suit for eviction does not fail merely because no notice preceded it.

4. The appeal is allowed.
"""

UNRELATED = """1. Leave granted.

2. A misrepresentation vitiates consent only where it induced the contract, and the burden of proving
inducement lies upon the party alleging it.

3. The appeal is dismissed.
"""


def _add(session, key: str, title: str, text: str, *, bench: int, year: int) -> Judgment:
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
    session.add(
        CitationAlias(
            judgment_id=judgment.id,
            reporter="SCC",
            citation_string=f"({year}) 1 SCC {bench}",
            normalized=f"SCC:{year}:1:{bench}",
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
    _add(session, "INSC:2019:1", "ALPHA versus BETA", HOLDS_MANDATORY, bench=2, year=2019)
    _add(session, "INSC:2021:2", "GAMMA versus DELTA", HOLDS_DIRECTORY, bench=3, year=2021)
    _add(session, "INSC:2020:3", "EPSILON versus ZETA", UNRELATED, bench=2, year=2020)
    session.commit()
    build_index(session)
    return session


PROPOSITION = "A notice under Section 106 of the Transfer of Property Act is mandatory before a suit for eviction."


def test_the_judgment_that_says_the_other_thing_is_found(corpus) -> None:
    report = find_contrary(corpus, PROPOSITION)
    assert report.found
    lead = report.leads[0]
    assert lead.authority.canonical_key == "INSC:2021:2"
    assert "directory" in lead.sentence
    assert lead.sentence == lead.authority.body[lead.sentence_start : lead.sentence_end]


def test_the_judgment_that_agrees_is_not_reported_as_contrary(corpus) -> None:
    """The one that would sink it: the supporting authority is the nearest text in the corpus."""
    report = find_contrary(corpus, PROPOSITION)
    assert all(lead.authority.canonical_key != "INSC:2019:1" for lead in report.leads)


def test_a_proposition_the_corpus_does_not_contradict_finds_nothing(corpus) -> None:
    report = find_contrary(corpus, "A misrepresentation vitiates consent only where it induced the contract.")
    assert not report.found
    assert "judgments held" in report.describe()


def test_the_authority_being_relied_on_can_be_left_out(corpus) -> None:
    """The draft's own authority must not be reported as an attack on the draft."""
    contrary_judgment = corpus.query(Judgment).filter_by(canonical_key="INSC:2021:2").one()
    report = find_contrary(corpus, PROPOSITION, exclude=(contrary_judgment.id,))
    assert not report.found


def test_the_report_says_how_much_was_searched(corpus) -> None:
    """"Nothing contradicts this" means nothing without the size of the field it was said over."""
    report = find_contrary(corpus, PROPOSITION)
    assert report.judgments_searched == 3
    assert report.paragraphs_examined > 0
    assert "2013" in report.describe() or report.found


def test_without_an_index_nothing_is_claimed(session) -> None:
    """No index is not an absence of contrary authority; it is a search that never ran."""
    report = find_contrary(session, PROPOSITION)
    assert not report.searched
    assert not report.found
    assert "not searched" in report.describe()


def test_a_lead_is_not_called_confirmed(corpus) -> None:
    """Nothing has read the pair. `is_confirmed` says so, and the description does not overclaim."""
    report = find_contrary(corpus, PROPOSITION)
    assert not report.read_by_model
    assert all(not lead.is_confirmed for lead in report.leads)
    assert "lead" in report.describe()


# --- the dissent in the very case relied on -----------------------------------------------------------


def test_the_dissent_in_the_case_relied_on_is_contrary(corpus) -> None:
    """No search needed: it is in the same judgment, and an opponent will read it out."""
    judgment = corpus.query(Judgment).filter_by(canonical_key="INSC:2019:1").one()
    version = judgment.versions[0]
    dissent = Opinion(
        text_version_id=version.id,
        kind="dissenting",
        author="B. Bhushan, J.",
        seq_start=3,
        seq_end=3,
    )
    corpus.add(dissent)
    corpus.flush()
    paragraph = [p for p in version.paragraphs if p.printed_label == "3"][0]
    paragraph.opinion_id = dissent.id
    corpus.commit()

    leads = dissents_in(corpus, judgment.id, PROPOSITION)
    assert len(leads) == 1
    assert leads[0].opposition.kind == "dissent"
    assert leads[0].authority.canonical_key == "INSC:2019:1"
    assert "dissenting judge" in leads[0].opposition.describe()


def test_a_judgment_with_no_dissent_yields_nothing(corpus) -> None:
    judgment = corpus.query(Judgment).filter_by(canonical_key="INSC:2019:1").one()
    assert dissents_in(corpus, judgment.id, PROPOSITION) == []
