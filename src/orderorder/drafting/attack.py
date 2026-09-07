"""What the other side will say about the draft this tool just wrote.

`docs/PRD.md` B8. `engine.memo` already does this for a brief somebody else wrote; the difference here
is that the draft has been through the gate, so every attack the gate catches is gone before this runs.
That makes the section look easy and it is the reason it is worth writing carefully: a self-attack
panel over a document that has already passed four checks will find nothing unless it is looking at
what the four checks do not cover, and a self-attack that finds nothing is worse than none at all,
because it reads as an assurance.

So the attacks here are precisely the ones the gate cannot make:

  * **Distinguished.** The gate refuses law that was overruled or doubted. It does not refuse law that
    a later court held inapplicable on its facts, because that is not a defect in the authority — it
    is the argument the other side will make about it, which is a different thing and belongs here.
  * **Contrary.** A judgment that states the opposite of the proposition itself. The gate checked the
    authority behind the point and nothing checked the point against the rest of the corpus, which is
    where an opponent starts. Found by `engine.contrary` with no model: a contradiction is the
    *nearest* text in the corpus to a proposition rather than the farthest, so the ordinary search
    reaches it, and the polarity of a clause is what separates it from a restatement. A lead, not a
    finding — a court can state a rule narrowly without denying a wider one.
  * **Outranked.** A judgment in the same retrieval field, with a larger bench or a later date, that
    the draft did not cite. This is a lead and is written as one: all that is known is that it matched
    the same words. It is still the first thing an opponent's researcher will find.
  * **Thin.** An authority no later judgment in the corpus has cited at all. Not a defect. Something an
    opponent will say out loud -- but only where being uncited is unusual, which in this corpus it is
    not, so the check measures the graph before it trusts it. See `MIN_CITED_SHARE`.
  * **Narrowed.** The court stated the point more narrowly than the advocate wanted, the draft says so,
    and the opponent will say it louder.
  * **Unsupported.** The propositions carrying no verified authority. These are already marked in the
    draft; they are repeated here because this is the section a person reads when they are deciding
    what to cut.

Everything here comes from the citation graph, the bench strengths, the dates, the verdicts already
computed, and — for the contrary attack — the full-text index and the grammar of a clause. No model is
called, so nothing in this section can be an invention, and every line of it can be traced to a row in
the database.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from orderorder.db.models import CitationEdge, Judgment
from orderorder.drafting.assemble import Draft, Point
from orderorder.engine.authority import NARROWED
from orderorder.engine.contrary import find_contrary
from orderorder.engine.search import Authority, find_authorities, index_exists

# What each attack is called, in the order an opponent would lead with it. A case held inapplicable on
# its facts is the strongest thing that can be said about an authority that is still good law; a
# proposition with nothing behind it is the strongest thing that can be said about the draft.
DISTINGUISHED = "distinguished"
UNSUPPORTED = "unsupported"
CONTRARY = "contrary"
OUTRANKED = "outranked"
NARROWED_ATTACK = "narrowed"
THIN = "thin"
ORDER = [UNSUPPORTED, DISTINGUISHED, CONTRARY, OUTRANKED, NARROWED_ATTACK, THIN]
# How many contrary passages to raise per proposition. Two, for the reason `_outranked` stops at two:
# one is a lead worth chasing and five is a research task, and a section a person skips is a section
# that takes the real attacks with it.
CONTRARY_LEADS = 2

# How wide a field to look across for a better authority than the one the draft cites. Past this the
# retrieval score has usually fallen far enough that a bench-strength comparison is comparing a
# holding with a passing mention.
FIELD = 8
# Below this share of the corpus ever being cited by anything else in it, "nothing has cited this
# authority" is the ordinary state of a judgment rather than a fact about the one in hand. Measured on
# the corpus as it stands: 8,716 edges over 9,429 judgments, and 79% of them have never been cited. At
# that density the observation fired on four authorities in five and told an advocate nothing, which
# is worse than not firing -- a section of noise is a section that gets skipped, taking the real
# attacks with it.
MIN_CITED_SHARE = 0.5
# What the gate never looks at, whatever the model says, because it has no way to. Said once, at the
# foot of the section, because a list of attacks that stops here reads as though this is all of them.
NOT_CHECKED = (
    "Whether any of these authorities governs the facts of this matter was not checked, and cannot be: "
    "the engine has the propositions and the corpus, not the record. The corpus was searched for a "
    "judgment stating the opposite of each proposition, and what that search returns is a passage a "
    "court wrote with the opposite sign -- not a holding that this submission is wrong, which only "
    "reading it can tell you. It searched 2013 onwards, so the judgment that says otherwise may not "
    "be held here at all."
)


@dataclass
class Attack:
    """One thing the other side will say, and what to do about it."""

    kind: str
    proposition: str
    citation: str | None
    says: str
    fix: str


def cited_share(session: Session) -> float:
    """What share of the corpus has ever been cited by something else in the corpus.

    The denominator for every claim this module makes about a citation graph. Cheap -- one count over
    a table with a few thousand rows -- and it decides whether "nothing has cited this" is a finding
    or a description of the corpus.
    """
    judgments = session.scalar(select(func.count()).select_from(Judgment)) or 0
    if not judgments:
        return 0.0
    cited = (
        session.scalar(
            select(func.count(distinct(CitationEdge.cited_id))).where(CitationEdge.cited_id.is_not(None))
        )
        or 0
    )
    return cited / judgments


def attack_draft(session: Session, draft: Draft, *, search_contrary: bool = True) -> list[Attack]:
    """Every attack the gate could not make, worst first.

    `search_contrary` is a flag rather than an assumption because it is the expensive one: a search
    over the whole corpus for each point, against a citation-graph lookup for everything else.
    """
    attacks: list[Attack] = []
    informative = cited_share(session) >= MIN_CITED_SHARE
    for point in draft.points:
        if not point.is_cited:
            attacks.append(_unsupported(point))
            continue
        attacks.extend(_distinguished(point))
        if search_contrary:
            attacks.extend(_contrary(session, point))
        attacks.extend(_outranked(session, point))
        if point.status == NARROWED:
            attacks.append(_narrowed(point))
        if informative:
            attacks.extend(_thin(point))
    return sorted(attacks, key=lambda a: ORDER.index(a.kind))


def _contrary(session: Session, point: Point) -> list[Attack]:
    """A judgment that says the other thing, which is what an opponent opens with.

    The gate checked the authority behind this proposition. Nothing checked the proposition itself
    against the rest of the corpus, and "there is a judgment the other way" is the first sentence of
    the reply. `engine.contrary` finds those without a model: a contradiction is the nearest text in
    the corpus to a proposition rather than the farthest, so the ordinary search reaches it and the
    polarity of a clause is what separates it from a restatement.

    Written as a lead, in the same voice as `_outranked`, because that is what it is. What has been
    established is that a court in its own voice wrote a sentence on this subject with the opposite
    sign -- not that it denies this submission rather than confining the rule to other facts. The
    authority the draft already cites is excluded, so a point cannot be attacked with itself.
    """
    authority = _authority_of(point)
    if authority is None or not index_exists(session):
        return []
    report = find_contrary(
        session,
        point.proposition,
        exclude=(authority.judgment_id,),
        top=CONTRARY_LEADS,
        # One search per point rather than three. The antonym expansion is worth its cost when a
        # lawyer asks the question directly; over every point of a draft it triples the wait for a
        # section that is already the slowest thing `orderorder draft` does.
        expand=False,
    )
    out = []
    for lead in report.leads:
        out.append(
            Attack(
                CONTRARY,
                point.argued,
                authority.pinpoint,
                f"{lead.authority.title[:60]} ({lead.pinpoint}) reads the other way: "
                f'"{lead.sentence[:200]}"',
                "Read it. It may be confined to its own facts, and if it is, say so before they do.",
            )
        )
    return out


def _unsupported(point: Point) -> Attack:
    return Attack(
        UNSUPPORTED,
        point.proposition.strip(),
        None,
        "My friend advances this without authority.",
        "Cite something, narrow it to what can be cited, or take it out.",
    )


def _distinguished(point: Point) -> list[Attack]:
    authority = _authority_of(point)
    treatment = authority.treatment if authority else None
    if authority is None or treatment is None:
        return []
    out = []
    for edge in treatment.edges:
        if edge.treatment != "distinguished":
            continue
        year = (edge.citing_date or "")[:4]
        out.append(
            Attack(
                DISTINGUISHED,
                point.argued,
                authority.pinpoint,
                f"That case was held inapplicable on its facts in {edge.citing_title[:60]} "
                f"({edge.citing_key}{', ' + year if year else ''}).",
                "Read what that court distinguished it on, and say why this matter is not that one.",
            )
        )
    return out


def _outranked(session: Session, point: Point) -> list[Attack]:
    """A larger or later bench in the same field that the draft does not cite.

    This is a lead and not a finding. All that is established is that another judgment matched the
    same words and was decided by more judges, or by the same number more recently. Whether it says
    anything useful is a person's job. It is here because it is the first thing an opponent's junior
    will turn up, and finding it after they do is the expensive way.
    """
    authority = _authority_of(point)
    if authority is None or not index_exists(session):
        # Without the full-text index there is no field to compare against. Every other attack here
        # reads the citation graph and still works, so this one steps aside rather than taking them
        # with it; the draft could not have been assembled without the index in any case.
        return []
    field = find_authorities(session, point.proposition, top=FIELD, check_treatment=False)
    out = []
    for other in field:
        if other.judgment_id == authority.judgment_id or not _outranks(other, authority):
            continue
        out.append(
            Attack(
                OUTRANKED,
                point.argued,
                authority.pinpoint,
                f"{other.title[:60]} ({other.pinpoint}) is on the same words and "
                f"{_why_it_outranks(other, authority)}.",
                "Read it. If it helps, cite it instead; if it does not, know why before they raise it.",
            )
        )
        # One is a lead worth chasing. Five is a research task, and listing them all turns a section
        # a person reads into a section a person skips.
        if len(out) == 2:
            break
    return out


def _outranks(other: Authority, cited: Authority) -> bool:
    bench, mine = other.bench_strength or 0, cited.bench_strength or 0
    if bench > mine:
        return True
    return bench == mine and bool(other.decided_on and cited.decided_on and other.decided_on > cited.decided_on)


def _why_it_outranks(other: Authority, cited: Authority) -> str:
    bench, mine = other.bench_strength or 0, cited.bench_strength or 0
    if bench > mine:
        return f"was decided by {bench} judges against {mine or 'an unrecorded number'}"
    return f"is later ({(other.decided_on or '')[:4]} against {(cited.decided_on or '')[:4]})"


def _narrowed(point: Point) -> Attack:
    return Attack(
        NARROWED_ATTACK,
        point.argued,
        point.citation,
        "The paragraph my friend relies on states the point more narrowly than the submission does.",
        f"The draft already argues the narrower form. The wider one - {point.proposition.strip()} - "
        "needs its own authority or should not be put.",
    )


def _thin(point: Point) -> list[Attack]:
    authority = _authority_of(point)
    treatment = authority.treatment if authority else None
    if authority is None or treatment is None or treatment.citing_count:
        return []
    return [
        Attack(
            THIN,
            point.argued,
            authority.pinpoint,
            "No later judgment in the corpus has cited that case at all.",
            "It may still be right. Find a judgment that has followed it, or say why none needed to.",
        )
    ]


def _authority_of(point: Point) -> Authority | None:
    return point.binding.chosen.authority if point.binding.chosen else None
