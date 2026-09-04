"""Resolve a citation found in a brief to a judgment in the knowledge base.

Order of attempts, stopping at the first confident match (ARCHITECTURE.md section 4.3):

  1. exact match of the normalised alias
  2. party-name match with rapidfuzz, filtered by year when the citation carries one
  3. (later) Indian Kanoon lookup for anything the local corpus does not hold

The resolver never asks a model whether a case exists. A well-formed citation that matches nothing is
`not_found`, which is what the phantom verdict is built on; a party-name match under a different
citation is `mis_cite`, and the correct citation is offered as the fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from rapidfuzz import fuzz, process, utils
from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.citations.grammar import Citation
from orderorder.db.models import CitationAlias, Judgment

EXACT = "exact"
PARTY_NAME = "party_name"
NOT_FOUND = "not_found"

PARTY_MATCH_THRESHOLD = 88.0
AMBIGUOUS_MARGIN = 4.0


@dataclass
class Candidate:
    judgment_id: str
    canonical_key: str
    title: str
    score: float
    via: str


@dataclass
class Resolution:
    status: str  # found | not_found | ambiguous
    method: str
    judgment_id: str | None = None
    canonical_key: str | None = None
    matched_alias: str | None = None
    score: float = 0.0
    candidates: list[Candidate] = field(default_factory=list)
    note: str | None = None

    @property
    def found(self) -> bool:
        return self.status == "found"


def resolve_exact(session: Session, normalized: str) -> Resolution:
    """Look the normalised alias up in the unique index. This is SQL, never vector search."""
    row = session.execute(
        select(CitationAlias, Judgment)
        .join(Judgment, CitationAlias.judgment_id == Judgment.id)
        .where(CitationAlias.normalized == normalized)
    ).first()
    if row is None:
        return Resolution(status=NOT_FOUND, method=EXACT)
    alias, judgment = row
    return Resolution(
        status="found",
        method=EXACT,
        judgment_id=judgment.id,
        canonical_key=judgment.canonical_key,
        matched_alias=alias.citation_string,
        score=100.0,
    )


def resolve_by_parties(
    session: Session, party_names: str, *, year: int | None = None, limit: int = 5
) -> Resolution:
    """Fuzzy-match "A v. B" against judgment titles, narrowed by year when the citation supplies one.

    The year filter spans the year before and after the citation year, because a case decided in
    December is routinely reported in the following year's volume.
    """
    query = select(Judgment.id, Judgment.canonical_key, Judgment.title)
    if year:
        query = query.where(
            Judgment.decided_on.is_not(None),
            Judgment.decided_on >= date(year - 1, 1, 1),
            Judgment.decided_on <= date(year + 1, 12, 31),
        )
    rows = session.execute(query).all()
    if not rows:
        return Resolution(status=NOT_FOUND, method=PARTY_NAME)

    titles = {r.id: (r.title or "") for r in rows}
    meta = {r.id: r for r in rows}
    # default_process lowercases and strips punctuation; without it "GURMIT" and "Gurmit" score 26 instead of 97.
    matches = process.extract(
        party_names,
        titles,
        scorer=fuzz.token_set_ratio,
        processor=utils.default_process,
        limit=limit,
        score_cutoff=PARTY_MATCH_THRESHOLD,
    )
    if not matches:
        return Resolution(status=NOT_FOUND, method=PARTY_NAME)

    candidates = [
        Candidate(
            judgment_id=key,
            canonical_key=meta[key].canonical_key,
            title=meta[key].title,
            score=float(score),
            via=PARTY_NAME,
        )
        for _, score, key in matches
    ]
    best = candidates[0]
    if len(candidates) > 1 and (best.score - candidates[1].score) < AMBIGUOUS_MARGIN:
        return Resolution(
            status="ambiguous",
            method=PARTY_NAME,
            score=best.score,
            candidates=candidates,
            note=f"{len(candidates)} titles within {AMBIGUOUS_MARGIN} points",
        )
    return Resolution(
        status="found",
        method=PARTY_NAME,
        judgment_id=best.judgment_id,
        canonical_key=best.canonical_key,
        score=best.score,
        candidates=candidates,
    )


def resolve(session: Session, citation: Citation) -> Resolution:
    """Full resolution for one parsed citation."""
    exact = resolve_exact(session, citation.normalized)
    if exact.found:
        return exact

    if citation.party_names:
        by_party = resolve_by_parties(session, citation.party_names, year=citation.year)
        if by_party.status in {"found", "ambiguous"}:
            if by_party.found:
                by_party.note = (
                    f"citation string {citation.raw!r} not in the corpus; matched on party names instead"
                )
            return by_party

    return Resolution(
        status=NOT_FOUND,
        method=EXACT,
        note=f"no judgment carries the alias {citation.normalized}",
    )
