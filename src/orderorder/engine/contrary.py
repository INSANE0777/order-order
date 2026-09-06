"""What says the opposite of what this draft argues.

`docs/PRD.md` B8, and the one thing `drafting.attack` says in terms that it does not do: "the draft was
not searched for a judgment stating the opposite of what it argues; the leads below are judgments that
matched the same words, which is not the same thing." This module is that search.

The gate, the citator and the self-attack between them cover every attack that can be made *about an
authority*: it was overruled, it was distinguished, a larger bench sat on the same words, nobody has
ever cited it. None of them covers the attack an opponent actually opens with, which is about the
proposition rather than the authority — **there is a judgment that says the other thing**.

## Why the ordinary search cannot answer it

The instinct is that a contrary holding is far away in the retrieval field and needs some other kind of
search to reach. It is the opposite. A paragraph that contradicts a proposition is the *nearest* thing
in the corpus to it, because it is about exactly the same subject in almost exactly the same words:

    the proposition   a notice under Section 106 is mandatory before a suit for eviction
    the contradiction the requirement of notice under Section 106 is directory and not mandatory

Every distinctive term is shared. BM25 cannot tell them apart, and neither can a proximity query, and
neither will a dense encoder that was trained to put sentences about the same subject in the same
place. Retrieval finds both; what separates them is not vocabulary but **polarity**, which is a
property of the grammar and not of the ranking.

So the retrieval here is the ordinary one — the same corpus-wide search `engine.search` already does,
which drops anything that is not the court speaking before it ranks — run over a wide field, and the
work is in what happens to the field afterwards.

## What a string can honestly decide

Two sentences are opposed, for the purpose of this module, when they are about the same thing and one
of them carries a negation the other does not:

  * **the same thing** — they share enough distinctive terms, counted after the words that appear in
    every paragraph of every judgment are taken out (`UBIQUITOUS`), because "court", "held" and "law"
    are not evidence that two sentences are about one subject;
  * **a negation the other does not carry** — inside the *clause* that carries those shared terms, not
    inside the sentence. A judgment routinely sets out a contention and then rejects it, so a sentence
    containing "not" says nothing until you know which clause the "not" is in;
  * **or a term of art that carries its own negation** — `mandatory` against `directory`, and the
    morphological pairs (`non-`, `in-`, `un-`) which are a rule rather than a list.

That is a lead and it is written as one. What the string test establishes is that a court, in its own
voice, wrote a sentence on this subject with the opposite polarity. Whether that sentence *contradicts*
this proposition — rather than distinguishing it, confining it to other facts, or stating the rule for
a different statute with the same words — is a reading, and a reading needs either a lawyer or a model
that can be checked. `assess_opposition` is that second reading; it is off by default and
`evals/report-contrary.txt` says what it was worth.

The honest failure mode of the string test is the one worth stating up front: it finds sentences whose
*form* is opposed. A court writing "the appellant's contention that the notice is mandatory cannot be
accepted" and one writing "the notice is not mandatory" are both found, which is right. A court writing
"the notice is not mandatory *where the tenant has waived it*" is also found, and that one is a
narrower rule rather than a contradiction. Which is why the fix a lead carries is "read it", never
"drop the point".

## What it cannot see

The corpus. 56% of the citations these judgments make are to judgments decided before 2013, which is
where the corpus starts, so the judgment that says the other thing may simply not be held here. Every
report therefore states how many judgments were searched, in the same words the treatment report uses,
because "nothing contradicts this" over nine thousand judgments and over seventy-five years of the
Supreme Court are different sentences.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.db.models import Judgment, JudgmentTextVersion, Opinion, Paragraph
from orderorder.engine.citator import corpus_size
from orderorder.engine.lexical import tokenize
from orderorder.engine.quotes import normalized
from orderorder.engine.search import Authority, find_authorities, index_exists
from orderorder.engine.sentences import split_sentences

# How wide a field to look across, and how deep the raw retrieval goes to fill it. Wider than the
# supporting search by an order of magnitude, and deliberately: a supporting authority only has to be
# found once, so the top few are enough, while the judgment that says the other thing is one paragraph
# somewhere in the field and being 60th is not being absent.
DEFAULT_FIELD = 150
DEFAULT_CANDIDATES = 400
DEFAULT_TOP = 5

# How much subject two sentences have to share before their polarities are worth comparing. Both
# conditions, because either alone fails in a way the other catches: a long proposition can share four
# terms with a paragraph about something else entirely, and a short one can share all of its terms and
# still be four words long.
MIN_SHARED_TERMS = 4
MIN_SHARED_SHARE = 0.30

# Words that appear in most paragraphs of most judgments, and so are evidence of nothing. This list is
# short on purpose: legal vocabulary is what makes two sentences about the same subject, and stripping
# it in the name of tidiness would leave nothing to match on. Only words that carry no subject at all.
UBIQUITOUS = frozenset(
    """
    court courts judgment judgments judgement case cases law laws legal held hold holding
    learned counsel submitted submission submissions contention contended appeal appeals appellant
    appellants respondent respondents petitioner petitioners hon ble supreme india indian
    view matter matters question questions issue issues fact facts present instant
    para paragraph paragraphs decision decisions bench judge judges justice

    before after under over upon into within during against between among through above below
    where when whether while since because therefore thus hence merely even still already further
    """.split()  # noqa: SIM905 - a readable block beats a 60-element list literal
)

# What negates a clause. Written as whole words with boundaries, because "cannot" is a negation and
# "canon" is not, and because "no" inside "notice" has ended more than one regex.
NEGATORS = re.compile(
    r"""(?ix)
    \b(?:
        not | never | cannot | can \s+ not | none | nor | neither
      # "No" negates a clause; "Civil Appeal No. 1234 of 2019" does not, and a citation in the
      # middle of a sentence would otherwise flip its polarity.
      | no (?! \s* \.? \s* \d)
      | unable \s+ to
      | fails? \s+ to | failed \s+ to
      | far \s+ from
      | devoid \s+ of
      | without
      | refuse[ds]? \s+ to | declined? \s+ to
      | rejected? | repelled
    )\b
    """
)

# Where one clause ends and the next begins, with the joint kept so the caller can see which one it
# was. Two kinds of joint matter and they behave differently.
#
# "That" is the joint an Indian judgment turns on -- "the contention that the notice is mandatory
# cannot be accepted" is two clauses with opposite polarities, and reading it as one sentence gets the
# answer exactly backwards.
#
# "Where", "when", "unless", "if" introduce the condition a court attaches to a rule, and a negation
# inside the condition says nothing about the rule: "a notice is mandatory only where the tenancy has
# not been determined" *asserts* that the notice is mandatory. Without this break that sentence reads
# as the opposite of itself, which is the first false positive this module produced.
#
# "That" only counts when it is a complementiser. A judgment writes "of that Act", "in that case",
# "the view taken in that judgment" constantly, and breaking there cuts a clause in half and loses the
# negation that governed it. What marks the complementiser is the word in front of it: a verb or noun
# of saying or holding. So the joint is matched as a phrase — "contention that", "cannot be said that"
# — and the test for a complement is the last word of the joint.
CLAUSE_BREAK = re.compile(
    r"""(?ix)
    ( [;:,]
    | \s\b(?: held | holds | hold | said | says | say | stated | states | state | observed | observes
            | submitted | submits | contended | contends | urged | argued | argues | found | finds
            | concluded | concludes | accepted | accepts | agreed | agree | means | meant | shows
            | show | indicates | indicate | persuaded | satisfied | clear | settled | established
            | contention | contentions | submission | submissions | argument | arguments | proposition
            | principle | plea | ground | opinion | conclusion | finding | doctrine | view | so
        )\s+that\b
    | \s\b whether \b
    | \s\b(?: but | however | whereas | although | though | because | since | unless | until | while
            | where | when | if | once | provided | except | save | and | or | before | after )\b
    )
    """
)
# Joints that introduce a complement rather than a clause of its own. "It cannot be said that the
# notice is mandatory" holds the proposition in the complement and the negation in the matrix around
# it, and the sentence denies the proposition.
COMPLEMENTISERS = {"that", "whether"}

# Pairs where the negation is lexical rather than grammatical: no "not" appears, and the two words are
# nonetheless opposites in Indian doctrine. Deliberately tiny. Every pair here is one where a court
# writing the second has contradicted an advocate arguing the first, with no reading required.
ANTONYMS: list[tuple[str, str]] = [
    ("mandatory", "directory"),
    ("mandatory", "optional"),
    ("valid", "void"),
    ("valid", "invalid"),
    ("legal", "illegal"),
    ("admissible", "inadmissible"),
    ("maintainable", "unmaintainable"),
    ("retrospective", "prospective"),
    ("bailable", "nonbailable"),
    ("justiciable", "nonjusticiable"),
    ("arbitrable", "nonarbitrable"),
    ("permissible", "impermissible"),
    ("necessary", "unnecessary"),
    ("sufficient", "insufficient"),
    ("binding", "persuasive"),
]
# Prefixes that turn a word into its own opposite. A rule rather than a list, so it covers the terms of
# art nobody thought to write down -- but only where the stem is a real word of four letters or more,
# because "invitation" is not the negation of "vitation".
NEGATING_PREFIXES = ("non", "in", "un", "im", "ir", "il", "dis")
MIN_STEM = 4


@dataclass(frozen=True)
class Opposition:
    """Why one sentence is the opposite of another, in terms a reader can check against the text."""

    kind: str  # negation | antonym | dissent
    cue: str  # the word or phrase that carries the flip, as it appears in the text
    shared_terms: tuple[str, ...]
    proposition_clause: str
    sentence_clause: str

    def describe(self) -> str:
        if self.kind == "antonym":
            return f"the court says {self.cue}, over {len(self.shared_terms)} shared terms"
        if self.kind == "dissent":
            return "a dissenting judge in the very case relied on"
        return f"the court's sentence carries \"{self.cue}\" where the proposition does not"


@dataclass
class ContraryLead:
    """One passage a court wrote that reads against the proposition. A lead, not a finding."""

    authority: Authority
    sentence: str
    sentence_start: int
    sentence_end: int
    opposition: Opposition
    # Filled only when a model has read the pair. None means nobody read it, which is not the same as
    # a model having read it and found nothing -- the distinction the whole engine is built on.
    reading: OppositionReading | None = None

    @property
    def pinpoint(self) -> str:
        return self.authority.pinpoint

    @property
    def is_confirmed(self) -> bool:
        return self.reading is not None and self.reading.contradicts


@dataclass
class OppositionReading:
    """A second reading of one lead: does that sentence actually contradict the proposition?"""

    contradicts: bool
    grounded: bool
    quote: str | None = None
    reason: str | None = None
    model: str | None = None


@dataclass
class ContraryReport:
    """Everything the corpus was asked, and everything it answered, for one proposition."""

    proposition: str
    leads: list[ContraryLead] = field(default_factory=list)
    judgments_searched: int = 0
    paragraphs_examined: int = 0
    queries: list[str] = field(default_factory=list)
    read_by_model: bool = False
    searched: bool = True

    @property
    def found(self) -> bool:
        return bool(self.leads)

    def describe(self) -> str:
        """What was established, in words that do not claim more than was done."""
        if not self.searched:
            return (
                "not searched: the full-text index has not been built, so no part of the corpus was "
                "read for a contrary holding"
            )
        if not self.leads:
            return (
                f"no passage opposed to this proposition was found in the {self.judgments_searched:,} "
                f"judgments held; {self.paragraphs_examined:,} paragraphs on the same subject were "
                "examined. The corpus begins in 2013, so a judgment that says otherwise may simply "
                "not be here"
            )
        confirmed = sum(1 for lead in self.leads if lead.is_confirmed)
        if self.read_by_model:
            return (
                f"{len(self.leads)} passage(s) read against the proposition; {confirmed} were confirmed "
                "as stating the opposite"
            )
        return (
            f"{len(self.leads)} passage(s) a court wrote on this subject with the opposite polarity. "
            "Nothing has read them against the proposition; each is a lead to check, not a holding"
        )


def distinctive_terms(text: str) -> list[str]:
    """Content terms, with the words that appear in every judgment taken out."""
    return [t for t in dict.fromkeys(tokenize(text)) if t not in UBIQUITOUS and len(t) > 2]


@dataclass(frozen=True)
class Clause:
    """One clause of a sentence, and the joint that introduced it."""

    text: str
    joint: str | None  # lower-cased connector, or None for the first clause


def clause_parts(text: str) -> list[Clause]:
    """Split a sentence where its polarity can change, keeping the joints."""
    pieces = CLAUSE_BREAK.split(text)
    parts: list[Clause] = []
    joint: str | None = None
    for position, piece in enumerate(pieces):
        if position % 2 == 1:
            joint = piece.strip().lower()
            continue
        body = piece.strip()
        if body:
            parts.append(Clause(body, joint))
        joint = None
    return parts


def clauses(text: str) -> list[str]:
    """The clause texts alone, for callers that do not care how they were joined."""
    return [part.text for part in clause_parts(text)]


def negated(clause: str) -> tuple[bool, str | None]:
    """Whether a clause is negated, and by which word. Two negations cancel, as they do in English."""
    found = NEGATORS.findall(clause)
    if not found:
        return False, None
    # `findall` on a pattern with no groups returns the whole matches, which is what should be quoted
    # back: a reader checking the finding wants the word that is actually in the judgment.
    return len(found) % 2 == 1, found[0].strip()


def is_complement(part: Clause) -> bool:
    """Whether this clause is the complement of a verb or noun of saying, rather than a clause."""
    return bool(part.joint) and part.joint.split()[-1] in COMPLEMENTISERS


def negated_at(parts: list[Clause], index: int) -> tuple[bool, str | None]:
    """The polarity of one clause, counting the negation that governs it from outside.

    "It cannot be said that a notice is mandatory" holds its negation in the matrix clause and its
    proposition in the complement. Reading the complement alone reports the sentence as asserting
    exactly what it denies, which is not a near miss: it is the answer inverted.

    The matrix can sit on either side of its complement — "the contention that X cannot be accepted"
    wraps it — so where the clause is a complement the parity is taken over the whole sentence.
    Crude, and right in every shape that occurs: one negation anywhere denies the complement, two
    cancel, and "we accept the contention that X is not mandatory" comes out opposed to X, which it is.

    Where it is wrong it is wrong in the safe direction. "The contention that a notice is mandatory
    where it was not waived cannot be accepted" holds two negations that do not cancel in meaning, and
    the sentence is read as agreeing. A lead not raised costs a reader nothing; a lead raised
    backwards costs them their confidence in every other one.
    """
    if is_complement(parts[index]):
        cues = [c.strip() for part in parts for c in NEGATORS.findall(part.text)]
    else:
        cues = [c.strip() for c in NEGATORS.findall(parts[index].text)]
    return len(cues) % 2 == 1, (cues[0] if cues else None)


def _stem_of(word: str) -> str | None:
    """The word a negating prefix was attached to, if one was."""
    for prefix in NEGATING_PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= MIN_STEM:
            return word[len(prefix) :]
    return None


def antonym_between(left: str, right: str) -> tuple[str, str] | None:
    """A term of art in `left` whose opposite is in `right`. Returns (term, its opposite).

    Each half has to hold its word *and not the other*. A court writing "the provision is directory
    and not mandatory" carries both words in one sentence, and without the exclusivity test that
    sentence is the opposite of itself — which is the shape of every self-contradicting detector ever
    shipped, and the reason the control in `evals/report-contrary.txt` is a control rather than a
    formality.
    """
    left_terms = set(tokenize(left))
    right_terms = set(tokenize(right))

    def only_in(word: str, terms: set[str], other: set[str]) -> bool:
        return word in terms and word not in other

    for first, second in ANTONYMS:
        if only_in(first, left_terms, right_terms) and only_in(second, right_terms, left_terms):
            return first, second
        if only_in(second, left_terms, right_terms) and only_in(first, right_terms, left_terms):
            return second, first
    # And the morphological rule, in the direction that matters: the proposition asserts the plain
    # word and the court wrote the prefixed one, or the reverse.
    for term in right_terms:
        stem = _stem_of(term)
        if stem and only_in(stem, left_terms, right_terms) and only_in(term, right_terms, left_terms):
            return stem, term
    for term in left_terms:
        stem = _stem_of(term)
        if stem and only_in(stem, right_terms, left_terms) and only_in(term, left_terms, right_terms):
            return term, stem
    return None


def richest_clause(parts: list[Clause], wanted: set[str]) -> int:
    """Which clause carries most of the shared terms: the clause the sentence is *about*."""
    best, best_score = 0, -1
    for index, part in enumerate(parts):
        score = len(wanted & set(tokenize(part.text)))
        if score > best_score:
            best, best_score = index, score
    return best


def opposes(proposition: str, sentence: str) -> Opposition | None:
    """Whether `sentence` reads against `proposition`. Pure string work; no model, no database.

    The order of the two tests matters. Grammatical negation is checked first because it is the common
    case and because it is the one that can be quoted back word for word; the antonym table only gets a
    say where no negation explains the difference.
    """
    # Nothing can be the opposite of itself. A proposition lifted verbatim out of a judgment will meet
    # its own paragraph at the top of the retrieval field every time, and a detector that flags it
    # there is not a detector. This is the one line that makes that structurally impossible rather
    # than improbable, and `test_contrary` pins it.
    left, right = normalized(proposition), normalized(sentence)
    if left in right or right in left:
        return None

    wanted = set(distinctive_terms(proposition))
    if not wanted:
        return None
    shared = wanted & set(distinctive_terms(sentence))
    if len(shared) < MIN_SHARED_TERMS or len(shared) / len(wanted) < MIN_SHARED_SHARE:
        return None

    proposition_parts = clause_parts(proposition)
    sentence_parts = clause_parts(sentence)
    proposition_at = richest_clause(proposition_parts, shared)
    sentence_at = richest_clause(sentence_parts, shared)
    proposition_clause = proposition_parts[proposition_at].text
    sentence_clause = sentence_parts[sentence_at].text
    ordered = tuple(sorted(shared))

    proposition_negated, proposition_cue = negated_at(proposition_parts, proposition_at)
    sentence_negated, cue = negated_at(sentence_parts, sentence_at)
    if proposition_negated != sentence_negated:
        # Where the court's sentence carries the negation, quote the court's word. Where the
        # proposition is the negated one and the court asserted what the advocate denies, there is
        # nothing in the judgment to quote, so the finding names the proposition's own negator rather
        # than inventing one for the court.
        carried = cue if sentence_negated else proposition_cue
        return Opposition("negation", carried or "not", ordered, proposition_clause, sentence_clause)

    pair = antonym_between(proposition_clause, sentence_clause)
    if pair is not None:
        return Opposition("antonym", pair[1], ordered, proposition_clause, sentence_clause)
    return None


def contrary_queries(proposition: str) -> list[str]:
    """The proposition, and the same proposition with its terms of art swapped for their opposites.

    One retrieval on the proposition's own words finds most of what contradicts it, because a
    contradiction shares the subject. It misses the case where the opposite is a different *word*:
    a proposition about a notice being `mandatory` shares nothing with the sentence calling it
    `directory` except the subject, and the subject alone may not be enough to reach the top of a
    field of four hundred thousand paragraphs. So each antonym in the proposition raises one more
    query, capped, because each is a search over the whole corpus and they are not free.
    """
    queries = [proposition]
    terms = set(tokenize(proposition))
    for first, second in ANTONYMS:
        for present, opposite in ((first, second), (second, first)):
            if present in terms:
                swapped = re.sub(rf"\b{re.escape(present)}\b", opposite, proposition, flags=re.IGNORECASE)
                if swapped not in queries:
                    queries.append(swapped)
    return queries[:3]


def _sentence_leads(proposition: str, authority: Authority) -> ContraryLead | None:
    """The first sentence of a retrieved paragraph that reads against the proposition."""
    for sentence, offset in split_sentences(authority.body):
        opposition = opposes(proposition, sentence)
        if opposition is not None:
            return ContraryLead(
                authority=authority,
                sentence=sentence,
                sentence_start=offset,
                sentence_end=offset + len(sentence),
                opposition=opposition,
            )
    return None


def find_contrary(
    session: Session,
    proposition: str,
    *,
    exclude: tuple[str, ...] = (),
    top: int = DEFAULT_TOP,
    field_size: int = DEFAULT_FIELD,
    candidates: int = DEFAULT_CANDIDATES,
    expand: bool = True,
) -> ContraryReport:
    """Search the corpus for a court saying the opposite of this proposition.

    `exclude` names judgments to leave out, which is how the drafting surface keeps the authority the
    draft already cites from being reported as an attack on itself.
    """
    report = ContraryReport(proposition=proposition, judgments_searched=corpus_size(session))
    if not index_exists(session):
        # Without the index there is no corpus-wide search, and a report that said "nothing found"
        # would be describing a search that never ran.
        report.searched = False
        return report

    queries = contrary_queries(proposition) if expand else [proposition]
    report.queries = queries

    seen: set[str] = set()
    examined = 0
    leads: list[ContraryLead] = []
    for query in queries:
        for authority in find_authorities(
            session,
            query,
            top=field_size,
            candidates=candidates,
            one_per_judgment=False,
            check_treatment=False,
        ):
            key = f"{authority.judgment_id}:{authority.paragraph_seq}"
            if key in seen or authority.judgment_id in exclude:
                continue
            seen.add(key)
            examined += 1
            lead = _sentence_leads(proposition, authority)
            if lead is not None:
                leads.append(lead)

    report.paragraphs_examined = examined
    # A larger bench saying the opposite is worse news than a smaller one, and that is what `score`
    # already carries: relevance plus standing. One lead per judgment, because the same court making
    # the same point twice is one thing to read.
    leads.sort(key=lambda lead: -lead.authority.score)
    best: list[ContraryLead] = []
    taken: set[str] = set()
    for lead in leads:
        if lead.authority.judgment_id in taken:
            continue
        taken.add(lead.authority.judgment_id)
        best.append(lead)
    report.leads = best[:top]
    return report


def dissents_in(session: Session, judgment_id: str, proposition: str) -> list[ContraryLead]:
    """The dissenting opinions inside the very judgment the draft relies on.

    The cheapest contrary authority there is, and the one an opponent reaches for first: it is in the
    same case, it needs no search to find, and it was written by a judge who heard the same argument.
    It is not a contradiction in law -- a dissent decides nothing -- which is why it is reported as
    what it is. The polarity test is not applied. A dissent is contrary by construction, and requiring
    it to also look contrary would drop the ones that disagree by reasoning rather than by wording.
    """
    version = session.scalars(
        select(JudgmentTextVersion).where(
            JudgmentTextVersion.judgment_id == judgment_id, JudgmentTextVersion.preferred.is_(True)
        )
    ).first()
    if version is None:
        return []
    opinions = session.scalars(
        select(Opinion).where(Opinion.text_version_id == version.id, Opinion.kind == "dissenting")
    ).all()
    if not opinions:
        return []

    judgment = session.get(Judgment, judgment_id)
    if judgment is None:
        return []

    wanted = set(distinctive_terms(proposition))
    leads: list[ContraryLead] = []
    for opinion in opinions:
        paragraphs = session.scalars(
            select(Paragraph)
            .where(Paragraph.opinion_id == opinion.id)
            .order_by(Paragraph.seq)
        ).all()
        best: tuple[int, Paragraph, str, int] | None = None
        for paragraph in paragraphs:
            for sentence, offset in split_sentences(paragraph.body):
                overlap = len(wanted & set(distinctive_terms(sentence)))
                if best is None or overlap > best[0]:
                    best = (overlap, paragraph, sentence, offset)
        if best is None:
            continue
        _, paragraph, sentence, offset = best
        authority = Authority(
            judgment_id=judgment.id,
            canonical_key=judgment.canonical_key,
            title=judgment.title,
            citation=None,
            court=judgment.court,
            decided_on=judgment.decided_on.isoformat() if judgment.decided_on else None,
            bench_strength=judgment.bench_strength,
            paragraph_label=paragraph.printed_label,
            paragraph_seq=paragraph.seq,
            body=paragraph.body,
            relevance=0.0,
            score=0.0,
            line=sentence,
        )
        leads.append(
            ContraryLead(
                authority=authority,
                sentence=sentence,
                sentence_start=offset,
                sentence_end=offset + len(sentence),
                opposition=Opposition(
                    kind="dissent",
                    cue=opinion.author or "a dissenting judge",
                    shared_terms=tuple(sorted(wanted & set(distinctive_terms(sentence)))),
                    proposition_clause=proposition,
                    sentence_clause=sentence,
                ),
            )
        )
    return leads
