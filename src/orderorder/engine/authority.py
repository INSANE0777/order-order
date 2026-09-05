"""Bind a proposition to an authority, or refuse to.

`docs/PRD.md` B5 and B6, which are the substance of the drafting surface. B7 is formatting and B4 is
already `engine.search`; this is the part where the two directions meet. An advocate has a
proposition they intend to argue and no citation for it. The corpus is searched for one, each
candidate is put through the same verifier that checks a brief, and then a **gate** decides whether it
is fit to go into a draft.

The gate is the point. Retrieval will always return something — a corpus of nine thousand judgments
has words matching any proposition — and a drafting tool that binds the top result to the sentence is
a machine for producing exactly the citations this engine exists to catch. So the default is strict:

  * the passage must be the court's own words, not counsel's, not the court below, not a quotation;
  * it must be the majority, not a dissent;
  * the judgment must be good law, with nothing later overruling or doubting it;
  * the judgment must say the proposition, with a quote that verifies word for word.

Anything short of all four does not go in silently. Partial support is offered *with the narrowing*,
so the advocate argues the proposition the court actually stated rather than the one they wanted. A
passage nobody could check is offered as a line to read, labelled as unchecked, and never as
authority — which is the same three-state honesty the verdict board uses, in the direction where the
temptation to overclaim is strongest, because here the tool is writing rather than marking.

What comes back is therefore usually a refusal with reasons, and that is the useful answer: it names
the authority that came closest and says what is wrong with it, which is where the next hour of
research starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from orderorder.engine.locator import locate
from orderorder.engine.providers import StructuredModel
from orderorder.engine.scope import assess_scope
from orderorder.engine.search import DEFAULT_CANDIDATES, Authority, find_authorities
from orderorder.engine.verdict import CitationVerdict, build_verdict
from orderorder.ingest.store import load_paragraphs
from orderorder.resolver import Resolution

# What the gate can say. `bound` may be cited as it stands; `narrowed` may be cited for less than was
# asked; `unchecked` is a line to read and not authority; `refused` is a candidate with something
# wrong with it.
BOUND = "bound"
NARROWED = "narrowed"
UNCHECKED = "unchecked"
REFUSED = "refused"

# How many candidates are put through the verifier. Each is a model call, and by the fifth the
# retrieval score has usually fallen far enough that a hit would be a surprise.
DEFAULT_CHECKED = 4


@dataclass
class Considered:
    """One authority the gate looked at, and what it decided."""

    authority: Authority
    verdict: CitationVerdict | None
    status: str
    reason: str

    @property
    def pinpoint(self) -> str:
        return self.authority.pinpoint


@dataclass
class Binding:
    """A proposition and the authority, if any, that may be put behind it."""

    proposition: str
    status: str
    reason: str
    chosen: Considered | None = None
    considered: list[Considered] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """Fit to go into a draft, as it stands or narrowed."""
        return self.status in {BOUND, NARROWED}

    @property
    def quote(self) -> str | None:
        verdict = self.chosen.verdict if self.chosen else None
        return verdict.quote if verdict and verdict.quote_verified else None

    @property
    def narrowed_to(self) -> str | None:
        verdict = self.chosen.verdict if self.chosen else None
        if verdict and verdict.scope:
            return verdict.scope.narrowed_proposition
        return None


def _gate(authority: Authority, verdict: CitationVerdict | None) -> tuple[str, str]:
    """Whether this authority may go into a draft, and why not where it may not.

    Checked in the order an advocate would care about. A dissent is not authority however well it
    matches; overruled law is worse than no law; and a passage that says something narrower than the
    proposition is still worth having, provided the narrowing goes with it.
    """
    voice = authority.voice
    if voice is not None and not voice.is_the_court:
        return REFUSED, f"the passage is not the court's own words ({voice.voice})"
    if voice is not None and voice.is_dissent:
        return REFUSED, "the passage is from a dissenting opinion"
    if authority.treatment is not None and authority.treatment.is_doubtful:
        return REFUSED, authority.treatment.note or "later judgments have doubted this one"

    if verdict is None:
        return UNCHECKED, "no model was configured, so whether this paragraph supports the claim was not checked"
    if not verdict.quote_verified:
        if verdict.support in {"full", "partial"}:
            # The verifier already refuses to record support without a verified quote; saying so here
            # is what stops an advocate reading "partial" as "usable".
            return REFUSED, "the supporting quote could not be found in the judgment text"
        return REFUSED, verdict.scope.gap if verdict.scope and verdict.scope.gap else "the judgment does not state this"
    if verdict.support == "full":
        return BOUND, "the court states this, in its own words, and the judgment is good law"
    if verdict.support == "partial":
        gap = (verdict.scope.gap if verdict.scope else None) or "the court states it more narrowly"
        return NARROWED, gap
    return REFUSED, "the judgment does not state this"


def check_authority(
    session: Session, authority: Authority, proposition: str, model: StructuredModel | None
) -> CitationVerdict | None:
    """Put one retrieved authority through the verifier: does that paragraph really say this?"""
    if model is None:
        return None
    paragraphs = load_paragraphs(session, authority.judgment_id)
    label = authority.paragraph_label
    location = locate(paragraphs, proposition, claimed_pinpoint=label, top_k=6)
    return build_verdict(
        authority.citation or authority.canonical_key,
        proposition,
        Resolution(
            status="found",
            method="search",
            judgment_id=authority.judgment_id,
            canonical_key=authority.canonical_key,
            score=100.0,
        ),
        judgment_title=authority.title,
        pinpoint=location.pinpoint,
        scope=assess_scope(proposition, location.candidates, model),
        voice=authority.voice,
        treatment=authority.treatment,
        claimed_pinpoint=label,
    )


def bind_proposition(
    session: Session,
    proposition: str,
    model: StructuredModel | None = None,
    *,
    checked: int = DEFAULT_CHECKED,
    candidates: int = DEFAULT_CANDIDATES,
) -> Binding:
    """Find an authority for a proposition and decide whether it may be put behind it.

    Candidates are taken in the order the search ranked them and the first that passes the gate wins,
    rather than the best-scoring one being chosen and then excused. Everything looked at is kept, with
    the reason it was rejected: a refusal that names the near miss is the answer an advocate can act on.
    """
    found = find_authorities(session, proposition, top=checked, candidates=candidates)
    if not found:
        return Binding(proposition, REFUSED, "no paragraph in the corpus carries these words")

    looked_at: list[Considered] = []
    for authority in found:
        verdict = check_authority(session, authority, proposition, model)
        status, reason = _gate(authority, verdict)
        entry = Considered(authority, verdict, status, reason)
        looked_at.append(entry)
        if status in {BOUND, NARROWED}:
            return Binding(proposition, status, reason, chosen=entry, considered=looked_at)

    # Nothing passed. An unchecked candidate is still worth putting in front of a person, so long as
    # it is not called authority.
    unchecked = next((c for c in looked_at if c.status == UNCHECKED), None)
    if unchecked is not None:
        return Binding(
            proposition,
            UNCHECKED,
            unchecked.reason,
            chosen=unchecked,
            considered=looked_at,
        )
    return Binding(
        proposition,
        REFUSED,
        f"{len(looked_at)} authorities were considered and none passed",
        considered=looked_at,
    )


def render_binding(binding: Binding) -> list[str]:
    """One proposition and its authority, as lines."""
    mark = {BOUND: "BOUND", NARROWED: "NARROWED", UNCHECKED: "UNCHECKED", REFUSED: "NO AUTHORITY"}
    lines = [f"{mark[binding.status]:>12}  {binding.proposition.strip()}"]

    if binding.chosen is not None:
        lines.append(f"    {binding.chosen.pinpoint}")
        lines.append(f"    {binding.chosen.authority.title[:80]}")
        if binding.quote:
            lines.append(f'    verified: "{binding.quote.strip()}"')
        elif binding.chosen.authority.line:
            lines.append(f'    line:     "{binding.chosen.authority.line.strip()[:200]}"')
    if binding.status == NARROWED and binding.narrowed_to:
        lines.append(f"    argue instead: {binding.narrowed_to}")
    lines.append(f"    {binding.reason}")

    rejected = [c for c in binding.considered if c is not binding.chosen]
    if rejected:
        lines.append("    also considered:")
        lines.extend(f"      {c.pinpoint} - {c.reason}" for c in rejected)
    return lines
