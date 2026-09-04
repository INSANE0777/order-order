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
from orderorder.engine.sentences import inside_quotation, sentence_bounds

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
              # The Reports' own annotation in the list of authorities: "Vijay Kumar Mishra v. High
              # Court of Judicature at Patna (2016) 9 SCC 313 - overruled." Terse, but it is the
              # reporter stating the treatment outright. Adjacency is enforced by the position check,
              # not by anchoring, which would now anchor to the sentence rather than the citation.
              | [-–—:]\s*overruled\b
            )
            """
        ),
    ),
    (
        "partly_overruled",
        re.compile(
            r"""(?ix)
            (?: partly\s+overruled
              | overruled\s+in\s+part
              | to\s+th(?:at|e)\s+extent[^.]{0,40}overruled
              | [-–—:]\s*partly\s+overruled\b
            )
            """
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
                  # ... with the earlier decision, not with counsel: rejecting a submission says
                  # nothing about the authority cited alongside it.
                  (?!\s+(?:with\s+)?(?:to\s+)?the\s+(?:submission|contention|argument|plea))
              | (?:with\s+respect|respectfully)\s*,?\s*we\s+(?:differ|disagree)
              # "... not in agreement with the view taken by the learned Single Judge" disagrees with
              # a court, not with the case cited beside it. Disagreement with a case reads "the view
              # taken *in*" and still counts.
              | (?:we\s+are\s+not\s+in\s+agreement\s+with(?!\s+the\s+view\s+taken\s+by))
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
# Negative treatment is measured on two different scales, because the two directions carry different
# risks. Every true negative found in the corpus sits within twenty-odd characters *after* its
# citation — "- overruled.", "are overruled", "has been doubted" — so that window is tight. A cue
# *before* the citation has to clear the case name in between ("we are unable to agree with the
# reasoning in Kasturi v. Iyyamperumal, (2015) 6 SCC 733"), so that window is long, and what keeps it
# safe is not distance but the absence of another citation between the cue and this one.
NEGATIVE_AFTER_WINDOW = 40
NEGATIVE_BEFORE_WINDOW = 120

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
    # "by which this Court overruled ...", "had only partly overruled Surya Dev Rai" — the connectors
    # courts put between a case they are naming and what that case did.
    (?:(?:by\s+which\s+)?(?:this\s+Court\s+)?(?:had\s+)?(?:only\s+)?(?:partly\s+)?)
    (?: overrul(?:ed|ing)\s+(?:the\s+(?:decision|judgment|view|law)|[A-Z])
      | (?:reversed|affirmed|upheld|approved)\s+(?:the\s+(?:decision|judgment|view|order)|[A-Z])
      | held\s+that
      | laid\s+down
    )
    """
)

# Something that looks like another citation: a bracketed year, which every Indian reporter carries.
INTERVENING_CITATION = re.compile(r"[(\[]\s*\d{4}[)\]]|\d{4}\)")

# Treatment that puts an authority in doubt. Anything else leaves it standing.
NEGATIVE = {"overruled", "partly_overruled", "reversed", "doubted", "referred_to_larger_bench"}
# Treatment that only a larger bench may give. Article 141 and the practice under it: a bench cannot
# overrule one at least as large as itself.
LARGER_BENCH_ONLY = {"overruled", "partly_overruled"}
# Treatment that means the judgment rested on the earlier case, so that killing the earlier one
# wounds this one too. Referring to a case, or distinguishing it, does not.
RELIANCE = {"relied_on", "followed"}
# Treatment serious enough to wound whatever rested on it. Doubt and a reference to a larger Bench
# unsettle a case without killing it, and are not carried onward to everything that followed it.
KILLING = {"overruled", "partly_overruled", "reversed"}
DEFAULT_TREATMENT = "referred"
UNDERMINED = "undermined"

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
class UnderminedLink:
    """An authority this judgment rested on, which a later bench has since killed."""

    relied_on_key: str
    relied_on_title: str
    relied_on_treatment: str
    killed_by_key: str
    killed_by_date: str | None
    edge_treatment: str

    def __str__(self) -> str:
        verb = "followed" if self.edge_treatment == "followed" else "relied on"
        return (
            f"it {verb} {self.relied_on_title[:50]} ({self.relied_on_key}), which "
            f"{self.killed_by_key} {self.relied_on_treatment.replace('_', ' ')} in "
            f"{(self.killed_by_date or '?')[:4]}"
        )


@dataclass
class TreatmentReport:
    """What the corpus knows about whether a judgment is still good law."""

    judgment_id: str
    status: str  # good_law | overruled | partly_overruled | reversed | doubted | referred_to_larger_bench | undermined | unknown
    edges: list[TreatmentEdge] = field(default_factory=list)
    citing_count: int = 0
    corpus_size: int = 0
    note: str | None = None
    undermined_by: list[UnderminedLink] = field(default_factory=list)

    @property
    def negative(self) -> list[TreatmentEdge]:
        return [e for e in self.edges if e.is_negative]

    @property
    def is_doubtful(self) -> bool:
        return self.status in NEGATIVE or self.status == UNDERMINED

    @property
    def is_undermined(self) -> bool:
        """Nothing was said about this judgment; what it stood on was taken away."""
        return self.status == UNDERMINED

    @property
    def worst(self) -> TreatmentEdge | None:
        for label in ("overruled", "reversed", "partly_overruled", "referred_to_larger_bench", "doubted"):
            for edge in self.edges:
                if edge.treatment == label:
                    return edge
        return None


def _negative_cue_governs(pattern: re.Pattern[str], line: str, at_start: int, at_end: int) -> bool:
    """Whether a negative cue in this sentence is about the citation at `at_start`.

    The two directions carry different risks and get different rules. Every genuine negative treatment
    in the corpus sits a few characters *after* its citation — "- overruled.", "are overruled", "has
    been doubted" — so a short leash suffices there. A cue *before* the citation has to clear the case
    name in between ("we are unable to agree with the reasoning in Kasturi v. Iyyamperumal, (2015) 6
    SCC 733"), so distance cannot be the test; what makes it safe is that no other citation stands in
    between. In the Reports' tables of authorities one always does.
    """
    for match in pattern.finditer(line):
        if at_end <= match.start() <= at_end + NEGATIVE_AFTER_WINDOW:
            return True
    for match in reversed(list(pattern.finditer(line))):
        if match.end() <= at_start and at_start - match.end() <= NEGATIVE_BEFORE_WINDOW:
            return not INTERVENING_CITATION.search(line[match.end() : at_start])
    return False


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
    # Search the citation's own sentence and judge each cue by where it falls. Judgments list
    # authorities one after another, each with its own annotation — "Krishna Veni Nagam ... - partly
    # overruled. Bhuwan Mohan Singh ... - referred to." — so a cue past the full stop belongs to the
    # previous entry.
    #
    # The cues are matched against the whole sentence rather than against a trimmed window, and the
    # window is then applied to the match's position. Trimming first would silently disarm every
    # guard that has to look further than the window: the lookahead in "not in agreement with (not the
    # view taken by)" needs to see four words that a forty-character window cuts off, and a negative
    # lookahead whose text has been truncated away always succeeds.
    left, right = sentence_bounds(sentence, start)
    line = sentence[left:right]
    at_start, at_end = start - left, end - left
    before = line[max(0, at_start - CUE_WINDOW) : at_start]
    after = line[at_end : at_end + CUE_WINDOW]

    # "reversed by this Court in ...", "overruled the decision in ..." — what follows performed the
    # action rather than suffering it.
    if ACTOR_BEFORE.search(before):
        return DEFAULT_TREATMENT

    for label, pattern in TREATMENT_CUES:
        if label in NEGATIVE:
            # The citation is the actor: "(2019) 8 SCC 714 overruled the decision in ..."
            if ACTOR_AFTER.match(after):
                continue
            if _negative_cue_governs(pattern, line, at_start, at_end):
                return label
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


# "Pune Municipal Corporation & Anr. (supra)" — a case named without its citation, because the
# citation was given earlier in the same judgment. The name may run to several words and carry the
# punctuation of a cause title.
SUPRA_REFERENCE = re.compile(
    r"(?P<name>[A-Z][\w.'’-]*(?:\s+(?:v\.?|vs\.?|versus|&|and|of|the|[A-Z][\w.'’-]*)){0,9})"
    r"\s*\(\s*supra\s*\)"
)
# How closely a "(supra)" name must match a case cited in full earlier in the same judgment.
SUPRA_MATCH_SCORE = 82.0
SUPRA_MATCH_MARGIN = 8.0


@dataclass(frozen=True)
class _Reference:
    """A place in a paragraph where a case is named, however it is named there."""

    raw: str
    span: tuple[int, int]
    cited_id: str


def antecedents(
    paragraphs: list[Paragraph], aliases: dict[str, str], titles: dict[str, str]
) -> dict[str, str]:
    """The cases this judgment cites, as {id: title}: what a "(supra)" reference may refer to.

    Keyed by id and valued by title because that is what the matcher scores — rapidfuzz reads a
    mapping's values and hands back its keys — and inverting it silently scores the query against a
    column of identifiers instead of against the titles.

    The candidate set is what makes this safe. A "(supra)" reference means a case cited earlier in the
    same judgment, so the only cases it can name are the ones this judgment cites — a few dozen, not
    nine thousand — and a name is matched against their titles rather than against the corpus.

    Matching titles rather than the words printed beside the citation is what makes it work at all.
    Judgments cite in footnotes: the text reads "Pune Municipal Corporation v. Harakchand Misirimal
    Solanki38" and the citation "38 (2014) 3 SCC 183" sits at the foot of the page, so the name and the
    citation are never adjacent and there is nothing to read off the citation itself.
    """
    named: dict[str, str] = {}
    for paragraph in paragraphs:
        for citation in extract_citations(paragraph.body):
            cited_id = aliases.get(citation.normalized)
            title = titles.get(cited_id or "")
            if cited_id and title:
                named.setdefault(cited_id, title)
    return named


def resolve_supra(name: str, named: dict[str, str]) -> str | None:
    """Which case cited earlier in this judgment a "(supra)" reference means, if one clearly."""
    if not named:
        return None
    from rapidfuzz import fuzz, process, utils

    matches = process.extract(
        name,
        named,
        scorer=fuzz.token_set_ratio,
        processor=utils.default_process,
        limit=2,
        score_cutoff=SUPRA_MATCH_SCORE,
    )
    if not matches:
        return None
    # Two different cases cited in this judgment answer to the name. Which one "(supra)" means is
    # what a reader resolves from context, and guessing would attach a holding to the wrong case.
    if (
        len(matches) > 1
        and (matches[0][1] - matches[1][1]) < SUPRA_MATCH_MARGIN
        and matches[0][2] != matches[1][2]
    ):
        return None
    return matches[0][2]


def title_map(session: Session) -> dict[str, str]:
    """Every judgment's title, held in memory for the same reason the aliases are."""
    return {
        judgment_id: title or ""
        for judgment_id, title in session.execute(select(Judgment.id, Judgment.title)).all()
    }


def edges_in_judgment(
    judgment: Judgment,
    paragraphs: list[Paragraph],
    aliases: dict[str, str],
    titles: dict[str, str] | None = None,
) -> list[CitationEdge]:
    """Every citation in one judgment that resolves to another judgment the corpus holds.

    Both ways a judgment names a case are read: the full citation, and the "(supra)" reference that
    stands in for it afterwards. The second matters more than its share of the text suggests, because
    a judgment gives the full citation while surveying the authorities and says "(supra)" when it
    comes to decide. The sentence that overruled Pune Municipal Corporation — "Resultantly, the
    decision rendered in Pune Municipal Corporation & Anr. (supra) is hereby overruled" — carries no
    citation at all, and a citator reading only citations cannot see the thing it exists to find.
    """
    found: list[CitationEdge] = []
    seen: set[tuple[str, str]] = set()
    named = antecedents(paragraphs, aliases, titles or {})

    for paragraph in paragraphs:
        references: list[_Reference] = []
        for citation in extract_citations(paragraph.body):
            cited_id = aliases.get(citation.normalized)
            if cited_id:
                references.append(_Reference(citation.raw, citation.span, cited_id))
        for match in SUPRA_REFERENCE.finditer(paragraph.body):
            supra_id = resolve_supra(match.group("name"), named)
            if supra_id is not None:
                name = " ".join(match.group("name").split())
                references.append(_Reference(f"{name} (supra)", match.span(), supra_id))

        for citation in references:
            cited_id = citation.cited_id
            if cited_id == judgment.id:
                continue  # a judgment citing itself teaches nothing
            # The span is given relative to the paragraph, and so is the reference, so the cue window
            # is read around the reference where it sits rather than around the sentence as a whole.
            treatment = classify_treatment(paragraph.body, citation.span)

            # A judgment quoting "the decision in X is hereby overruled" is reporting an overruling,
            # not performing one. Recording it as this court's own would credit a two-judge bench with
            # a Constitution Bench's work, and the bench rule would then downgrade a real overruling
            # to doubt. The overruling itself is not lost: it is on the record in the judgment that
            # actually gave it, which is where this reads it from.
            if treatment in NEGATIVE and inside_quotation(paragraph.body, citation.span[0]):
                treatment = DEFAULT_TREATMENT
            marker = (cited_id, treatment)
            if marker in seen:
                continue
            seen.add(marker)
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
    titles = title_map(session)
    stats = CitatorStats()
    judgments = _judgments_with_text(session, limit=limit, skip_done=not rebuild)
    total = len(judgments)

    for done, judgment in enumerate(judgments, start=1):
        paragraphs = _paragraphs_of(session, judgment.id)
        edges = edges_in_judgment(judgment, paragraphs, aliases, titles)
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


def undermining_links(session: Session, judgment_id: str) -> list[UnderminedLink]:
    """Authorities this judgment rested on that have since been overruled.

    A judgment is not only wounded by what was said about it. It is wounded by what happened to the
    cases it stood on. The Constitution Bench in Indore Development Authority said so in terms:
    "all other decisions in which Pune Municipal Corpn. has been followed, are also overruled."

    Three limits keep this from spreading further than it should.

    * **Only reliance counts.** `relied_on` and `followed` mean the judgment rested on the earlier
      case. Merely referring to it, or distinguishing it, does not.
    * **Only what came afterwards.** A judgment decided after the overruling has had the chance to
      take it into account, and cannot be undermined by news it already had.
    * **One hop.** Reliance compounds uncertainty at every step, and the engine cannot see whether
      the particular holding relied on is the one that was overruled. At one remove the warning is
      worth giving; at three it would be noise.
    """
    judgment = session.get(Judgment, judgment_id)
    if judgment is None:
        return []
    relied = session.execute(
        select(CitationEdge, Judgment)
        .join(Judgment, CitationEdge.cited_id == Judgment.id)
        .where(CitationEdge.citing_id == judgment_id, CitationEdge.treatment.in_(RELIANCE))
    ).all()

    links: list[UnderminedLink] = []
    for edge, relied_on_judgment in relied:
        if relied_on_judgment.id == judgment_id:
            continue
        killer = _worst_direct_edge(session, relied_on_judgment)
        if killer is None or killer.treatment not in KILLING:
            continue
        # News a judgment already had cannot have undermined it.
        if judgment.decided_on and killer.citing_date and judgment.decided_on.isoformat() >= killer.citing_date:
            continue
        links.append(
            UnderminedLink(
                relied_on_key=relied_on_judgment.canonical_key,
                relied_on_title=relied_on_judgment.title,
                relied_on_treatment=killer.treatment,
                killed_by_key=killer.citing_key,
                killed_by_date=killer.citing_date,
                edge_treatment=edge.treatment or DEFAULT_TREATMENT,
            )
        )
    return links


def _worst_direct_edge(session: Session, cited: Judgment) -> TreatmentEdge | None:
    """The most serious thing any later judgment did to this one, with the bench rule applied.

    Direct edges only, and deliberately: this is the step that stops one hop becoming an unbounded
    walk of the citation graph.
    """
    rows = session.execute(
        select(CitationEdge, Judgment)
        .join(Judgment, CitationEdge.citing_id == Judgment.id)
        .where(CitationEdge.cited_id == cited.id, CitationEdge.treatment.in_(NEGATIVE))
    ).all()
    edges = []
    for edge, citing in rows:
        treatment, claimed = apply_bench_rule(
            edge.treatment or DEFAULT_TREATMENT, citing.bench_strength, cited.bench_strength
        )
        edges.append(
            TreatmentEdge(
                citing_key=citing.canonical_key,
                citing_title=citing.title,
                citing_date=citing.decided_on.isoformat() if citing.decided_on else None,
                citing_bench=citing.bench_strength,
                treatment=treatment,
                paragraph_label=None,
                downgraded_from=claimed,
            )
        )
    for label in ("overruled", "reversed", "partly_overruled", "referred_to_larger_bench", "doubted"):
        for edge in edges:
            if edge.treatment == label:
                return edge
    return None


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
    elif links := undermining_links(session, judgment_id):
        # Nothing has been said about this judgment. Something has been said about what it rested on.
        report.status = UNDERMINED
        report.undermined_by = links
        report.note = (
            "no later judgment has criticised this one, but " + str(links[0])
            + ". That is an inference from the citation graph, not a holding of any court: whether "
            "this judgment's own reasoning survives depends on which part of the earlier case it used."
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
