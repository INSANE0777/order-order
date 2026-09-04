"""Is this authority still good law?

Failure mode 10, and the one that most embarrasses an advocate in open court: the case is real, the
paragraph exists, it says exactly what the brief claims — and a later bench overruled it. Nothing in
the judgment itself records that. It can only be known by reading every judgment that came after and
seeing what they did with it.

That is what a citator is, and building one from the corpus means two passes.

**Edges.** Every citation in every paragraph of every judgment is extracted by the same grammar the
brief side uses, and resolved against the alias index. A resolved citation is an edge: this judgment
cited that one, at this paragraph. A citation inside a block quotation gives no negative treatment,
because a court quoting an overruling is reporting one rather than performing it. Resolution here is exact-alias only and runs off a dictionary held
in memory, because four hundred thousand paragraphs cannot each afford a fuzzy party-name search.

**Treatment.** What the citing court *did* with the case it cited — followed it, distinguished it,
doubted it, overruled it — is read from the words around the citation. The cues are the ones courts
actually use, and only the words near the citation count, because a paragraph routinely cites four
cases and treats them differently.

Direction is the trap, and getting it wrong inverts the answer. Both of these appeared in the first
full run, and both were recorded as the cited case having been killed:

    "A three-Judge Bench of this Court in Mayavati Trading ... reported in (2019) 8 SCC 714
     overruled the decision in Antique Art (supra)"
    "The said judgement was reversed by this Court in the Judgment reported in (2020) 10 SCC 264."

In each, the cited case is the court that *did* the overruling. So a cue counts only when the citation
is its object: the cue follows the citation in the passive ("... is hereby overruled"), or precedes it
and takes what follows ("we overrule ..."), and never when the words in between mark the citation as
the actor.

One rule matters more than the cues, and it is arithmetic rather than language: **a bench cannot
overrule one at least as large as itself.** Two judges saying an earlier three-judge decision "does
not lay down the correct law" have doubted it and, at most, referred it onward; they have not
overruled it, and reporting that they did would be a worse error than missing it. So a claimed
overruling by a bench no larger than the one it overrules is recorded as `doubted`, with the reason
attached.

What this cannot see is a judgment the corpus does not hold. The report therefore says how much of the
corpus it searched, because "no negative treatment found" from nine thousand judgments means something
different from the same words over the full seventy-five years.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from orderorder.citations.grammar import extract_citations
from orderorder.db.models import CitationAlias, CitationEdge, Judgment, JudgmentTextVersion, Paragraph
from orderorder.engine.sentences import inside_quotation

# Treatment labels, from ARCHITECTURE.md section 4.8. Order matters: the first cue to match wins, so
# the most specific and most serious come first.
TREATMENT_CUES: list[tuple[str, re.Pattern[str]]] = [
    (
        "overruled",
        re.compile(
            r"""(?ix)
            (?: (?:is|are|stands?|hereby)\s+(?:hereby\s+)?overruled
              | we\s+(?:hereby\s+)?overrule
              | (?:is|are)\s+no\s+longer\s+good\s+law
              | (?:does|do)\s+not\s+lay\s+down\s+the\s+correct\s+(?:law|position)
              | (?:is|are)\s+not\s+good\s+law
              | overrule[ds]?\s+the\s+(?:decision|judgment|view)
            )
            """
        ),
    ),
    (
        "partly_overruled",
        re.compile(
            r"(?ix)(?:partly\s+overruled|overruled\s+in\s+part|to\s+th(?:at|e)\s+extent[^.]{0,40}overruled)"
        ),
    ),
    (
        "referred_to_larger_bench",
        re.compile(
            r"""(?ix)
            (?: referred?\s+to\s+a\s+(?:larger|bigger)\s+Bench
              | place[d]?\s+before\s+(?:the\s+)?(?:Hon(?:'|’)?ble\s+)?(?:the\s+)?Chief\s+Justice
              | requires?\s+(?:re-?consideration|to\s+be\s+reconsidered)
              | refer\s+(?:the\s+)?(?:matter|question|issue)\s+to\s+a\s+larger\s+Bench
            )
            """
        ),
    ),
    (
        "doubted",
        re.compile(
            r"""(?ix)
            (?: we\s+(?:respectfully\s+)?(?:doubt|are\s+unable\s+to\s+(?:agree|subscribe))
              | (?:with\s+respect|respectfully)\s*,?\s*we\s+(?:differ|disagree)
              | (?:we\s+are\s+not\s+in\s+agreement\s+with)
              | (?:cannot\s+be\s+said\s+to\s+lay\s+down)
              | (?:has\s+been\s+doubted)
            )
            """
        ),
    ),
    (
        "reversed",
        re.compile(r"(?ix)(?:(?:is|was|stands?)\s+reversed|we\s+reverse\s+the\s+(?:decision|judgment))"),
    ),
    (
        "distinguished",
        re.compile(
            r"""(?ix)
            (?: (?:is|are)\s+(?:clearly\s+)?distinguishable
              | (?:has|have)\s+no\s+application\s+to\s+the\s+facts
              | (?:is|are)\s+distinguished
              | turn(?:s|ed)?\s+on\s+(?:its|their)\s+own\s+facts
              | (?:does|do)\s+not\s+(?:apply|assist)\s+(?:to|the)
            )
            """
        ),
    ),
    (
        "affirmed",
        re.compile(r"(?ix)(?:(?:is|was|stands?)\s+affirmed|we\s+affirm\s+the\s+(?:decision|judgment|view))"),
    ),
    (
        "followed",
        re.compile(
            r"""(?ix)
            (?: (?:we|this\s+Court)\s+(?:respectfully\s+)?(?:follow|are\s+bound\s+by)
              | (?:is|are)\s+(?:squarely\s+)?(?:covered|governed)\s+by
              | following\s+the\s+(?:decision|judgment|ratio)
              | (?:in\s+line|accord)\s+with\s+the\s+(?:decision|ratio)
            )
            """
        ),
    ),
    (
        "relied_on",
        re.compile(
            r"""(?ix)
            (?: (?:relied|reliance)\s+(?:(?:was|is|has\s+been)\s+)?(?:placed\s+)?(?:up)?on
              | (?:we\s+may\s+)?(?:usefully\s+)?refer\s+to\s+the\s+(?:decision|judgment)
              | (?:as\s+)?(?:held|observed)\s+by\s+this\s+Court\s+in
            )
            """
        ),
    ),
]

# How far from the citation a cue may sit and still be about it. A sentence in a judgment runs long
# and cites several cases; a cue at the other end of it is about one of the others.
CUE_WINDOW = 160

# The citation performs the action rather than suffering it. "was reversed by this Court in <cite>",
# "overruled the decision in <cite>" — everything here names the citation as the overruling court, so
# no negative treatment attaches to it.
ACTOR_BEFORE = re.compile(
    r"""(?ix)
    (?: (?:overruled|reversed|affirmed|approved|upheld|doubted|distinguished)
        \s+ (?:by\s+[^.]{0,40}?\s+)? in \s+ [^.]{0,60}? $
      | (?:as\s+)?(?:held|observed|laid\s+down|decided)\s+(?:by\s+[^.]{0,30}?\s+)?in\s+[^.]{0,60}?$
    )
    """
)
# The citation is the subject of what follows: "<cite> overruled the decision in ...".
ACTOR_AFTER = re.compile(
    r"""(?ix)
    ^[\s,)\]"'-]{0,12}
    (?: overrul(?:ed|ing)\s+the\s+(?:decision|judgment|view|law)
      | (?:reversed|affirmed|upheld|approved)\s+the\s+(?:decision|judgment|view|order)
      | held\s+that
      | laid\s+down
    )
    """
)

# Treatment that puts an authority in doubt. Anything else leaves it standing.
NEGATIVE = {"overruled", "partly_overruled", "reversed", "doubted", "referred_to_larger_bench"}
# Treatment that only a larger bench may give. Article 141 and the practice under it: a bench cannot
# overrule one at least as large as itself.
LARGER_BENCH_ONLY = {"overruled", "partly_overruled"}
DEFAULT_TREATMENT = "referred"

GOOD_LAW = "good_law"
UNKNOWN = "unknown"


@dataclass
class TreatmentEdge:
    """One later judgment's treatment of an earlier one."""

    citing_key: str
    citing_title: str
    citing_date: str | None
    citing_bench: int | None
    treatment: str
    paragraph_label: str | None
    sentence: str | None = None
    downgraded_from: str | None = None

    @property
    def is_negative(self) -> bool:
        return self.treatment in NEGATIVE


@dataclass
class TreatmentReport:
    """What the corpus knows about whether a judgment is still good law."""

    judgment_id: str
    status: str  # good_law | overruled | partly_overruled | reversed | doubted | referred_to_larger_bench | unknown
    edges: list[TreatmentEdge] = field(default_factory=list)
    citing_count: int = 0
    corpus_size: int = 0
    note: str | None = None

    @property
    def negative(self) -> list[TreatmentEdge]:
        return [e for e in self.edges if e.is_negative]

    @property
    def is_doubtful(self) -> bool:
        return self.status in NEGATIVE

    @property
    def worst(self) -> TreatmentEdge | None:
        for label in ("overruled", "reversed", "partly_overruled", "referred_to_larger_bench", "doubted"):
            for edge in self.edges:
                if edge.treatment == label:
                    return edge
        return None


def classify_treatment(sentence: str, span: tuple[int, int] | None = None) -> str:
    """What the citing court did with the cited case.

    **Word order decides direction, and getting it wrong inverts the answer.** Two sentences from the
    corpus, both containing "overruled" or "reversed" a few words from a citation:

        "A three-Judge Bench of this Court in Mayavati Trading ... reported in (2019) 8 SCC 714
         overruled the decision in Antique Art (supra)"
        "The said judgement was reversed by this Court in the Judgment reported in (2020) 10 SCC 264."

    In both, the cited case is the court that *did* the overruling. Reading the cue as treatment *of*
    that case would report a live authority as dead, which is the worst thing a citator can say.

    So a cue counts only when the citation is its object: either the cue follows the citation in the
    passive ("... is hereby overruled"), or it precedes it and takes what follows ("we overrule ..."),
    and never when the words in between mark the citation as the actor ("overruled ... in <citation>").
    Without a span there is no direction to read, so the sentence is searched as a whole and the
    caller gets the older, looser behaviour.
    """
    if span is None:
        for label, pattern in TREATMENT_CUES:
            if pattern.search(sentence):
                return label
        return DEFAULT_TREATMENT

    start, end = span
    before = sentence[max(0, start - CUE_WINDOW) : start]
    after = sentence[end : end + CUE_WINDOW]

    # "reversed by this Court in ...", "overruled the decision in ..." — what follows performed the
    # action rather than suffering it.
    if ACTOR_BEFORE.search(before):
        return DEFAULT_TREATMENT

    for label, pattern in TREATMENT_CUES:
        # The citation is the actor: "(2019) 8 SCC 714 overruled the decision in ..."
        if label in NEGATIVE and ACTOR_AFTER.match(after):
            continue
        if pattern.search(after) or pattern.search(before):
            return label
    return DEFAULT_TREATMENT


def apply_bench_rule(
    treatment: str, citing_bench: int | None, cited_bench: int | None
) -> tuple[str, str | None]:
    """A bench cannot overrule one at least as large as itself.

    Returns the treatment to record and, when it was changed, the treatment claimed by the words. The
    downgrade is to `doubted` rather than to nothing: the later court plainly disagreed, and a reader
    needs to know that even though the earlier decision still binds.
    """
    if treatment not in LARGER_BENCH_ONLY:
        return treatment, None
    if not citing_bench or not cited_bench:
        return treatment, None
    if citing_bench > cited_bench:
        return treatment, None
    return "doubted", treatment


def alias_map(session: Session) -> dict[str, str]:
    """Every normalised citation alias to its judgment id, held in memory.

    Four hundred thousand paragraphs cannot each afford a database round trip, let alone the fuzzy
    party-name search the brief side can. Exact alias matching only: an edge asserted on a fuzzy name
    match would put words in a court's mouth about a case it may never have cited.
    """
    rows = session.execute(select(CitationAlias.normalized, CitationAlias.judgment_id)).all()
    return {normalized: judgment_id for normalized, judgment_id in rows}


def edges_in_judgment(
    judgment: Judgment, paragraphs: list[Paragraph], aliases: dict[str, str]
) -> list[CitationEdge]:
    """Every citation in one judgment that resolves to another judgment the corpus holds."""
    found: list[CitationEdge] = []
    seen: set[tuple[str, str]] = set()
    for paragraph in paragraphs:
        for citation in extract_citations(paragraph.body):
            cited_id = aliases.get(citation.normalized)
            if cited_id is None or cited_id == judgment.id:
                continue  # not in the corpus, or the judgment citing itself
            # The span is given relative to the paragraph, and so is the citation, so the cue window
            # is read around the citation where it sits rather than around the sentence as a whole.
            treatment = classify_treatment(paragraph.body, citation.span)

            # A judgment quoting "the decision in X is hereby overruled" is reporting an overruling,
            # not performing one. Recording it as this court's own would credit a two-judge bench with
            # a Constitution Bench's work, and the bench rule would then downgrade a real overruling
            # to doubt. The overruling itself is not lost: it is on the record in the judgment that
            # actually gave it, which is where this reads it from.
            if treatment in NEGATIVE and inside_quotation(paragraph.body, citation.span[0]):
                treatment = DEFAULT_TREATMENT
            key = (cited_id, treatment)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                CitationEdge(
                    citing_id=judgment.id,
                    cited_id=cited_id,
                    cited_alias=citation.raw,
                    treatment=treatment,
                    paragraph_id=paragraph.id,
                    source="extraction",
                )
            )
    return found


@dataclass
class CitatorStats:
    judgments_read: int = 0
    edges: int = 0
    treatments: dict[str, int] = field(default_factory=dict)

    def record(self, edges: list[CitationEdge]) -> None:
        self.judgments_read += 1
        self.edges += len(edges)
        for edge in edges:
            label = edge.treatment or DEFAULT_TREATMENT
            self.treatments[label] = self.treatments.get(label, 0) + 1


def build_citator(
    session: Session,
    *,
    limit: int | None = None,
    rebuild: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> CitatorStats:
    """Extract citation edges from every judgment whose text the corpus holds."""
    if rebuild:
        session.execute(delete(CitationEdge).where(CitationEdge.source == "extraction"))
        session.commit()

    aliases = alias_map(session)
    stats = CitatorStats()
    judgments = _judgments_with_text(session, limit=limit, skip_done=not rebuild)
    total = len(judgments)

    for done, judgment in enumerate(judgments, start=1):
        paragraphs = _paragraphs_of(session, judgment.id)
        edges = edges_in_judgment(judgment, paragraphs, aliases)
        for edge in edges:
            session.add(edge)
        stats.record(edges)
        if done % 200 == 0 or done == total:
            session.commit()
        if on_progress is not None:
            on_progress(done, total)
    session.commit()
    return stats


def _judgments_with_text(session: Session, *, limit: int | None, skip_done: bool) -> list[Judgment]:
    query = select(Judgment).join(JudgmentTextVersion, JudgmentTextVersion.judgment_id == Judgment.id)
    if skip_done:
        done = select(CitationEdge.citing_id).where(CitationEdge.source == "extraction")
        query = query.where(Judgment.id.not_in(done))
    query = query.order_by(Judgment.decided_on.desc())
    rows = list(session.scalars(query).all())
    return rows[:limit] if limit else rows


def _paragraphs_of(session: Session, judgment_id: str) -> list[Paragraph]:
    version = session.scalars(
        select(JudgmentTextVersion)
        .where(JudgmentTextVersion.judgment_id == judgment_id)
        .order_by(JudgmentTextVersion.preferred.desc())
    ).first()
    if version is None:
        return []
    return list(
        session.scalars(
            select(Paragraph).where(Paragraph.text_version_id == version.id).order_by(Paragraph.seq)
        ).all()
    )


def corpus_size(session: Session) -> int:
    """How many judgments the corpus holds text for, counted once per session.

    Every treatment report states this, and a brief has many citations; counting the table afresh for
    each of them is a table scan to answer a question whose answer cannot change during the run.
    """
    cached = getattr(session, "_orderorder_corpus_size", None)
    if cached is None:
        cached = session.scalar(select(func.count()).select_from(JudgmentTextVersion)) or 0
        session._orderorder_corpus_size = cached
    return cached


def treatment_of(session: Session, judgment_id: str) -> TreatmentReport:
    """What every later judgment in the corpus did with this one."""
    held = corpus_size(session)
    cited = session.get(Judgment, judgment_id)
    rows = session.execute(
        select(CitationEdge, Judgment, Paragraph)
        .join(Judgment, CitationEdge.citing_id == Judgment.id)
        .outerjoin(Paragraph, CitationEdge.paragraph_id == Paragraph.id)
        .where(CitationEdge.cited_id == judgment_id)
    ).all()

    edges: list[TreatmentEdge] = []
    for edge, citing, paragraph in rows:
        treatment, claimed = apply_bench_rule(
            edge.treatment or DEFAULT_TREATMENT,
            citing.bench_strength,
            cited.bench_strength if cited else None,
        )
        edges.append(
            TreatmentEdge(
                citing_key=citing.canonical_key,
                citing_title=citing.title,
                citing_date=citing.decided_on.isoformat() if citing.decided_on else None,
                citing_bench=citing.bench_strength,
                treatment=treatment,
                paragraph_label=paragraph.printed_label if paragraph else None,
                downgraded_from=claimed,
            )
        )

    report = TreatmentReport(
        judgment_id=judgment_id, status=GOOD_LAW, edges=edges, citing_count=len(edges), corpus_size=held
    )
    worst = report.worst
    if worst is not None:
        report.status = worst.treatment
        report.note = (
            f"{worst.citing_key} ({worst.citing_date or '?'}, bench {worst.citing_bench or '?'}) "
            f"{worst.treatment.replace('_', ' ')} this judgment"
        )
        if worst.downgraded_from:
            report.note += (
                f"; its words claim it {worst.downgraded_from.replace('_', ' ')} it, but a bench of "
                f"{worst.citing_bench} cannot overrule one of {cited.bench_strength if cited else '?'}"
            )
    elif not edges:
        report.status = GOOD_LAW
        report.note = (
            f"no judgment among the {held:,} the corpus holds has cited this one, "
            "which is not the same as none ever having done so"
        )
    return report


def treatments_for(session: Session, judgment_ids: list[str]) -> dict[str, TreatmentReport]:
    """Treatment reports for several judgments, for ranking a list of authorities."""
    return {judgment_id: treatment_of(session, judgment_id) for judgment_id in judgment_ids}


def iter_negative_edges(session: Session) -> Iterator[tuple[str, str, str]]:
    """(cited judgment id, citing judgment id, treatment) for every negative edge. For an audit."""
    rows = session.execute(
        select(CitationEdge.cited_id, CitationEdge.citing_id, CitationEdge.treatment).where(
            CitationEdge.treatment.in_(NEGATIVE)
        )
    ).all()
    yield from ((cited, citing, treatment) for cited, citing, treatment in rows if cited)
