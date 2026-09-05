"""Build a gold set by planting known errors in real judgments.

`docs/ARCHITECTURE.md` section 11.1 sets out the method: start from a real judgment and a true,
quote-grounded proposition taken from it, then derive one item per failure mode — alter the citation
string, attribute it to the wrong court, lift a sentence from counsel's argument, shift the pinpoint,
and so on.

Two properties make this worth having before the co-founder's hand-labelled set arrives, rather than
instead of it.

**The label is known by construction.** The item is built by taking a sentence from a paragraph the
engine's own voice check calls counsel's argument, so "this is failure mode 5" is not a judgment call
made afterwards; it is how the item was made. The same machinery that will be graded picks the
paragraph, which sounds circular and is not: the grading asks whether the *verdict* names mode 5, and
a paragraph correctly identified as counsel's argument at generation time can still be missed by the
verdict path, misgraded, or drowned in other findings.

**Clean items come free.** Every seed judgment also yields a sound citation — the court's own words,
correctly pinpointed, correctly attributed. Those measure false positives, which no amount of planted
error can, and which decide whether the verdict board is worth reading at all.

What this cannot produce is the natural distribution of mistakes real advocates make. Planted errors
are the ones we thought of. That is what the memorials are for.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.db.models import CitationAlias, Judgment, JudgmentTextVersion
from orderorder.engine.citator import NEGATIVE, CitationEdge, treatment_of
from orderorder.engine.locator import Candidate
from orderorder.engine.sentences import split_sentences
from orderorder.engine.voice import attribute_voice
from orderorder.engine.weight import DECLINING_CUES
from orderorder.evaluation.gold import GoldItem, GoldLabels
from orderorder.ingest.store import load_paragraphs

# A sentence has to be substantial enough to be a proposition a brief would actually make.
MIN_SENTENCE_WORDS = 12
MAX_SENTENCE_WORDS = 60

# Qualifiers a court attaches and a brief drops. Truncating here is failure mode 9, and the claim that
# survives the truncation is failure mode 8.
QUALIFIER = re.compile(
    r"(?i)\b(only\s+(?:where|when|if)|unless|provided\s+that|subject\s+to|except\s+where|"
    r"so\s+long\s+as|in\s+the\s+facts\s+of|having\s+regard\s+to)\b"
)


@dataclass
class Seed:
    """One judgment with the paragraphs a generator can draw on."""

    judgment: Judgment
    citation: str
    court_sentences: list[tuple[str, str]]  # (paragraph label, sentence)
    counsel_sentences: list[tuple[str, str]]
    obiter_sentences: list[tuple[str, str]]
    dissent_sentences: list[tuple[str, str]]
    qualified_sentences: list[tuple[str, str]]
    labels: list[str]


def _usable(sentence: str) -> bool:
    words = sentence.split()
    if not (MIN_SENTENCE_WORDS <= len(words) <= MAX_SENTENCE_WORDS):
        return False
    # Page furniture, tables of authorities and citation runs are not propositions.
    if sentence.count("(") > 3 or sum(c.isdigit() for c in sentence) > len(sentence) * 0.12:
        return False
    return bool(re.match(r"^[A-Z“\"']", sentence.strip()))


def collect_seed(session: Session, judgment: Judgment) -> Seed | None:
    """Read one judgment and sort its sentences by whose words they are."""
    paragraphs = load_paragraphs(session, judgment.id)
    if len(paragraphs) < 6:
        return None
    alias = session.scalars(
        select(CitationAlias)
        .where(CitationAlias.judgment_id == judgment.id)
        .order_by(CitationAlias.reporter)
    ).first()
    if alias is None:
        return None

    seed = Seed(judgment, alias.citation_string, [], [], [], [], [], [])
    for paragraph in paragraphs:
        if not paragraph.printed_label:
            continue
        seed.labels.append(paragraph.printed_label)
        candidate = Candidate(
            seq=paragraph.seq,
            printed_label=paragraph.printed_label,
            score=0.0,
            matched_terms=[],
            body=paragraph.body,
            opinion_kind=paragraph.opinion_kind,
            opinion_author=paragraph.opinion_author,
        )
        voice = attribute_voice(candidate)
        declining = bool(DECLINING_CUES.search(paragraph.body))

        for sentence, _offset in split_sentences(paragraph.body):
            if not _usable(sentence):
                continue
            entry = (paragraph.printed_label, sentence)
            if voice.voice == "counsel_argument":
                seed.counsel_sentences.append(entry)
            elif voice.is_dissent:
                seed.dissent_sentences.append(entry)
            elif voice.is_the_court:
                if declining:
                    seed.obiter_sentences.append(entry)
                else:
                    seed.court_sentences.append(entry)
                    if QUALIFIER.search(sentence):
                        seed.qualified_sentences.append(entry)
    return seed if seed.court_sentences else None


def _shifted(labels: list[str], label: str, by: int = 7) -> str:
    """A pinpoint several paragraphs away from the right one, or past the end of the judgment."""
    numeric = [x for x in labels if x.isdigit()]
    if label in numeric:
        moved = int(label) + by
        return str(moved)
    return str(by * 10)


def _altered(citation: str) -> str:
    """The same case with the volume and page wrong: right name, wrong numbers."""

    def bump(match: re.Match[str]) -> str:
        return str(int(match.group(0)) + 3)

    return re.sub(r"\d+", bump, citation, count=2)


def plant(seed: Seed, session: Session, rng: random.Random, overruled: list[tuple[str, str]]) -> list[GoldItem]:
    """Derive one item per failure mode the seed can support, plus a clean one."""
    key = seed.judgment.canonical_key
    items: list[GoldItem] = []

    def add(
        suffix: str,
        claim: str,
        citation: str,
        mode: int | None,
        note: str,
        *,
        paragraph: str | None = None,
        voice: str | None = None,
    ) -> None:
        items.append(
            GoldItem(
                id=f"{key}-{suffix}",
                claim_text=claim,
                citation_raw=citation,
                planted_error=mode,
                notes=note,
                labels=GoldLabels(
                    exists=mode != 1,
                    judgment_key=None if mode == 1 else key,
                    paragraph_label=paragraph,
                    voice=voice,
                ),
            )
        )

    label, sentence = rng.choice(seed.court_sentences)
    pinpoint = f"{seed.citation}, para {label}"

    # Clean. The court's own words, correctly pinpointed. Any finding here is a false positive.
    add("clean", sentence, pinpoint, None, "the court's own holding, correctly cited",
        paragraph=label, voice="court_majority")

    # 1 — phantom. A citation shaped like a real one that resolves to nothing.
    add("m1", sentence, f"({2000 + rng.randint(0, 24)}) {rng.randint(11, 19)} SCC {rng.randint(4000, 9000)}",
        1, "invented citation, resolves nowhere")

    # 2 — mis-cite. Right case by name, wrong numbers.
    add("m2", sentence, f"{seed.judgment.title.split(' versus ')[0].title()} v. Anr., {_altered(seed.citation)}",
        2, "party names right, reporter numbers altered")

    # 3 — wrong bench. Only when the claim would actually overstate it.
    if (seed.judgment.bench_strength or 0) < 5:
        add("m3", f"A Constitution Bench of this Court held that {sentence[0].lower()}{sentence[1:]}",
            pinpoint, 3, f"claimed as a Constitution Bench; the judgment was decided by "
            f"{seed.judgment.bench_strength}", paragraph=label)

    # 5 — wrong voice. A submission of counsel, offered as the holding.
    if seed.counsel_sentences:
        counsel_label, counsel_sentence = rng.choice(seed.counsel_sentences)
        add("m5", counsel_sentence, f"{seed.citation}, para {counsel_label}", 5,
            "sentence taken from a paragraph reciting counsel's submission",
            paragraph=counsel_label, voice="counsel_argument")

    # 6 — dissent, where the judgment has one.
    if seed.dissent_sentences:
        dissent_label, dissent_sentence = rng.choice(seed.dissent_sentences)
        add("m6", dissent_sentence, f"{seed.citation}, para {dissent_label}", 6,
            "sentence taken from the dissenting opinion", paragraph=dissent_label,
            voice="court_dissent")

    # 7 — obiter, where the court said in terms that it was not deciding.
    if seed.obiter_sentences:
        obiter_label, obiter_sentence = rng.choice(seed.obiter_sentences)
        add("m7", obiter_sentence, f"{seed.citation}, para {obiter_label}", 7,
            "sentence from a paragraph where the court declined to decide", paragraph=obiter_label)

    # 8 and 9 — the qualifier dropped, and the sentence truncated before it.
    if seed.qualified_sentences:
        q_label, q_sentence = rng.choice(seed.qualified_sentences)
        match = QUALIFIER.search(q_sentence)
        if match and match.start() > 40:
            truncated = q_sentence[: match.start()].rstrip(" ,;")
            add("m9", truncated + ".", f"{seed.citation}, para {q_label}", 9,
                f"truncated before the qualifier {match.group(0)!r}", paragraph=q_label)

    # 12 — wrong pinpoint. Right case, right proposition, paragraph several away.
    add("m12", sentence, f"{seed.citation}, para {_shifted(seed.labels, label)}", 12,
        "pinpoint shifted away from the paragraph the words are in", paragraph=label)

    # 10 — dead law. Only where the citator actually knows of an overruling.
    if overruled:
        dead_key, dead_citation = rng.choice(overruled)
        dead = session.scalars(select(Judgment).where(Judgment.canonical_key == dead_key)).first()
        if dead is not None:
            dead_seed = collect_seed(session, dead)
            if dead_seed and dead_seed.court_sentences:
                dead_label, dead_sentence = rng.choice(dead_seed.court_sentences)
                items.append(
                    GoldItem(
                        id=f"{dead_key}-m10",
                        claim_text=dead_sentence,
                        citation_raw=f"{dead_citation}, para {dead_label}",
                        planted_error=10,
                        notes="a judgment the citator records as overruled",
                        labels=GoldLabels(exists=True, judgment_key=dead_key, paragraph_label=dead_label),
                    )
                )
    return items


def overruled_judgments(session: Session) -> list[tuple[str, str]]:
    """Judgments the citator records as negatively treated, with a citation for each."""
    rows = session.execute(
        select(CitationEdge.cited_id).where(CitationEdge.treatment.in_(NEGATIVE)).distinct()
    ).all()
    found: list[tuple[str, str]] = []
    for (cited_id,) in rows:
        if not cited_id:
            continue
        report = treatment_of(session, cited_id)
        if not report.is_doubtful:
            continue
        judgment = session.get(Judgment, cited_id)
        alias = session.scalars(
            select(CitationAlias).where(CitationAlias.judgment_id == cited_id)
        ).first()
        if judgment and alias:
            found.append((judgment.canonical_key, alias.citation_string))
    return found


def generate(session: Session, *, seeds: int = 8, seed_value: int = 20260904) -> list[GoldItem]:
    """Build a gold set from judgments the corpus holds text for."""
    rng = random.Random(seed_value)
    judgments = list(
        session.scalars(
            select(Judgment)
            .join(JudgmentTextVersion, JudgmentTextVersion.judgment_id == Judgment.id)
            .order_by(Judgment.decided_on.desc())
        ).all()
    )
    rng.shuffle(judgments)
    dead = overruled_judgments(session)

    items: list[GoldItem] = []
    used = 0
    for judgment in judgments:
        if used >= seeds:
            break
        collected = collect_seed(session, judgment)
        if collected is None:
            continue
        items.extend(plant(collected, session, rng, dead))
        used += 1

    # The same overruled judgment is drawn repeatedly; one item for it is enough.
    seen: set[str] = set()
    unique: list[GoldItem] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    return unique
