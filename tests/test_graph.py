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


# --- voice, opinion and weight, end to end ------------------------------------

DIVIDED_JUDGMENT = """1. Feeling aggrieved by the impugned judgment, the appellant preferred these appeals.

2. It was strenuously contended on behalf of the appellant that a misrepresentation vitiates
consent in every commercial contract, howsoever slight the misstatement may be.

3. A misrepresentation vitiates consent only where it induced the contract, and the burden
of proving inducement lies upon the party alleging it.

4. For the reasons stated above, the appeals are dismissed with no order as to costs.

NARIMAN, J. (dissenting)

5. In my respectful view a misrepresentation vitiates consent in every commercial contract,
whatever the materiality of the misstatement.
"""


@pytest.fixture
def divided(session):
    """A judgment with a dissent, so opinion boundaries are real rather than assumed."""
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
    session.add(
        CitationAlias(
            judgment_id=judgment.id,
            reporter="SCR",
            citation_string="[2019] 9 S.C.R. 593",
            normalized="SCR:2019:9:593",
        )
    )
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path="x", page_count=6, headnote="", judgment=DIVIDED_JUDGMENT),
    )
    session.commit()
    return session


def test_the_dissent_is_stored_as_its_own_opinion(divided) -> None:
    from orderorder.db.models import Judgment as J
    from orderorder.ingest.store import load_paragraphs

    judgment = divided.query(J).one()
    kinds = {p.printed_label: p.opinion_kind for p in load_paragraphs(divided, judgment.id)}
    assert kinds["3"] == "majority"
    assert kinds["5"] == "dissenting"


def test_a_dissent_cited_as_the_holding_is_caught(divided) -> None:
    answer = ScopeAssessment(
        paragraph_label="5",
        quote="a misrepresentation vitiates consent in every commercial contract",
        support="full",
        confidence=0.9,
    )
    text = (
        "A misrepresentation vitiates consent in every commercial contract, as held in "
        "[2019] 9 S.C.R. 593, para 5."
    )
    verdict = verify_text(divided, text, StubModel(answer))[0]
    assert verdict.quote_verified
    assert verdict.voice is not None and verdict.voice.voice == "court_dissent"
    assert any(f.mode == 6 for f in verdict.findings)
    assert verdict.grade == "D"


def test_counsels_submission_cited_as_the_holding_is_caught(divided) -> None:
    answer = ScopeAssessment(
        paragraph_label="2",
        quote="a misrepresentation vitiates consent in every commercial contract",
        support="full",
        confidence=0.9,
    )
    text = (
        "A misrepresentation vitiates consent in every commercial contract, as held in "
        "[2019] 9 S.C.R. 593, para 2."
    )
    verdict = verify_text(divided, text, StubModel(answer))[0]
    assert verdict.voice is not None and verdict.voice.voice == "counsel_argument"
    assert any(f.mode == 5 for f in verdict.findings)
    assert verdict.grade == "D"


def test_the_majority_speaking_is_not_marked_down(divided) -> None:
    answer = ScopeAssessment(
        paragraph_label="3",
        quote="A misrepresentation vitiates consent only where it induced the contract",
        support="full",
        confidence=0.9,
    )
    text = (
        "A misrepresentation vitiates consent where it induced the contract: "
        "[2019] 9 S.C.R. 593, para 3."
    )
    verdict = verify_text(divided, text, StubModel(answer))[0]
    assert verdict.voice is not None and verdict.voice.voice == "court_majority"
    assert not verdict.findings
    assert verdict.grade == "A"


def test_the_dissent_is_caught_with_no_model_at_all(divided) -> None:
    """Whose words they are is structural, so it survives having no API key."""
    text = "The rule is absolute: see [2019] 9 S.C.R. 593, para 5."
    verdict = verify_text(divided, text, None)[0]
    assert verdict.support == "not_assessed"
    assert verdict.voice is not None and verdict.voice.voice == "court_dissent"
    assert any(f.mode == 6 for f in verdict.findings)


def test_a_paragraph_that_merely_ranked_well_is_not_attributed(divided) -> None:
    """No pinpoint and no verified quote means no paragraph is definite enough to attribute."""
    fabricated = ScopeAssessment(
        paragraph_label="3",
        quote="a sentence that appears nowhere in this judgment at all",
        support="full",
        confidence=0.9,
    )
    text = "A misrepresentation vitiates consent: [2019] 9 S.C.R. 593."
    verdict = verify_text(divided, text, StubModel(fabricated))[0]
    assert verdict.voice is None
    assert not any(f.mode in {5, 6} for f in verdict.findings)
