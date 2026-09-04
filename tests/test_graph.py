"""The engine end to end, as a LangGraph state graph.

These build a small corpus in an in-memory database and run whole passages through the graph with a
stub model, so the whole path is exercised with no network and no API key.
"""

from __future__ import annotations

import pytest

from orderorder.db.models import Judgment
from orderorder.engine.graph import _sentence_around, verify_text
from orderorder.engine.schemas import ScopeAssessment
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

JUDGMENT_TEXT = """1. Feeling aggrieved by the impugned judgment, the appellant preferred these appeals.

2. The facts of the case leading to these appeals in nutshell are as under.

3. A misrepresentation vitiates consent only where it induced the contract, and the burden
of proving inducement lies upon the party alleging it.

4. In view of the above, the appeals are dismissed with no order as to costs.
"""


class StubModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def invoke(self, prompt: str):
        self.calls += 1
        return self.answer


@pytest.fixture
def corpus(session):
    """One judgment, reachable by its SCR citation and its neutral citation."""
    from orderorder.db.models import CitationAlias

    judgment = Judgment(
        canonical_key="INSC:2019:770",
        court="Supreme Court of India",
        title="GURMIT SINGH BHATIA versus KIRAN KANT ROBINSON",
        source="aws_open_data",
        source_id="2019_9_593_605",
    )
    session.add(judgment)
    session.flush()
    for reporter, text, normalized in [
        ("INSC", "2019 INSC 770", "INSC:2019:770"),
        ("SCR", "[2019] 9 S.C.R. 593", "SCR:2019:9:593"),
    ]:
        session.add(
            CitationAlias(
                judgment_id=judgment.id, reporter=reporter, citation_string=text, normalized=normalized
            )
        )
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path="x", page_count=5, headnote="", judgment=JUDGMENT_TEXT),
    )
    session.commit()
    return session


def _supported() -> ScopeAssessment:
    return ScopeAssessment(
        paragraph_label="3",
        quote="A misrepresentation vitiates consent only where it induced the contract",
        support="partial",
        dropped_conditions=["where it induced the contract"],
        gap="The court confined the rule to inducement.",
        narrowed_proposition="A misrepresentation that induced the contract vitiates consent.",
        confidence=0.9,
    )


def test_a_good_citation_runs_the_whole_graph(corpus) -> None:
    text = "A misrepresentation vitiates consent, as held in [2019] 9 S.C.R. 593, para 3."
    verdicts = verify_text(corpus, text, StubModel(_supported()))
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.existence == "found"
    assert verdict.canonical_key == "INSC:2019:770"
    assert verdict.support == "partial"
    assert verdict.quote_verified
    assert verdict.paragraph_label == "3"


def test_a_phantom_short_circuits_before_the_model(corpus) -> None:
    """Nothing to read, so the model must not be called at all."""
    model = StubModel(_supported())
    verdicts = verify_text(corpus, "As held in (2019) 99 SCC 9999, the rule is settled.", model)
    assert verdicts[0].existence == "not_found"
    assert verdicts[0].grade == "F"
    assert model.calls == 0


def test_a_bad_pinpoint_is_caught(corpus) -> None:
    text = "The rule is settled: see [2019] 9 S.C.R. 593, para 73."
    verdicts = verify_text(corpus, text, StubModel(_supported()))
    assert any(f.mode == 12 for f in verdicts[0].findings)


def test_a_fabricated_quote_is_not_believed(corpus) -> None:
    """The model claims full support with a sentence that is not in the judgment."""
    fabricated = ScopeAssessment(
        paragraph_label="3",
        quote="A misrepresentation always renders the contract void from the beginning",
        support="full",
        confidence=0.95,
    )
    text = "A misrepresentation renders a contract void, as held in [2019] 9 S.C.R. 593."
    verdicts = verify_text(corpus, text, StubModel(fabricated))
    assert verdicts[0].support == "none"
    assert not verdicts[0].quote_verified
    assert verdicts[0].grade == "F"


def test_several_citations_in_one_passage(corpus) -> None:
    text = (
        "A misrepresentation vitiates consent, as held in [2019] 9 S.C.R. 593, para 3. "
        "The same was affirmed in (2019) 99 SCC 9999. "
        "It was explained again in 2019 INSC 770, para 73."
    )
    verdicts = verify_text(corpus, text, StubModel(_supported()))
    assert len(verdicts) == 3
    assert [v.existence for v in verdicts] == ["found", "not_found", "found"]
    assert any(f.mode == 1 for f in verdicts[1].findings)
    assert any(f.mode == 12 for f in verdicts[2].findings)


def test_without_a_model_the_other_checks_still_run(corpus) -> None:
    text = "The rule is settled: see [2019] 9 S.C.R. 593, para 73."
    verdicts = verify_text(corpus, text, None)
    assert verdicts[0].existence == "found"
    assert any(f.mode == 12 for f in verdicts[0].findings)
    assert verdicts[0].support == "not_assessed"
    assert verdicts[0].needs_review


def test_no_citations_yields_no_verdicts(corpus) -> None:
    assert verify_text(corpus, "This passage cites nothing at all.", None) == []


# --- sentence boundaries ------------------------------------------------------


def test_sentence_is_not_split_inside_a_citation() -> None:
    """'[2019] 9 S.C.R. 593' contains full stops that must not end the sentence."""
    text = "The plaintiff is dominus litis, as held in [2019] 9 S.C.R. 593, para 5.1. The next sentence."
    assert _sentence_around(text, text.index("S.C.R")).endswith("para 5.1.")
    assert "dominus litis" in _sentence_around(text, text.index("S.C.R"))


def test_sentence_boundaries_are_found() -> None:
    text = "First sentence here. Second sentence cites (2019) 4 SCC 1. Third sentence."
    around = _sentence_around(text, text.index("SCC"))
    assert around.startswith("Second sentence")
    assert "Third" not in around


def test_single_sentence_returns_the_whole_text() -> None:
    text = "Only one sentence citing (2019) 4 SCC 1"
    assert _sentence_around(text, 5) == text
