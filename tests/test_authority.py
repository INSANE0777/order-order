"""The gate that decides whether an authority may go into a draft.

Retrieval always returns something. A corpus of nine thousand judgments has words matching any
proposition, so a drafting tool that binds the top result to the sentence is a machine for producing
exactly the citations this engine exists to catch. Everything here is about what the gate refuses.

The other property under test is that a refusal is *useful*: it names what was considered and what is
wrong with it, because that is where the next hour of research starts.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, Judgment
from orderorder.engine.authority import (
    BOUND,
    NARROWED,
    REFUSED,
    UNCHECKED,
    _gate,
    bind_proposition,
    render_binding,
)
from orderorder.engine.citator import TreatmentReport
from orderorder.engine.scope import ScopeVerdict
from orderorder.engine.search import Authority, build_index
from orderorder.engine.verdict import CitationVerdict
from orderorder.engine.voice import VoiceVerdict
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

HOLDING = """1. Leave granted in the special leave petition filed by the appellant in this matter.

2. It was strenuously contended on behalf of the appellant that any misrepresentation whatsoever
vitiates consent in a commercial contract, however immaterial the misstatement may have been.

3. A misrepresentation of a material fact vitiates the consent of the contracting party only where
it induced the contract, and the burden of proving that inducement lies upon the party alleging it.

4. The doctrine of frustration has no application where the parties have expressly allocated the
risk of the supervening event between themselves in the contract that they made.

5. Nothing said above should be understood as expressing any view upon the counterclaim, which the
trial court will decide on its own merits in accordance with law.

6. In view of the above, the appeals are dismissed with no order as to costs whatsoever.
"""


def _add(session, key: str, title: str, text: str, *, year: int = 2019) -> Judgment:
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
    _add(session, "INSC:2019:1", "ALPHA versus BETA", HOLDING)
    session.commit()
    build_index(session)
    return session


CLAIM = "a misrepresentation vitiates consent only where it induced the contract"


def _authority(**kwargs) -> Authority:
    base = {
        "judgment_id": "j1",
        "canonical_key": "INSC:2019:1",
        "title": "ALPHA versus BETA",
        "citation": "(2019) 4 SCC 118",
        "court": "Supreme Court of India",
        "decided_on": "2019-06-01",
        "bench_strength": 2,
        "paragraph_label": "3",
        "paragraph_seq": 4,
        "body": "A misrepresentation vitiates consent only where it induced the contract.",
        "relevance": 10.0,
        "score": 10.1,
        "voice": VoiceVerdict(voice="court_majority", method="opinion"),
        "treatment": TreatmentReport(judgment_id="j1", status="good_law"),
    }
    base.update(kwargs)
    return Authority(**base)


def _verdict(**kwargs) -> CitationVerdict:
    base = {
        "citation_raw": "(2019) 4 SCC 118",
        "proposition": CLAIM,
        "existence": "found",
        "support": "full",
        "quote": "a misrepresentation vitiates consent only where it induced",
        "quote_verified": True,
    }
    base.update(kwargs)
    return CitationVerdict(**base)


# --- what the gate refuses -------------------------------------------------------------------------


def test_the_courts_own_words_supporting_the_claim_are_bound() -> None:
    status, reason = _gate(_authority(), _verdict())
    assert status == BOUND
    assert "good law" in reason


def test_counsels_submission_is_refused_however_well_it_matches() -> None:
    """An advocate states a rule more baldly than a court will, which is why it ranks well."""
    voice = VoiceVerdict(voice="counsel_argument", method="rule", cue="learned counsel")
    status, reason = _gate(_authority(voice=voice), _verdict())
    assert status == REFUSED
    assert "counsel_argument" in reason


def test_a_dissent_is_refused() -> None:
    voice = VoiceVerdict(voice="court_dissent", opinion_kind="dissenting", method="opinion")
    status, _reason = _gate(_authority(voice=voice), _verdict())
    assert status == REFUSED


def test_overruled_law_is_refused_however_well_it_supports_the_claim() -> None:
    overruled = TreatmentReport(
        judgment_id="j1", status="overruled", note="overruled by a Constitution Bench in 2020"
    )
    status, reason = _gate(_authority(treatment=overruled), _verdict())
    assert status == REFUSED
    assert "2020" in reason


def test_support_claimed_without_a_verified_quote_is_refused() -> None:
    """The verifier will not record support without one; the gate must not let it read as usable."""
    status, reason = _gate(_authority(), _verdict(support="full", quote_verified=False))
    assert status == REFUSED
    assert "quote" in reason


def test_a_narrower_holding_is_offered_with_the_narrowing() -> None:
    scope = ScopeVerdict(
        claim=CLAIM,
        support="partial",
        model_support="partial",
        gap="the court conditioned it on inducement",
        narrowed_proposition="a misrepresentation vitiates consent where it induced the contract",
    )
    status, reason = _gate(_authority(), _verdict(support="partial", scope=scope))
    assert status == NARROWED
    assert "inducement" in reason


def test_a_provider_outage_is_unchecked_and_never_a_refusal() -> None:
    """A failed HTTP request is not a finding that the judgment does not say this.

    Found by running the drafting demo with the local model proxy down: every candidate came back
    "the judgment does not state this", which is a verdict, stated on the strength of a connection
    error. The verifier already refuses to make that mistake; the gate has to refuse it too, and a
    refusal is the place it hides best, because refusing looks like the tool being careful.
    """
    scope = ScopeVerdict(
        claim=CLAIM,
        support="none",
        model_support="error",
        needs_review=True,
        review_reason="every configured model provider failed (OpenAIConnectionError)",
    )
    verdict = _verdict(support="not_assessed", quote_verified=False, scope=scope)
    verdict.ask_review(scope.review_reason)
    status, reason = _gate(_authority(), verdict)
    assert status == UNCHECKED
    assert "provider failed" in reason


def test_a_verdict_the_engine_flagged_is_never_bound() -> None:
    """The gate was the last place `needs_review` could be ignored, and it was ignoring it.

    Found by running the drafting demo against a live model: the verifier recorded that a person
    should look at a citation, and the gate bound it as settled authority anyway with a pinpoint that
    made it look checked. A flagged citation in somebody else's brief is one you can still catch. A
    flagged citation in your own draft has already been written in your name.
    """
    verdict = _verdict(support="full")
    verdict.ask_review("the model's own confidence was 0.00")
    status, reason = _gate(_authority(), verdict)
    assert status == UNCHECKED
    assert "confidence" in reason


def test_a_flagged_narrowing_is_not_offered_as_authority_either() -> None:
    scope = ScopeVerdict(
        claim=CLAIM,
        support="partial",
        model_support="partial",
        narrowed_proposition="a misrepresentation that induced the contract vitiates consent",
    )
    verdict = _verdict(support="partial", scope=scope)
    verdict.ask_review("the quote matched a paragraph other than the one named")
    status, _reason = _gate(_authority(), verdict)
    assert status == UNCHECKED


def test_an_unflagged_verdict_still_binds() -> None:
    """The rule must not swallow the case the gate exists to allow."""
    status, _reason = _gate(_authority(), _verdict(support="full"))
    assert status == BOUND


def test_with_no_model_nothing_can_be_bound() -> None:
    status, reason = _gate(_authority(), None)
    assert status == UNCHECKED
    assert "not checked" in reason


# --- end to end ------------------------------------------------------------------------------------


def test_without_a_model_the_line_is_offered_but_never_as_authority(corpus) -> None:
    binding = bind_proposition(corpus, CLAIM)
    assert binding.status == UNCHECKED
    assert not binding.is_usable
    assert binding.chosen is not None
    assert binding.chosen.authority.paragraph_label == "3"


def test_a_proposition_the_corpus_cannot_answer_is_refused_plainly(corpus) -> None:
    binding = bind_proposition(corpus, "a promissory estoppel cannot be invoked against a statute")
    assert binding.status == REFUSED
    assert not binding.chosen


def test_the_rendering_says_what_was_considered_and_what_was_wrong_with_it(corpus) -> None:
    """A refusal that names the near miss is the answer an advocate can act on."""
    binding = bind_proposition(corpus, CLAIM)
    text = "\n".join(render_binding(binding))
    assert CLAIM in text
    assert "para 3" in text
    assert binding.reason in text
