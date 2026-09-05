"""Measuring the drafting gate.

What is worth testing in an evaluation harness is the thing that would make its numbers a lie: that
it draws items whose label is known by construction, that it follows the whole chain rather than one
link of it, and that the one row nobody may misread — a proposition bound to counsel's submission —
is counted from the binding and not assumed.

The corpus here is one judgment written to contain holdings and a paragraph reciting counsel's
submission, which is the pair the report turns on.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, Judgment
from orderorder.engine.authority import BOUND, UNCHECKED
from orderorder.engine.search import build_index
from orderorder.evaluation.gate import (
    COUNSEL,
    DISSENT,
    HOLDING,
    GateItem,
    GateOutcome,
    GateReport,
    build_items,
    format_gate,
    run_item,
)
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

HOLDING_SENTENCE = (
    "A misrepresentation of a material fact vitiates the consent of the contracting party only "
    "where it induced the contract to be entered into by that party."
)
COUNSEL_SENTENCE = (
    "Any misrepresentation whatsoever vitiates consent in a commercial contract, however "
    "immaterial the misstatement made to the other contracting party may have been."
)

JUDGMENT = f"""1. Leave granted in the special leave petition filed by the appellant in this matter.

2. It was strenuously contended on behalf of the appellant that {COUNSEL_SENTENCE[0].lower()}{COUNSEL_SENTENCE[1:]}

3. {HOLDING_SENTENCE}

4. The doctrine of frustration has no application where the parties have expressly allocated the
risk of the supervening event between themselves in the contract that they made.

5. A notice under Section 106 of the Transfer of Property Act is mandatory before a suit for
eviction is instituted, and its absence is fatal to the suit however strong the merits may be.

6. The burden of proving that a misstatement induced the contract lies upon the party who alleges
that it did, and no presumption arises in favour of that party merely from the misstatement.

7. In view of the above, the appeals are dismissed with no order as to costs whatsoever.
"""


@pytest.fixture
def corpus(session):
    judgment = Judgment(
        canonical_key="INSC:2019:1",
        court="Supreme Court of India",
        title="ALPHA versus BETA",
        source="aws_open_data",
        source_id="INSC:2019:1",
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
    return session


def _outcome(kind: str, **kwargs) -> GateOutcome:
    base = {
        "item": GateItem("INSC:2019:1", "2", "some proposition or other here", kind),
        "raw_candidates": 4,
        "raw_not_the_court": 2,
        "raw_source_rank": 1,
        "candidates": 3,
        "source_survived": False,
        "refused_not_the_court": 0,
        "refused_doubtful": 0,
        "source_refusal": None,
        "status": UNCHECKED,
        "chosen_key": None,
        "chosen_label": None,
        "seconds": 0.1,
    }
    base.update(kwargs)
    return GateOutcome(**base)


# --- drawing the items ------------------------------------------------------------------------------


def test_items_carry_the_paragraph_they_were_lifted_from(corpus) -> None:
    """The label is known by construction; nothing here decides afterwards what an item was."""
    items = build_items(corpus, judgments=1)
    assert items
    for item in items:
        assert item.judgment_key == "INSC:2019:1"
        assert item.paragraph_label
        assert item.kind in {HOLDING, COUNSEL, DISSENT}


def test_a_holding_and_a_submission_are_drawn_from_the_same_judgment(corpus) -> None:
    kinds = {i.kind for i in build_items(corpus, judgments=1)}
    assert HOLDING in kinds
    assert COUNSEL in kinds


# --- following the chain ----------------------------------------------------------------------------


def test_the_raw_field_is_measured_before_the_voice_filter(corpus) -> None:
    """One column is what a word search returns and the other is what survives. Both are needed.

    Measuring only the second would report that nothing uncitable ever reaches the gate, which is
    true and says nothing about how much of it there was.
    """
    item = next(i for i in build_items(corpus, judgments=1) if i.kind == COUNSEL)
    outcome = run_item(corpus, item, None)
    assert outcome.raw_candidates >= 1
    assert outcome.raw_not_the_court >= 1
    assert outcome.raw_source_rank is not None


def test_counsels_own_words_do_not_survive_to_the_gate(corpus) -> None:
    item = next(i for i in build_items(corpus, judgments=1) if i.kind == COUNSEL)
    outcome = run_item(corpus, item, None)
    assert not outcome.source_survived
    assert outcome.status != BOUND


def test_with_no_model_a_holding_is_unchecked_and_never_refused(corpus) -> None:
    """Three-state honesty in the direction the tool writes rather than reads."""
    item = next(i for i in build_items(corpus, judgments=1) if i.kind == HOLDING)
    outcome = run_item(corpus, item, None)
    assert outcome.status == UNCHECKED


# --- the row nobody may misread ---------------------------------------------------------------------


def test_a_false_bind_is_counted_from_the_binding(corpus) -> None:
    """Counted from what was actually chosen, not from the status alone."""
    report = GateReport(outcomes=[_outcome(COUNSEL, status=BOUND, chosen_key="INSC:2019:1", chosen_label="2")])
    assert len(report.false_binds) == 1
    assert "would have written into a draft" in "\n".join(format_gate(report))


def test_binding_a_holding_to_its_own_paragraph_is_not_a_false_bind() -> None:
    report = GateReport(outcomes=[_outcome(HOLDING, status=BOUND, chosen_key="INSC:2019:1", chosen_label="2")])
    assert report.false_binds == []


def test_binding_counsels_proposition_to_a_different_paragraph_is_not_a_false_bind() -> None:
    """A real holding elsewhere that says the same thing is a correct answer, not a miss."""
    report = GateReport(outcomes=[_outcome(COUNSEL, status=BOUND, chosen_key="INSC:2020:9", chosen_label="7")])
    assert report.false_binds == []


def test_a_clean_run_says_so_rather_than_saying_nothing() -> None:
    text = "\n".join(format_gate(GateReport(outcomes=[_outcome(COUNSEL)])))
    assert "No proposition was bound to the paragraph it was lifted from" in text


def test_the_report_says_when_nothing_could_be_bound() -> None:
    """A table of zeroes in the `bound` column means one thing with a model and another without."""
    text = "\n".join(format_gate(GateReport(outcomes=[_outcome(HOLDING)], model_configured=False)))
    assert "no model configured" in text
    assert "structurally zero" in text


def test_a_missing_row_is_not_a_clean_row() -> None:
    """No dissent in the draw is not the same as no dissent got through, and must not read as it."""
    text = "\n".join(format_gate(GateReport(outcomes=[_outcome(COUNSEL)])))
    assert "missing rather than clean" in text


def test_the_chain_is_reported_as_a_chain(corpus) -> None:
    report = GateReport(
        outcomes=[_outcome(COUNSEL, raw_source_rank=1, source_survived=False)],
        model_configured=True,
    )
    line = next(x for x in format_gate(report) if x.startswith("Counsel's submission:"))
    assert "within reach for 1 of 1" in line
    assert "0 survived" in line
    assert "0 were bound" in line
