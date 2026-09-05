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
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.citations.grammar import extract_citations
from orderorder.db.models import CitationAlias, Judgment, JudgmentTextVersion
from orderorder.engine.citator import NEGATIVE, CitationEdge, treatment_of
from orderorder.engine.locator import Candidate
from orderorder.engine.sentences import split_sentences
from orderorder.engine.voice import attribute_voice
from orderorder.engine.weight import DECLINING_CUES
from orderorder.evaluation.gold import GoldItem, GoldLabels
from orderorder.ingest.segment import find_out_of_sequence
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

# Ways a judgment announces that a quotation follows. What comes after is the proposition; this is not.
LEAD_IN = re.compile(
    r"(?i)(?:as\s+under|as\s+follows|thus|to\s+the\s+following\s+effect|in\s+the\s+following\s+terms)"
    r"\s*[:.-]|(?::-|:)\s*$|\b(?:may\s+usefully\s+refer|it\s+is\s+profitable\s+to\s+(?:refer|quote)|"
    r"we\s+may\s+(?:quote|reproduce|extract))\b"
)
# "Pandurang and Ors. v. State of Hyderabad" — another case named inside the sentence.
PARTIES = re.compile(r"\b[A-Z][\w.&'()-]*(?:\s+[\w.&'()-]+){0,6}\s+(?:v\.|vs\.?|versus)\s+[A-Z]")


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
    stripped = sentence.strip()
    # A proposition is a whole sentence. Column-formatted reports extract into fragments — half a
    # table row, a line that stops mid-clause — and a fragment is not something an advocate would
    # assert. One such fragment reached the gold set as a *clean* item and was flagged, which reads
    # as a false positive by the engine and was nothing of the kind.
    if not stripped.endswith((".", "?", "!", '."', ".'", ".”", ".’")):
        return False
    if not re.match(r"^[A-Z“\"']", stripped):
        return False
    # A sentence that announces a quotation is not the proposition; the quotation is. Offered as one,
    # it carries the introduced case's bench and citation into a claim about a different case, and the
    # engine is right to object — "In paragraphs 365 and 366, the Constitution Bench of this Court has
    # held as under:-" asserts a Constitution Bench, whatever the judgment it was taken from.
    if LEAD_IN.search(sentence) or PARTIES.search(sentence):
        return False
    # Likewise a sentence naming another authority. The gold item pairs a claim with one citation, and
    # a second citation inside the claim makes it ambiguous which one the item is about. This is the
    # dearest check by a wide margin — the whole citation grammar over every sentence of every
    # paragraph — so it goes last, where most sentences have already been rejected.
    return not extract_citations(sentence)


def _first_citation(session: Session, judgment_id) -> str | None:
    """One citation for a judgment, chosen the same way every time so a run is reproducible."""
    alias = session.scalars(
        select(CitationAlias)
        .where(CitationAlias.judgment_id == judgment_id)
        .order_by(CitationAlias.reporter, CitationAlias.citation_string)
    ).first()
    return alias.citation_string if alias else None


def collect_seed(session: Session, judgment: Judgment) -> Seed | None:
    """Read one judgment and sort its sentences by whose words they are."""
    paragraphs = load_paragraphs(session, judgment.id)
    if len(paragraphs) < 6:
        return None
    citation = _first_citation(session, judgment.id)
    if citation is None:
        return None

    # A printed label is not unique: a judgment that quotes another carries that judgment's numbering
    # too. An item drawn from the second paragraph numbered 11 and cited as "para 11" points at the
    # first one, so it is not a sound citation whatever else is true of it — and as a *clean* item it
    # would score the engine down for saying so. Ground truth has to be unambiguous or it is not
    # ground truth.
    occurrences = Counter(p.printed_label for p in paragraphs if p.printed_label)

    # Paragraphs whose printed number is not part of the court's own numbering carry words from
    # somewhere else. The generator cannot assert that such a paragraph is the court's own holding,
    # so it does not draw items from them at all.
    #
    # Be clear about what this costs. It is the one place where the generator uses a detector's own
    # answer to decide what to label, and it means **the false positive rate below does not measure
    # the sequence-based half of failure mode 5**: those paragraphs never reach the gold set, so that
    # detector cannot be seen to fire on a clean item here. Every other detector is measured. Closing
    # this gap needs paragraphs whose provenance a person has read and confirmed, which is what the
    # hand-labelled memorials are for.
    quoted = find_out_of_sequence(paragraphs)

    seed = Seed(judgment, citation, [], [], [], [], [], [])
    for paragraph in paragraphs:
        if not paragraph.printed_label:
            continue
        seed.labels.append(paragraph.printed_label)
        if occurrences[paragraph.printed_label] > 1 or paragraph.seq in quoted:
            continue
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


# A sentence reciting the facts of somebody else's case: parties, dates, sums, procedural history.
# Real court text and useless as a planted proposition, because "this judgment does not say that" is
# obvious from the party names alone and the item would score a detector that never read the
# paragraph.
RECITAL = re.compile(
    r"\((?:[Aa]ppellant|[Rr]espondent|[Pp]etitioner|[Dd]efendant|[Pp]laintiff)s?\)"
    # Capitalised, a party word names *this case's* parties; in lower case it states a general rule
    # about parties, which is exactly the kind of sentence this item wants.
    r"|\b(?:Appellant|Respondent|Petitioner|Corporation|Board|Tribunal|Commission)s?\b"
    r"|\bM/s\b|\b\d{2}[-./]\d{2}[-./]\d{4}\b"
    r"|(?i:\bRs\.?\s*\d|\bin\s+the\s+(?:present|instant)\b|\bfactual\s+(?:set-?up|matrix)\b)"
    r"|(?i:\b(?:appellant|respondent|petitioner)\s+(?:herein|no\.?\s*\d))"
)


def _is_proposition(sentence: str) -> bool:
    """Whether a sentence states a rule rather than recounting what happened to somebody.

    Only used to pick the foreign sentence for the mode 4 item. A recital fails that item for the
    wrong reason -- no reader needs to check the paragraph to know this judgment is not about M/s
    somebody's contract of 2002 -- and an item that is failed for the wrong reason measures nothing.
    """
    return not RECITAL.search(sentence)


def _shifted(labels: list[str], label: str, by: int = 7) -> str:
    """A pinpoint several paragraphs away from the right one, or past the end of the judgment."""
    numeric = [x for x in labels if x.isdigit()]
    if label in numeric:
        moved = int(label) + by
        return str(moved)
    return str(by * 10)


def _party_name(title: str) -> str:
    """The first-named party, as a brief would write it."""
    head = re.split(r"(?i)\s+(?:versus|vs\.?|v\.)\s+", title)[0]
    head = re.sub(r"(?i)\s*(?:etc\.?|& ors\.?|and others|& anr\.?|and another)\s*$", "", head)
    return " ".join(word.capitalize() if word.isupper() else word for word in head.split())


def plant(
    seed: Seed,
    session: Session,
    rng: random.Random,
    overruled: list[tuple[str, str]],
    decoy: str | None = None,
    foreign: str | None = None,
) -> list[GoldItem]:
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
        treatment: str | None = None,
        support: str | None = None,
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
                    treatment=treatment,
                    support=support,
                ),
            )
        )

    label, sentence = rng.choice(seed.court_sentences)
    pinpoint = f"{seed.citation}, para {label}"

    # Clean. The court's own words, correctly pinpointed, in a judgment no later one has doubted —
    # that last part checked rather than assumed, because a citation to overruled law is not clean
    # however carefully it is pinpointed, and the citator would be right to say so.
    if not treatment_of(session, seed.judgment.id).is_doubtful:
        add("clean", sentence, pinpoint, None, "the court's own holding, correctly cited",
            paragraph=label, voice="court_majority", treatment="good_law")

    # 1 — phantom. A citation shaped like a real one that resolves to nothing.
    add("m1", sentence, f"({2000 + rng.randint(0, 24)}) {rng.randint(11, 19)} SCC {rng.randint(4000, 9000)}",
        1, "invented citation, resolves nowhere")

    # 2 — mis-cite. The case is named correctly and the reporter reference belongs to a different
    # case altogether. This is the shape that matters: bumping the numbers of a neutral citation
    # produces a reference that resolves nowhere, which is a phantom (mode 1) and not a mis-cite, and
    # an item labelled 2 that contains a 1 marks the engine down for being right.
    if decoy is not None:
        add("m2", sentence, f"{_party_name(seed.judgment.title)} v. Anr., {decoy}", 2,
            "party names are this case; the reporter reference belongs to another")

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

    # 4 — not there. A proposition another court stated, cited to this judgment at a paragraph this
    # judgment really has. Everything the model-free checks can see is correct: the case exists, the
    # citation resolves to it, the pinpoint is a real paragraph, the words in that paragraph are the
    # court's own and the judgment is good law. The only thing wrong is that the paragraph does not
    # say it, which cannot be established without reading the claim against the text.
    #
    # This mode and mode 8 are the two the gold set never planted, and they are the two a live run
    # of the drafting gate got wrong: a paragraph about what must be *decided* was bound to a claim
    # about who must be *joined*. Mode 8 is covered in substance by the m9 items, whose claim is the
    # court's sentence cut before its qualifier and which the verdict path reports as mode 8. Mode 4
    # had nothing at all, so a detector that never fired would have scored the same as one that
    # always did.
    if foreign:
        add("m4", foreign, pinpoint, 4,
            "a proposition from a different judgment, cited to this one at a real paragraph",
            paragraph=label, voice="court_majority", treatment="good_law", support="none")

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
    previous: Seed | None = None
    for judgment in judgments:
        if used >= seeds:
            break
        collected = collect_seed(session, judgment)
        if collected is None:
            continue
        # A real citation belonging to some other case, for the mis-cite item to point at.
        decoy = next(
            (
                other
                for judgment_id in (j.id for j in rng.sample(judgments, min(8, len(judgments))))
                if judgment_id != judgment.id
                for other in [_first_citation(session, judgment_id)]
                if other and other != collected.citation
            ),
            None,
        )
        # A sentence from a judgment that is not this one, for the mode 4 item. Drawn from the seed
        # built for the previous judgment, so it costs no extra reading and is guaranteed to be a
        # real court's real holding rather than something invented.
        foreign = None
        if previous is not None:
            stated = [x for _label, x in previous.court_sentences if _is_proposition(x)]
            if stated:
                foreign = rng.choice(stated)

        items.extend(plant(collected, session, rng, dead, decoy, foreign))
        previous = collected
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
