"""The verification engine as a LangGraph state graph.

Each stage from docs/ARCHITECTURE.md section 4.13 is a node; the state is the verdict in progress. The
graph is deliberately not an agent: the model is called inside two nodes and everything else is plain
Python, so the path a citation takes is fixed and inspectable.

Compiled with a checkpointer, a run survives a restart and every intermediate state can be read back,
which is what makes a verdict auditable rather than merely produced.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from orderorder.citations.grammar import Citation
from orderorder.db.models import Judgment
from orderorder.engine.locator import Candidate, LocationResult, locate
from orderorder.engine.providers import StructuredModel
from orderorder.engine.scope import ScopeVerdict, assess_scope
from orderorder.engine.verdict import CitationVerdict, build_verdict
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
    verdict: CitationVerdict


def build_verify_graph(session: Session, model: StructuredModel | None = None, *, top_k: int = 6):
    """Compile the per-citation graph against a database session and an optional model."""

    def resolve_node(state: VerifyState) -> dict:
        citation = state["citation"]
        resolution = resolve(session, citation)
        title = None
        if resolution.judgment_id:
            judgment = session.get(Judgment, resolution.judgment_id)
            title = judgment.title if judgment else None
        return {"resolution": resolution, "judgment_title": title}

    def load_node(state: VerifyState) -> dict:
        resolution = state["resolution"]
        if not resolution.judgment_id:
            return {"paragraphs": []}
        return {"paragraphs": load_paragraphs(session, resolution.judgment_id)}

    def locate_node(state: VerifyState) -> dict:
        citation = state["citation"]
        paragraphs = state.get("paragraphs") or []
        pinpoint = citation.pinpoint.label if citation.pinpoint else None
        location = locate(paragraphs, state["proposition"], claimed_pinpoint=pinpoint, top_k=top_k)
        return {"location": location, "candidates": location.candidates}

    def scope_node(state: VerifyState) -> dict:
        # Called even with no candidates: assess_scope reports that as unassessed rather than
        # unsupported, which is the distinction the verdict depends on.
        return {"scope": assess_scope(state["proposition"], state.get("candidates") or [], model)}

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
            claimed_pinpoint=citation.pinpoint.label if citation.pinpoint else None,
            likely_quoted=any(c.likely_quoted for c in candidates[:3]),
        )
        return {"verdict": verdict}

    def has_judgment(state: VerifyState) -> str:
        """A citation that resolves to nothing goes straight to the verdict: there is nothing to read."""
        return "load" if state["resolution"].judgment_id else "assemble"

    def has_text(state: VerifyState) -> str:
        return "locate" if state.get("paragraphs") else "assemble"

    graph = StateGraph(VerifyState)
    graph.add_node("resolve", resolve_node)
    graph.add_node("load", load_node)
    graph.add_node("locate", locate_node)
    graph.add_node("scope", scope_node)
    graph.add_node("assemble", assemble_node)

    graph.set_entry_point("resolve")
    graph.add_conditional_edges("resolve", has_judgment, {"load": "load", "assemble": "assemble"})
    graph.add_conditional_edges("load", has_text, {"locate": "locate", "assemble": "assemble"})
    graph.add_edge("locate", "scope")
    graph.add_edge("scope", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def verify_citation(
    session: Session,
    citation: Citation,
    proposition: str,
    model: StructuredModel | None = None,
    *,
    top_k: int = 6,
) -> CitationVerdict:
    """Run one citation through the engine."""
    compiled = build_verify_graph(session, model, top_k=top_k)
    final = compiled.invoke({"citation": citation, "proposition": proposition})
    return final["verdict"]


def verify_text(
    session: Session, text: str, model: StructuredModel | None = None, *, top_k: int = 6
) -> list[CitationVerdict]:
    """Find every citation in a passage and verify each one.

    The proposition attributed to a citation is the sentence containing it. That is a first
    approximation: a citation often supports the sentence before it, and resolving that properly is
    the span-tagging step the architecture assigns to the model.
    """
    from orderorder.citations.grammar import extract_citations

    verdicts: list[CitationVerdict] = []
    compiled = build_verify_graph(session, model, top_k=top_k)
    for citation in extract_citations(text):
        proposition = _sentence_around(text, citation.span[0])
        final = compiled.invoke({"citation": citation, "proposition": proposition})
        verdicts.append(final["verdict"])
    return verdicts


# A sentence ends at a full stop that follows a lower-case letter or digit and precedes a capital.
# Requiring the lower-case or digit is what stops "[2019] 9 S.C.R. 593" and "No. 5522 of 2019" from
# being split mid-citation, which would hand the scope check half a proposition.
_SENTENCE_BREAK = re.compile(r"(?<=[a-z0-9\)\"'’”])\.\s+(?=[A-Z\"'“‘])|\n\s*\n")


def _sentence_around(text: str, position: int) -> str:
    """The sentence containing a character position, with the citation itself left in place."""
    breaks = [m.end() for m in _SENTENCE_BREAK.finditer(text)]
    start = max((b for b in breaks if b <= position), default=0)
    end = min((b for b in breaks if b > position), default=len(text))
    return text[start:end].strip()
