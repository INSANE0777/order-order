"""Measuring the search for a contrary holding, and being honest about which half of it is circular.

Ground truth for "these two sentences contradict each other" is not something the corpus supplies. It
supplies the opposite: sentences a court wrote, which the corpus can name. So the item is built by
turning one of those around.

Take a holding — a sentence the court wrote, in a paragraph the corpus can point at — and put it to
the engine twice:

    **opposed**  the holding negated, which is what the advocate on the other side asserts.
                 The source paragraph is then a contrary authority for that proposition, and it is
                 known to be one before the search runs.
    **agreed**   the holding as the court wrote it, which is what the advocate relying on it asserts.
                 Nothing in that paragraph is contrary to it, and any lead the engine returns from
                 that judgment is a lead it should not have returned.

Two runs over the same corpus, from one sentence, differing only in polarity.

## What is circular here, and what is not

The negation that builds the `opposed` query and the negation the detector reads are the same idea,
so **recall on the source paragraph is largely a property of the construction**, not a finding. It is
reported because a number that should be near 100% and is not says something has broken — but it is
not evidence that the detector works, and this file will not pretend otherwise.

Three things measured here are *not* circular.

**Retrieval.** Whether the source paragraph is in the field at all when the query is the negation of
its own sentence. Nothing guarantees it: the retrieval is BM25 and proximity over the whole corpus,
and the negated query is competing with four hundred thousand paragraphs.

**Discrimination.** The number of leads returned for the negated proposition against the number
returned for the court's own words. If a tool returns as many contrary passages for a proposition the
court itself stated as for its negation, the polarity test is doing nothing at all, and every summary
statistic would still look healthy. This is the number that says whether the module works.

**The floor.** How often the engine answers a proposition that is a court's own holding with a
passage from some *other* judgment said to contradict it. Some of those are real — courts do disagree,
and a corpus of nine thousand judgments contains genuine conflicts — so this is an upper bound on the
false-positive rate rather than the rate itself. It is the number a user feels: leads to read for a
proposition that is not in doubt.

The one thing structurally guaranteed is that the source paragraph is never returned for the `agreed`
query, because a sentence cannot be the opposite of a sentence containing it. That guard is pinned in
`tests/test_contrary.py` rather than measured here; a control that cannot fail is not a measurement.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.db.models import Judgment, JudgmentTextVersion, Paragraph
from orderorder.engine.contrary import (
    NARROWER,
    OPPOSITE,
    RECORD_BOUND,
    SAME,
    UNREAD,
    UNRELATED,
    ContraryLead,
    ContraryReport,
    Opposition,
    assess_opposition,
    find_contrary,
)
from orderorder.engine.providers import StructuredModel
from orderorder.engine.search import Authority
from orderorder.evaluation.generate import collect_seed

OPPOSED = "opposed"
AGREED = "agreed"
KINDS = [OPPOSED, AGREED]
KIND_NAMES = {
    OPPOSED: "the holding, negated",
    AGREED: "the holding, as written",
}

# How the negation is put in, and taken out. Ordered: the first site in the sentence wins, so a
# sentence with two candidate verbs is negated on the one the court reached first, which is almost
# always its main verb. Every pair is reversible, because the `agreed` half of an item built from a
# court's *negative* holding has to come back out.
NEGATIONS: list[tuple[str, str]] = [
    (r"\bcannot\b", "can"),
    (r"\bis not\b", "is"),
    (r"\bare not\b", "are"),
    (r"\bwas not\b", "was"),
    (r"\bwere not\b", "were"),
    (r"\bdoes not\b", "does"),
    (r"\bdo not\b", "do"),
    (r"\bdid not\b", "did"),
    (r"\bshall not\b", "shall"),
    (r"\bwill not\b", "will"),
    (r"\bmay not\b", "may"),
    (r"\bmust not\b", "must"),
    (r"\bneed not\b", "must"),
    (r"\bhas not\b", "has"),
    (r"\bhave not\b", "have"),
    (r"\bhad not\b", "had"),
    (r"\bno longer\b", "still"),
    # "Has no application" is how a judgment most often says a rule does not apply, and it negates
    # with a determiner rather than an auxiliary.
    (r"\bhas no\b", "has"),
    (r"\bhave no\b", "have"),
    (r"\bhad no\b", "had"),
]
# And in the other direction: an affirmative sentence, negated. Not the mirror image of the list
# above, because "must" negates to "need not" and un-negates from it, and because "can" has to become
# "cannot" as one word.
AFFIRMATIONS: list[tuple[str, str]] = [
    (r"\bcannot\b", "can"),
    (r"\bcan\b", "cannot"),
    (r"\bis\b", "is not"),
    (r"\bare\b", "are not"),
    (r"\bwas\b", "was not"),
    (r"\bwere\b", "were not"),
    (r"\bshall\b", "shall not"),
    (r"\bmust\b", "need not"),
    (r"\bmay\b", "may not"),
    (r"\bwould\b", "would not"),
    (r"\bhas to\b", "does not have to"),
    (r"\bhave to\b", "do not have to"),
    (r"\bdoes\b", "does not"),
    (r"\bdo\b", "do not"),
]


def negate(sentence: str) -> str | None:
    """The same sentence asserting the opposite, or None where no site can be found.

    Deliberately crude. It is not a paraphrase and does not need to read well: it stands in for what
    an advocate on the other side asserts, and the only property that matters is that a reader would
    agree the two sentences cannot both be right.

    Sentences with no auxiliary to work on are dropped rather than mangled, which is why an item set
    is always smaller than the draw it came from.
    """
    for pattern, replacement in NEGATIONS:
        if re.search(pattern, sentence, flags=re.IGNORECASE):
            return re.sub(pattern, replacement, sentence, count=1, flags=re.IGNORECASE)
    for pattern, replacement in AFFIRMATIONS:
        if re.search(pattern, sentence, flags=re.IGNORECASE):
            return re.sub(pattern, replacement, sentence, count=1, flags=re.IGNORECASE)
    return None


@dataclass
class ContraryItem:
    """One holding, and the two propositions built from it."""

    judgment_key: str
    paragraph_label: str
    holding: str
    query: str
    kind: str


@dataclass
class ContraryOutcome:
    """What the engine answered for one of them."""

    item: ContraryItem
    leads: int
    source_retrieved: bool
    source_rank: int | None
    top_key: str | None
    top_sentence: str | None
    paragraphs_examined: int
    seconds: float
    # Filled only by `read_pairs`, which is the model half and runs over the source paragraph rather
    # than over what the search found.
    reading: str | None = None
    reading_grounded: bool = False
    reading_expected: str | None = None

    @property
    def source_flagged(self) -> bool:
        return self.source_rank is not None


@dataclass
class ContraryEvalReport:
    outcomes: list[ContraryOutcome] = field(default_factory=list)
    judgments: int = 0
    corpus_size: int = 0
    rule_like: bool = True
    read_by_model: bool = False

    def of(self, kind: str) -> list[ContraryOutcome]:
        return [o for o in self.outcomes if o.item.kind == kind]

    def pairs(self) -> list[tuple[ContraryOutcome, ContraryOutcome]]:
        """The two runs of each holding, side by side. Only holdings that produced both."""
        agreed = {(o.item.judgment_key, o.item.paragraph_label): o for o in self.of(AGREED)}
        out = []
        for opposed in self.of(OPPOSED):
            key = (opposed.item.judgment_key, opposed.item.paragraph_label)
            if key in agreed:
                out.append((opposed, agreed[key]))
        return out


def build_items(
    session: Session,
    *,
    judgments: int = 40,
    per_judgment: int = 1,
    seed_value: int = 20260904,
    rule_like: bool = True,
) -> list[ContraryItem]:
    """Draw holdings from the corpus and build the opposed and agreed propositions from each.

    The same draw as `evaluation.retrieval` and `evaluation.gate` when given the same seed, so the
    three sit over the same judgments and can be read together.

    `rule_like` keeps only sentences that state law rather than decide a case. Without it the draw
    contains "the appellant shall deposit the compensation within four weeks", "the chemical name for
    charas and hashish is extracts and tinctures of cannabis" and every disposition in the corpus --
    sentences nobody argues, whose negations nobody argues either, and against which any contrary
    search is measuring its behaviour on inputs it will never see. The filter is `RECORD_BOUND`, the
    same one the engine applies to candidate sentences, and it is applied to the *proposition* here
    for the same reason rather than a different one: a sentence about who won is not a proposition of
    law. It does not touch polarity, which is what the report measures.
    """
    rng = random.Random(seed_value)
    pool = list(
        session.scalars(
            select(Judgment)
            .join(JudgmentTextVersion, JudgmentTextVersion.judgment_id == Judgment.id)
            .order_by(Judgment.decided_on.desc())
        ).all()
    )
    rng.shuffle(pool)

    items: list[ContraryItem] = []
    used = 0
    for judgment in pool:
        if used >= judgments:
            break
        seed = collect_seed(session, judgment)
        if seed is None or not seed.court_sentences:
            continue
        drawn = 0
        for label, sentence in rng.sample(seed.court_sentences, len(seed.court_sentences)):
            if drawn >= per_judgment:
                break
            if rule_like and RECORD_BOUND.search(sentence):
                continue
            opposite = negate(sentence)
            if opposite is None:
                continue
            drawn += 1
            items.append(ContraryItem(judgment.canonical_key, label, sentence, opposite, OPPOSED))
            items.append(ContraryItem(judgment.canonical_key, label, sentence, sentence, AGREED))
        if drawn:
            used += 1
    return items


def run_item(session: Session, item: ContraryItem, *, top: int = 5) -> ContraryOutcome:
    """Put one proposition to the engine and record what came back about its own paragraph."""
    started = time.monotonic()
    retrieved = False

    def watch(candidate) -> None:
        # Whether the source paragraph was retrieved at all, whatever the polarity test then said.
        # Kept apart from `source_flagged` because a miss here is a fact about BM25 over four hundred
        # thousand paragraphs and a miss there is a fact about the opposition test.
        nonlocal retrieved
        if (
            candidate.canonical_key == item.judgment_key
            and str(candidate.paragraph_label) == item.paragraph_label
        ):
            retrieved = True

    report: ContraryReport = find_contrary(session, item.query, top=top, on_candidate=watch)
    seconds = time.monotonic() - started

    rank = next(
        (
            index
            for index, lead in enumerate(report.leads, start=1)
            if lead.authority.canonical_key == item.judgment_key
            and str(lead.authority.paragraph_label) == item.paragraph_label
        ),
        None,
    )
    return ContraryOutcome(
        item=item,
        leads=len(report.leads),
        source_retrieved=retrieved,
        source_rank=rank,
        top_key=report.leads[0].authority.canonical_key if report.leads else None,
        top_sentence=report.leads[0].sentence if report.leads else None,
        paragraphs_examined=report.paragraphs_examined,
        seconds=round(seconds, 2),
    )


def run_contrary(
    session: Session,
    items: list[ContraryItem],
    *,
    top: int = 5,
    rule_like: bool = True,
    on_item=None,
) -> ContraryEvalReport:
    from orderorder.engine.citator import corpus_size

    report = ContraryEvalReport(
        judgments=len({item.judgment_key for item in items}),
        corpus_size=corpus_size(session),
        rule_like=rule_like,
    )
    for index, item in enumerate(items, start=1):
        report.outcomes.append(run_item(session, item, top=top))
        if on_item is not None:
            on_item(index, len(items))
    return report


def source_lead(session: Session, item: ContraryItem) -> ContraryLead | None:
    """The paragraph the holding was lifted from, as a lead, so a model can be asked about it.

    No search is involved. The pair is known: this sentence, that paragraph, and a proposition that
    is either the sentence negated or the sentence itself.
    """
    row = session.execute(
        select(Paragraph, Judgment)
        .join(JudgmentTextVersion, Paragraph.text_version_id == JudgmentTextVersion.id)
        .join(Judgment, JudgmentTextVersion.judgment_id == Judgment.id)
        .where(
            Judgment.canonical_key == item.judgment_key,
            Paragraph.printed_label == item.paragraph_label,
            JudgmentTextVersion.preferred.is_(True),
        )
    ).first()
    if row is None:
        return None
    paragraph, judgment = row
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
    )
    start = paragraph.body.find(item.holding[:60])
    return ContraryLead(
        authority=authority,
        sentence=item.holding,
        sentence_start=max(0, start),
        sentence_end=max(0, start) + len(item.holding),
        opposition=Opposition(
            kind="known",
            cue="the item was built from this paragraph",
            shared_terms=(),
            proposition_clause=item.query,
            sentence_clause=item.holding,
        ),
    )


def read_pairs(
    session: Session, report: ContraryEvalReport, model: StructuredModel, *, limit: int = 20, on_item=None
) -> None:
    """Put the same two texts to the model twice, differing only in the proposition's polarity.

    This is the measurement that says whether a second reading is worth having, and it is built the
    way it is because of what happened to `engine.challenge`: a model that answers the prompt's lean
    rather than the texts scores well on positives alone. Here the positive and the negative control
    are the *same paragraph and the same sentence*. Only the proposition changes, by one word, and
    the correct answers are opposite and same. A model that says `opposite` to both has told us
    nothing except that it agrees with whoever is asking.
    """
    done = 0
    for opposed, agreed in report.pairs():
        if done >= limit:
            break
        for outcome, expected in ((opposed, OPPOSITE), (agreed, SAME)):
            lead = source_lead(session, outcome.item)
            if lead is None:
                continue
            reading = assess_opposition(outcome.item.query, lead, model)
            outcome.reading = reading.relation
            outcome.reading_grounded = reading.grounded
            outcome.reading_expected = expected
        done += 1
        if on_item is not None:
            on_item(done, min(limit, len(report.pairs())))
    report.read_by_model = True


def format_reading(report: ContraryEvalReport) -> list[str]:
    """What the model made of the pairs, positives and controls counted together."""
    read = [o for o in report.outcomes if o.reading is not None]
    if not read:
        return []
    lines = [
        "",
        "The second reading, over the same paragraph and the same sentence, with only the",
        "proposition's polarity changed. The correct answers are `opposite` for the negated",
        "proposition and `same` for the court's own words.",
        "",
        f"  {'proposition':<24}{'n':>4}{'opposite':>10}{'narrower':>10}{'same':>8}"
        f"{'unrelated':>11}{'unread':>8}{'grounded':>10}",
    ]
    for kind in KINDS:
        outcomes = [o for o in report.of(kind) if o.reading is not None]
        if not outcomes:
            continue
        n = len(outcomes)
        counts = {
            relation: sum(1 for o in outcomes if o.reading == relation)
            for relation in (OPPOSITE, NARROWER, SAME, UNRELATED, UNREAD)
        }
        lines.append(
            f"  {KIND_NAMES[kind]:<24}{n:>4}"
            f"{counts[OPPOSITE]:>10}{counts[NARROWER]:>10}{counts[SAME]:>8}"
            f"{counts[UNRELATED]:>11}{counts[UNREAD]:>8}"
            f"{sum(1 for o in outcomes if o.reading_grounded):>10}"
        )

    correct = sum(1 for o in read if o.reading == o.reading_expected)
    agreed_opposite = sum(1 for o in report.of(AGREED) if o.reading == OPPOSITE)
    lines += [
        "",
        f"{correct} of {len(read)} answers were the expected one.",
        f"{agreed_opposite} of the {len(report.of(AGREED))} controls -- where the proposition is the",
        "sentence itself -- came back as `opposite`. That is the number to read first. A model that",
        "calls a sentence the opposite of a proposition copied out of it is answering the question it",
        "was asked to look for rather than the two texts in front of it, and no positive score it",
        "produces means anything.",
    ]
    return lines


def format_contrary(report: ContraryEvalReport) -> list[str]:
    """The report, as lines. Two tables and a sentence saying what the first one is not."""
    pairs = report.pairs()
    lines = [
        f"{len(report.outcomes)} searches over {report.corpus_size:,} judgments, "
        f"{len(pairs)} holdings put both ways",
        "",
        "Each holding is a sentence a court wrote. It is put to the engine twice: negated, which is",
        "what the other side argues, and as written, which is what the side relying on it argues.",
        (
            "Only sentences that state law were drawn; the ones that decide a case are left out."
            if report.rule_like
            else "Every court sentence was drawn, including the ones that decide a case rather than"
            " state law."
        ),
        "",
        f"  {'proposition':<24}{'n':>4}{'source in field':>17}{'source flagged':>16}{'leads':>8}"
        f"{'seconds':>9}",
    ]
    for kind in KINDS:
        outcomes = report.of(kind)
        if not outcomes:
            continue
        n = len(outcomes)
        lines.append(
            f"  {KIND_NAMES[kind]:<24}{n:>4}"
            f"{sum(1 for o in outcomes if o.source_retrieved) / n:>16.0%}"
            f"{sum(1 for o in outcomes if o.source_flagged) / n:>16.0%}"
            f"{sum(o.leads for o in outcomes) / n:>8.1f}"
            f"{sum(o.seconds for o in outcomes) / n:>9.1f}"
        )

    lines += [
        "",
        "The `source flagged` column on the first row is not a finding. The negation that built the",
        "proposition and the negation the detector reads are the same idea, so a high number there is",
        "a property of the construction. It is reported because a low one would mean something broke.",
        "",
        "What the two rows *do* measure is discrimination, which is the whole question: the same",
        "paragraph, the same retrieval, and the only difference is the polarity of the sentence put to",
        "it. A tool that answered the same way to both would be reading the words and not the sense.",
        "",
    ]

    if pairs:
        both = sum(1 for opposed, agreed in pairs if opposed.source_flagged and agreed.source_flagged)
        only = sum(1 for opposed, agreed in pairs if opposed.source_flagged and not agreed.source_flagged)
        neither = sum(
            1 for opposed, agreed in pairs if not opposed.source_flagged and not agreed.source_flagged
        )
        inverted = sum(
            1 for opposed, agreed in pairs if not opposed.source_flagged and agreed.source_flagged
        )
        lines += [
            f"  {'the source paragraph was called contrary ...':<52}",
            f"    for the negated proposition only                {only:>4} of {len(pairs)}",
            f"    for both                                        {both:>4}",
            f"    for neither                                     {neither:>4}",
            f"    for the court's own words only                  {inverted:>4}",
            "",
        ]

    agreed = report.of(AGREED)
    if agreed:
        noisy = [o for o in agreed if o.leads]
        lines += [
            f"The floor: {len(noisy)} of {len(agreed)} propositions that are a court's own holding came",
            f"back with a contrary lead from some other judgment, {sum(o.leads for o in agreed) / len(agreed):.1f}",
            "per proposition. Some of those are real, because courts disagree and this corpus holds",
            "nine thousand of them, so the number is an upper bound on what is wrong rather than a",
            "count of what is wrong. It is also what a user feels: passages to read for a proposition",
            "that was never in doubt.",
        ]
    return lines


def format_examples(report: ContraryEvalReport, limit: int = 8) -> list[str]:
    """What came back for the court's own words, which is where the false leads are."""
    lines = [
        "leads returned for a proposition the court itself stated",
        "  (several of these answer a sentence that is not a proposition of law at all -- a",
        "   disposition, a chemical name, an order about a booster pump. Propositions drawn from",
        "   arbitrary court sentences are part of why the floor above is an upper bound.)",
    ]
    shown = 0
    for outcome in report.of(AGREED):
        if not outcome.leads or shown >= limit:
            continue
        shown += 1
        lines.append(f"  {outcome.item.judgment_key} para {outcome.item.paragraph_label}")
        lines.append(f"    held    {outcome.item.holding[:150]}")
        lines.append(f"    lead    {(outcome.top_sentence or '')[:150]}")
        lines.append(f"    from    {outcome.top_key}")
    if shown == 0:
        lines.append("  none: no proposition stated by a court drew a contrary lead")
    return lines


def write_report(report: ContraryEvalReport, path: Path, *, examples: bool = True) -> None:
    lines = format_contrary(report) + format_reading(report)
    if examples:
        lines += ["", *format_examples(report)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
