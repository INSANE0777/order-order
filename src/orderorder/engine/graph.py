"""The verification engine as a LangGraph state graph.

Each stage from docs/ARCHITECTURE.md section 4.13 is a node; the state is the verdict in progress. The
graph is deliberately not an agent: the model is called inside two nodes and everything else is plain
Python, so the path a citation takes is fixed and inspectable.

Compiled with a checkpointer, a run survives a restart and every intermediate state can be read back,
which is what makes a verdict auditable rather than merely produced.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from orderorder.citations.grammar import Citation
from orderorder.db.models import Judgment
from orderorder.engine.citator import TreatmentReport, treatment_of
from orderorder.engine.facts import ApplicabilityVerdict, assess_applicability
from orderorder.engine.hierarchy import HierarchyCheck, check_hierarchy
from orderorder.engine.locator import Candidate, LocationResult, locate
from orderorder.engine.providers import StructuredModel
from orderorder.engine.scope import ScopeVerdict, assess_scope
from orderorder.engine.sentences import sentence_around
from orderorder.engine.truncation import Truncation, find_truncation
from orderorder.engine.verdict import CitationVerdict, build_verdict
from orderorder.engine.voice import VoiceVerdict, attribute_voice, relied_on
from orderorder.engine.weight import WeightVerdict, classify_weight, find_disposition
from orderorder.ingest.store import load_paragraphs
from orderorder.resolver import Resolution, resolve


class VerifyState(TypedDict, total=False):
    """The verdict in progress. Each node adds to it; nothing is removed."""

    citation: Citation
    proposition: str
    resolution: Resolution
    judgment_title: str | None
    paragraphs: list[Any]
    location: LocationResult
    candidates: list[Candidate]
    scope: ScopeVerdict | None
    voice: VoiceVerdict | None
    weight: WeightVerdict | None
    treatment: TreatmentReport | None
    hierarchy: HierarchyCheck | None
    applicability: ApplicabilityVerdict | None
    truncation: Truncation | None
    verdict: CitationVerdict


def build_verify_graph(
    session: Session,
    model: StructuredModel | None = None,
    *,
    top_k: int = 6,
    voice_model: StructuredModel | None = None,
    weight_model: StructuredModel | None = None,
    facts_model: StructuredModel | None = None,
    matter_facts: str = "",
):
    """Compile the per-citation graph against a database session and its models.

    The three models are separate because each is bound to a different output schema. Any of them may
    be None: the graph then runs that node's rules alone and says so, rather than skipping the node and
    leaving the question silently unanswered.
    """

    def resolve_node(state: VerifyState) -> dict:
        citation = state["citation"]
        resolution = resolve(session, citation)
        title = None
        hierarchy = None
        if resolution.judgment_id:
            judgment = session.get(Judgment, resolution.judgment_id)
            title = judgment.title if judgment else None
            if judgment is not None:
                hierarchy = check_hierarchy(
                    state["proposition"], judgment.court, judgment.bench_strength
                )
        return {"resolution": resolution, "judgment_title": title, "hierarchy": hierarchy}

    def load_node(state: VerifyState) -> dict:
        resolution = state["resolution"]
        if not resolution.judgment_id:
            return {"paragraphs": []}
        return {"paragraphs": load_paragraphs(session, resolution.judgment_id)}

    def treatment_node(state: VerifyState) -> dict:
        """Has a later judgment killed this authority?

        Asked of the judgment as a whole, not of the paragraph, and asked even when the citation has
        no text to read: whether a case is still good law is a fact about the case, and the answer is
        useful even when nothing else about the citation could be checked.
        """
        resolution = state["resolution"]
        if not resolution.judgment_id:
            return {"treatment": None}
        return {"treatment": treatment_of(session, resolution.judgment_id)}

    def locate_node(state: VerifyState) -> dict:
        citation = state["citation"]
        paragraphs = state.get("paragraphs") or []
        pinpoint = citation.pinpoint.label if citation.pinpoint else None
        location = locate(paragraphs, state["proposition"], claimed_pinpoint=pinpoint, top_k=top_k)
        # Whether the brief stopped a quotation before its qualification is a string comparison, so it
        # is settled here alongside the pinpoint rather than waited on from the model.
        return {
            "location": location,
            "candidates": location.candidates,
            "truncation": find_truncation(state["proposition"], paragraphs),
        }

    def scope_node(state: VerifyState) -> dict:
        # Called even with no candidates: assess_scope reports that as unassessed rather than
        # unsupported, which is the distinction the verdict depends on.
        return {"scope": assess_scope(state["proposition"], state.get("candidates") or [], model)}

    def attribute_node(state: VerifyState) -> dict:
        """Whose words are they, and did they carry the decision?

        Both questions are asked only about a paragraph the engine can name with confidence: one whose
        quote verified, or the one the brief itself pinpointed. Attributing a dissent to a paragraph
        that merely ranked highest would be a confident guess, which is the failure this engine exists
        to catch rather than commit.
        """
        candidates = state.get("candidates") or []
        scope = state.get("scope")
        matched = scope.matched_paragraph_label if scope and scope.quote_verified else None
        candidate = relied_on(candidates, matched)
        if candidate is None:
            return {"voice": None, "weight": None}

        quote_start = scope.char_start if scope and scope.quote_verified else None
        voice = attribute_voice(candidate, quote_start=quote_start, model=voice_model)
        weight = classify_weight(
            candidate,
            state["proposition"],
            voice=voice,
            disposition=find_disposition(state.get("paragraphs") or []),
            model=weight_model,
        )
        return {"voice": voice, "weight": weight}

    def applicability_node(state: VerifyState) -> dict:
        """Does the cited case govern the facts of this matter?

        Skipped entirely when the user has supplied no facts: there is nothing to compare against, and
        an engine that answered anyway would be answering a question nobody asked.
        """
        if not (matter_facts or "").strip():
            return {"applicability": None}
        return {
            "applicability": assess_applicability(
                state["proposition"], matter_facts, state.get("candidates") or [], facts_model
            )
        }

    def assemble_node(state: VerifyState) -> dict:
        citation = state["citation"]
        location = state.get("location")
        candidates = state.get("candidates") or []
        verdict = build_verdict(
            citation.raw,
            state["proposition"],
            state["resolution"],
            judgment_title=state.get("judgment_title"),
            pinpoint=location.pinpoint if location else None,
            scope=state.get("scope"),
            voice=state.get("voice"),
            weight=state.get("weight"),
            treatment=state.get("treatment"),
            hierarchy=state.get("hierarchy"),
            applicability=state.get("applicability"),
            truncation=state.get("truncation"),
            claimed_pinpoint=citation.pinpoint.label if citation.pinpoint else None,
            likely_quoted=any(c.likely_quoted for c in candidates[:3]),
            span=citation.span,
        )
        return {"verdict": verdict}

    def has_judgment(state: VerifyState) -> str:
        """A citation that resolves to nothing goes straight to the verdict: there is nothing to read."""
        return "load" if state["resolution"].judgment_id else "assemble"

    def has_text(state: VerifyState) -> str:
        return "locate" if state.get("paragraphs") else "assemble"

    graph = StateGraph(VerifyState)
    graph.add_node("resolve", resolve_node)
    graph.add_node("treatment", treatment_node)
    graph.add_node("load", load_node)
    graph.add_node("locate", locate_node)
    graph.add_node("scope", scope_node)
    graph.add_node("attribute", attribute_node)
    graph.add_node("applicability", applicability_node)
    graph.add_node("assemble", assemble_node)

    graph.set_entry_point("resolve")
    graph.add_conditional_edges(
        "resolve", has_judgment, {"load": "treatment", "assemble": "assemble"}
    )
    graph.add_edge("treatment", "load")
    graph.add_conditional_edges("load", has_text, {"locate": "locate", "assemble": "assemble"})
    graph.add_edge("locate", "scope")
    graph.add_edge("scope", "attribute")
    graph.add_edge("attribute", "applicability")
    graph.add_edge("applicability", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def verify_citation(
    session: Session,
    citation: Citation,
    proposition: str,
    model: StructuredModel | None = None,
    *,
    top_k: int = 6,
    voice_model: StructuredModel | None = None,
    weight_model: StructuredModel | None = None,
    facts_model: StructuredModel | None = None,
    matter_facts: str = "",
) -> CitationVerdict:
    """Run one citation through the engine."""
    compiled = build_verify_graph(
        session,
        model,
        top_k=top_k,
        voice_model=voice_model,
        weight_model=weight_model,
        facts_model=facts_model,
        matter_facts=matter_facts,
    )
    final = compiled.invoke({"citation": citation, "proposition": proposition})
    return final["verdict"]


def verify_text(
    session: Session,
    text: str,
    model: StructuredModel | None = None,
    *,
    top_k: int = 6,
    voice_model: StructuredModel | None = None,
    weight_model: StructuredModel | None = None,
    facts_model: StructuredModel | None = None,
    matter_facts: str = "",
    on_found=None,
    on_verdict=None,
) -> list[CitationVerdict]:
    """Find every citation in a passage and verify each one.

    The proposition attributed to a citation is the sentence containing it. That is a first
    approximation: a citation often supports the sentence before it, and resolving that properly is
    the span-tagging step the architecture assigns to the model.

    `on_found` is told how many citations there are before any of them is checked, and `on_verdict`
    is told about each one as it finishes. A brief of thirty citations takes minutes with a model
    configured, and a caller that can only wait for the list has nothing to show until the last one
    is done — including the phantom that was settled in milliseconds.
    """
    from orderorder.citations.grammar import extract_citations

    verdicts: list[CitationVerdict] = []
    compiled = build_verify_graph(
        session,
        model,
        top_k=top_k,
        voice_model=voice_model,
        weight_model=weight_model,
        facts_model=facts_model,
        matter_facts=matter_facts,
    )
    citations = extract_citations(text)
    if on_found is not None:
        on_found(len(citations))
    for citation in citations:
        proposition = sentence_around(text, citation.span[0])
        final = compiled.invoke({"citation": citation, "proposition": proposition})
        verdicts.append(final["verdict"])
        if on_verdict is not None:
            on_verdict(final["verdict"])
    return verdicts
