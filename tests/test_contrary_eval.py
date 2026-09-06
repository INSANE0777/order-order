"""Measuring the contrary search.

What is worth testing in an evaluation harness is whatever would make its numbers a lie. Here that is
the negation: every `opposed` item is built by turning a court's own sentence around, so a `negate`
that quietly returned the sentence unchanged would produce an item set in which the two rows of the
report are the same query twice, and the discrimination number — the only number in the report that
is not circular — would be a measurement of nothing at all.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, Judgment
from orderorder.engine.search import build_index
from orderorder.evaluation.contrary import (
    AGREED,
    OPPOSED,
    ContraryItem,
    build_items,
    format_contrary,
    format_reading,
    negate,
    read_pairs,
    run_contrary,
    run_item,
    source_lead,
)
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("A notice is mandatory before eviction.", "A notice is not mandatory before eviction."),
        ("The period cannot be extended.", "The period can be extended."),
        ("Such an award shall be set aside.", "Such an award shall not be set aside."),
        ("The court must consider the plea.", "The court need not consider the plea."),
        ("The provision does not apply here.", "The provision does apply here."),
        ("Section 5 has no application to appeals.", "Section 5 has application to appeals."),
    ],
)
def test_a_holding_is_turned_around(sentence: str, expected: str) -> None:
    """Crude on purpose. It stands in for what the other side asserts, not for good prose."""
    assert negate(sentence) == expected


def test_the_first_site_wins() -> None:
    """Two auxiliaries, and the main verb is almost always the one the court reached first."""
    assert negate("A notice is mandatory and the suit is competent.") == (
        "A notice is not mandatory and the suit is competent."
    )


def test_a_sentence_with_nowhere_to_put_a_negation_is_dropped() -> None:
    """Dropped rather than mangled, which is why an item set is smaller than the draw."""
    assert negate("Leave granted.") is None
    assert negate("Accordingly, the appeals stand disposed of in the above terms.") is None


HOLDING = (
    "A notice under Section 106 of the Transfer of Property Act is mandatory before a suit for "
    "eviction is instituted by the landlord against his tenant."
)

JUDGMENT = f"""1. Leave granted in the special leave petition filed by the appellant in this matter.

2. It was strenuously contended on behalf of the appellant that any misrepresentation whatsoever
vitiates consent in a commercial contract, however immaterial the misstatement may have been.

3. {HOLDING}

4. The doctrine of frustration has no application where the parties have expressly allocated the
risk of the supervening event between themselves in the contract that they made.

5. A misrepresentation of a material fact vitiates the consent of the contracting party only where
it induced the contract to be entered into by that party to the agreement.

6. The burden of proving that a misstatement induced the contract lies upon the party who alleges
that it did, and no presumption arises in favour of that party from the misstatement alone.

7. In view of the above, the appeals are dismissed with no order as to costs whatsoever.
"""

CONTRADICTS = """1. Leave granted in this matter after hearing both the parties at some length.

2. The question arising in this appeal concerns the termination of a tenancy by the landlord.

3. The requirement of a notice under Section 106 of the Transfer of Property Act is directory, and
a suit for eviction instituted by the landlord does not fail merely because no notice preceded it.

4. The tenant is entitled to no further protection than the statute itself confers upon him.

5. The findings recorded by the trial court on the question of default are not open to challenge.

6. The High Court was accordingly in error in dismissing the suit on that preliminary ground.

7. The appeal is allowed and the suit is remanded for trial on the remaining issues.
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
        ExtractedJudgment(source_path=key, page_count=8, headnote="", judgment=text),
    )
    return judgment


@pytest.fixture
def corpus(session):
    _add(session, "INSC:2019:1", "ALPHA versus BETA", JUDGMENT, bench=2, year=2019)
    _add(session, "INSC:2021:2", "GAMMA versus DELTA", CONTRADICTS, bench=3, year=2021)
    session.commit()
    build_index(session)
    return session


def test_every_holding_is_drawn_twice(corpus) -> None:
    """One sentence, two propositions, and the pair is what the report reads."""
    items = build_items(corpus, judgments=2, per_judgment=1)
    assert items
    kinds = [item.kind for item in items]
    assert kinds.count(OPPOSED) == kinds.count(AGREED)
    for opposed, agreed in zip(items[::2], items[1::2], strict=True):
        assert opposed.kind == OPPOSED and agreed.kind == AGREED
        assert opposed.holding == agreed.holding
        assert agreed.query == agreed.holding
        assert opposed.query != opposed.holding


def test_the_negated_holding_finds_the_judgment_that_says_the_other_thing(corpus) -> None:
    """Two answers are right here, and the harness has to count them differently.

    The advocate arguing that notice is *not* mandatory meets both the judgment holding that it is —
    which is the source paragraph, and is contrary by construction — and the judgment calling the
    requirement directory, which the search had to find. `source_rank` counts the first; the leads
    count the second.
    """
    item = ContraryItem("INSC:2019:1", "3", HOLDING, negate(HOLDING), OPPOSED)
    outcome = run_item(corpus, item)
    assert outcome.source_flagged
    assert outcome.leads >= 2


def test_the_holding_as_written_does_not_flag_its_own_paragraph(corpus) -> None:
    """The control. Nothing may report a paragraph as the opposite of a sentence copied out of it."""
    item = ContraryItem("INSC:2019:1", "3", HOLDING, HOLDING, AGREED)
    outcome = run_item(corpus, item)
    assert not outcome.source_flagged


def test_the_source_paragraph_is_retrieved_either_way(corpus) -> None:
    """Retrieval and detection are different questions, and the report keeps them apart."""
    for query, kind in ((negate(HOLDING), OPPOSED), (HOLDING, AGREED)):
        outcome = run_item(corpus, ContraryItem("INSC:2019:1", "3", HOLDING, query, kind))
        assert outcome.source_retrieved, kind


class StubModel:
    """Answers the same relation to everything, which is the failure the control exists to catch."""

    def __init__(self, *relations: str):
        self.relations = list(relations)
        self.calls = 0

    def invoke(self, prompt: str):
        from orderorder.engine.schemas import OppositionAssessment

        relation = self.relations[min(self.calls, len(self.relations) - 1)]
        self.calls += 1
        # A quote that will ground: the prompt carries the paragraph, so copy from it.
        line = prompt.split("copied from paragraph")[-1].split("\n")[1] if "copied from" in prompt else ""
        return OppositionAssessment(relation=relation, quote=line.strip() or None)


def test_the_source_paragraph_is_found_without_a_search(corpus) -> None:
    """The pair is known: this sentence, that paragraph. Nothing needs retrieving to ask about it."""
    item = ContraryItem("INSC:2019:1", "3", HOLDING, negate(HOLDING), OPPOSED)
    lead = source_lead(corpus, item)
    assert lead is not None
    assert lead.sentence == HOLDING
    assert HOLDING in lead.authority.body
    assert lead.authority.canonical_key == "INSC:2019:1"


def test_a_model_that_says_opposite_to_everything_is_caught(corpus) -> None:
    """The whole point of the control: it scores 1 of 2, and the report names the half it failed."""
    items = build_items(corpus, judgments=2, per_judgment=1)
    report = run_contrary(corpus, items)
    read_pairs(corpus, report, StubModel("opposite"), limit=1)

    text = "\n".join(format_reading(report))
    assert "1 of 2 answers were the expected one" in text
    assert "of the 1 controls" in text or "controls" in text
    read = [o for o in report.outcomes if o.reading is not None]
    assert [o.reading for o in read] == ["opposite", "opposite"]
    assert sum(1 for o in read if o.reading == o.reading_expected) == 1


def test_a_model_that_reads_the_texts_scores_both(corpus) -> None:
    items = build_items(corpus, judgments=2, per_judgment=1)
    report = run_contrary(corpus, items)
    read_pairs(corpus, report, StubModel("opposite", "same"), limit=1)
    read = [o for o in report.outcomes if o.reading is not None]
    assert sum(1 for o in read if o.reading == o.reading_expected) == 2


def test_the_report_says_which_number_is_circular(corpus) -> None:
    items = build_items(corpus, judgments=2, per_judgment=1)
    report = run_contrary(corpus, items)
    text = "\n".join(format_contrary(report))
    assert "not a finding" in text
    assert "discrimination" in text
    assert "upper bound" in text
