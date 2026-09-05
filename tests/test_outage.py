"""What the engine says when the model cannot be reached at all.

This file exists because of a bug found by running the drafting demo on a night when the local model
proxy happened to be down. Every candidate came back "the judgment does not state this" — a verdict
about Indian law, stated on the strength of a connection error, on every proposition in the plan. The
gate had fallen through to a refusal, and a refusal is where that mistake hides best, because refusing
looks like the tool being careful.

The rule, everywhere: **a check that could not run is reported as not run.** Not as a finding, not as
a refusal, not as a clean pass. An outage costs the engine its answer to a question; it must not be
allowed to invent one, and it must not take the eight detectors that need no model down with it.

So every model call site gets a provider that raises, and the whole engine is run end to end with
one. What is asserted is the same thing each time: the state comes back "not assessed", the reason
names the outage, and no finding was recorded against the citation.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, Judgment
from orderorder.engine.authority import UNCHECKED, _gate
from orderorder.engine.facts import assess_applicability
from orderorder.engine.graph import verify_text
from orderorder.engine.locator import Candidate
from orderorder.engine.scope import assess_scope, decompose_claim
from orderorder.engine.search import Authority, build_index
from orderorder.engine.verdict import build_verdict
from orderorder.engine.weight import classify_weight
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted
from orderorder.resolver import Resolution

CLAIM = "A misrepresentation vitiates consent only where it induced the contract"

JUDGMENT = """1. Leave granted in the special leave petition filed by the appellant in this matter.

2. A misrepresentation of a material fact vitiates the consent of the contracting party only where
it induced the contract, and the burden of proving that inducement lies upon the party alleging it.

3. In view of the above, the appeals are dismissed with no order as to costs whatsoever.
"""

BRIEF = "1. A misrepresentation vitiates consent only where it induced it: (2019) 4 SCC 118, para 2.\n"


class OutOfReach:
    """Every provider failed. This is what LangChain hands back after the last fallback."""

    class ConnectionError(Exception):  # noqa: A001 - named for what the traceback will say
        pass

    def invoke(self, _prompt):
        raise OutOfReach.ConnectionError("all providers failed")


@pytest.fixture
def model() -> OutOfReach:
    return OutOfReach()


@pytest.fixture
def candidates() -> list[Candidate]:
    return [
        Candidate(
            seq=2,
            printed_label="2",
            score=10.0,
            matched_terms=["misrepresentation", "consent"],
            body="A misrepresentation of a material fact vitiates the consent of the contracting "
            "party only where it induced the contract.",
        )
    ]


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
        ExtractedJudgment(source_path="x", page_count=2, headnote="", judgment=JUDGMENT),
    )
    session.commit()
    build_index(session)
    return session


# --- one detector at a time -------------------------------------------------------------------------


def test_extent_of_support_is_not_assessed_rather_than_denied(model, candidates) -> None:
    verdict = assess_scope(CLAIM, candidates, model)
    assert verdict.model_support == "error"
    assert verdict.needs_review
    assert "ConnectionError" in (verdict.review_reason or "")


def test_ratio_and_obiter_are_not_told_apart_rather_than_guessed(model, candidates) -> None:
    verdict = classify_weight(candidates[0], CLAIM, model=model)
    assert verdict.label == "unclear"
    assert verdict.method == "not_assessed"
    assert "ConnectionError" in (verdict.reason or "")


def test_applicability_is_not_assessed_rather_than_denied(model, candidates) -> None:
    verdict = assess_applicability(CLAIM, "the parties here are strangers", candidates, model)
    assert verdict.status == "not_assessed"
    assert verdict.needs_review


def test_decomposition_falls_back_to_the_whole_proposition(model) -> None:
    """Nothing calls this yet. The guard is here so nobody learns the rule from a traceback."""
    claims = decompose_claim(CLAIM, model)
    assert [c.text for c in claims] == [CLAIM]


# --- the verdict ------------------------------------------------------------------------------------


def test_an_outage_is_never_a_finding(model, candidates) -> None:
    """`support: none` and `could not ask` are different answers and the verdict must not merge them."""
    verdict = build_verdict(
        "(2019) 4 SCC 118",
        CLAIM,
        Resolution(status="found", method="alias", judgment_id="j1", canonical_key="INSC:2019:1", score=100.0),
        scope=assess_scope(CLAIM, candidates, model),
    )
    assert verdict.support == "not_assessed"
    assert verdict.findings == []
    assert verdict.grade in {"A", "B"}
    assert verdict.needs_review


def test_the_drafting_gate_offers_the_line_rather_than_refusing_it(model, candidates) -> None:
    """The bug this file was written for."""
    authority = Authority(
        judgment_id="j1",
        canonical_key="INSC:2019:1",
        title="ALPHA versus BETA",
        citation="(2019) 4 SCC 118",
        court="Supreme Court of India",
        decided_on="2019-06-01",
        bench_strength=2,
        paragraph_label="2",
        paragraph_seq=2,
        body=candidates[0].body,
        relevance=10.0,
        score=10.1,
    )
    verdict = build_verdict(
        "(2019) 4 SCC 118",
        CLAIM,
        Resolution(status="found", method="search", judgment_id="j1", canonical_key="INSC:2019:1", score=100.0),
        scope=assess_scope(CLAIM, candidates, model),
    )
    status, reason = _gate(authority, verdict)
    assert status == UNCHECKED
    assert "provider failed" in reason


# --- the whole engine -------------------------------------------------------------------------------


def test_a_brief_still_comes_back_with_everything_that_needed_no_model(corpus, model) -> None:
    """An outage costs the engine one of twelve checks. It must not cost it the other eight."""
    verdicts = verify_text(
        corpus,
        BRIEF,
        model,
        voice_model=model,
        weight_model=model,
        facts_model=model,
        matter_facts="the parties here are strangers",
    )
    assert len(verdicts) == 1
    verdict = verdicts[0]
    # The checks that need no model still ran: the case was found and the pinpoint located.
    assert verdict.existence == "found"
    assert verdict.canonical_key == "INSC:2019:1"
    # And the one that needed a model is reported as not run, not as a failure of the citation.
    assert verdict.support == "not_assessed"
    assert verdict.grade != "F"
    assert verdict.needs_review
