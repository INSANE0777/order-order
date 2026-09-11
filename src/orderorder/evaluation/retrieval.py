"""Measure the search direction: a proposition in, a judgment and a line out.

The verification eval asks whether the engine catches a bad citation. This asks the question a lawyer
preparing an argument actually starts from — *which* Supreme Court judgment says this, and *where* in
it — and it has never been measured. Recall on planted errors says nothing about it: an engine can be
perfect at rejecting bad citations and useless at finding good ones.

Ground truth comes the same way the gold set's does, by construction. Take a sentence the court itself
wrote, in a paragraph whose number is unambiguous and part of the court's own sequence, and the answer
is known before the search runs: that judgment, that paragraph, that line.

Three numbers, and they answer three different questions.

**Judgment recall** — is the right case in the top few at all. This is the question a lawyer asks
first, and the one a plain text search over the corpus would also answer.

**Paragraph recall** — is the right *paragraph* there. A judgment runs to three hundred pages and an
advocate cannot read it to check; a citation is only usable if it pinpoints.

**Line accuracy** — of the times the right paragraph came back, how often the sentence named as the
line is the one the proposition came from. This is the specific promise: not a document, not even a
paragraph, but the line to put in the brief.

Queries come in two shapes, and the difference between their scores is the interesting part:

  * **verbatim** — the sentence as the court wrote it. Someone who has the passage and wants the
    citation for it. If this is not near perfect, something is broken.
  * **fragment** — a run of words from the middle, which is what remembering a line is like. Harder,
    and closer to how the question actually arrives.

  * **paraphrase** — the proposition restated in an advocate's own words, sharing only the idea.
    This is the hardest shape and the one a lawyer actually types, and it cannot be built from the
    judgment's text: something has to do the restating. A model does it, cached to a file so the
    measurement repeats without one.

Using a model to write those queries does not make the measurement circular. The model is not what is
being measured — the retrieval is lexical and has never seen a model's output — and its job here is
the one job it is reliably good at, which is saying the same thing differently. What it does mean is
that the paraphrase score is against *a* set of paraphrases rather than the ones lawyers write, and
the queries are kept in the repository so anyone can read them and disagree.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.db.models import Judgment, JudgmentTextVersion
from orderorder.engine.prompts import RESTATE_PROMPT
from orderorder.engine.providers import StructuredModel
from orderorder.engine.quotes import longest_shared_run, normalized
from orderorder.engine.schemas import Restatement
from orderorder.engine.search import find_authorities
from orderorder.evaluation.generate import collect_seed

VERBATIM = "verbatim"
FRAGMENT = "fragment"
PARAPHRASE = "paraphrase"

# How many consecutive words a fragment query keeps. Long enough to be a distinctive phrase, short
# enough that most of the sentence is missing.
FRAGMENT_WORDS = 12
# How many of those have to be ordinary words rather than case numbers and party labels.
MIN_READABLE_WORDS = 8


@dataclass
class RetrievalItem:
    """One proposition whose source in the corpus is known before the search runs."""

    judgment_key: str
    paragraph_label: str
    sentence: str
    query: str
    kind: str


@dataclass
class Outcome:
    """Where the right answer came in the ranking, if it came at all."""

    item: RetrievalItem
    judgment_rank: int | None
    paragraph_rank: int | None
    line_matched: bool
    top_answer: str | None
    seconds: float


def _fragment(sentence: str) -> str | None:
    """A run of words from the middle of the sentence: what half-remembering a line looks like.

    Windows are taken from the middle outwards, and one made mostly of case numbers and party labels
    — "(A2, A4, A 7, AS, and A 11)" — is skipped. Not because it is hard, but because it is not a
    thing anyone would search for, and a benchmark should be hard for the reasons the real task is.
    The window is never chosen for how well it retrieves; the first readable one wins.
    """
    words = sentence.split()
    if len(words) < FRAGMENT_WORDS + 4:
        return None
    middle = (len(words) - FRAGMENT_WORDS) // 2
    for offset in range(0, len(words) - FRAGMENT_WORDS + 1):
        for start in {middle - offset, middle + offset}:
            if not 0 <= start <= len(words) - FRAGMENT_WORDS:
                continue
            window = words[start : start + FRAGMENT_WORDS]
            readable = sum(1 for w in window if len(w.strip(".,;:()[]")) >= 3 and w.strip(".,;:()[]").isalpha())
            if readable >= MIN_READABLE_WORDS:
                return " ".join(window)
    return None


def build_items(
    session: Session, *, judgments: int = 40, per_judgment: int = 2, seed_value: int = 20260904
) -> list[RetrievalItem]:
    """Draw propositions from the corpus whose home paragraph is known."""
    rng = random.Random(seed_value)
    pool = list(
        session.scalars(
            select(Judgment)
            .join(JudgmentTextVersion, JudgmentTextVersion.judgment_id == Judgment.id)
            .order_by(Judgment.decided_on.desc())
        ).all()
    )
    rng.shuffle(pool)

    items: list[RetrievalItem] = []
    used = 0
    for judgment in pool:
        if used >= judgments:
            break
        seed = collect_seed(session, judgment)
        if seed is None or len(seed.court_sentences) < per_judgment:
            continue
        used += 1
        for label, sentence in rng.sample(seed.court_sentences, per_judgment):
            items.append(
                RetrievalItem(judgment.canonical_key, label, sentence, sentence, VERBATIM)
            )
            fragment = _fragment(sentence)
            if fragment:
                items.append(
                    RetrievalItem(judgment.canonical_key, label, sentence, fragment, FRAGMENT)
                )
    return items


def run_item(session: Session, item: RetrievalItem, *, top: int = 10, dense: bool = False, role_boost: bool = False) -> Outcome:
    """Search for one proposition and record where its own paragraph came in the ranking."""
    started = time.monotonic()
    # `one_per_judgment` is off: paragraph recall cannot be measured when the search returns one
    # paragraph per case, and the pinpoint is the part that matters.
    found = find_authorities(
        session, item.query, top=top, one_per_judgment=False, check_treatment=False, dense=dense, role_boost=role_boost
    )
    seconds = time.monotonic() - started

    judgment_rank = next(
        (i for i, a in enumerate(found, start=1) if a.canonical_key == item.judgment_key), None
    )
    paragraph_rank = next(
        (
            i
            for i, a in enumerate(found, start=1)
            if a.canonical_key == item.judgment_key and a.paragraph_label == item.paragraph_label
        ),
        None,
    )
    line_matched = False
    if paragraph_rank is not None:
        hit = found[paragraph_rank - 1]
        # The same sentence, not merely an overlapping one: both come from the same splitter over the
        # same paragraph, so anything short of equality means a different line was named.
        line_matched = bool(hit.line) and normalized(hit.line) == normalized(item.sentence)
    return Outcome(
        item=item,
        judgment_rank=judgment_rank,
        paragraph_rank=paragraph_rank,
        line_matched=line_matched,
        top_answer=found[0].pinpoint if found else None,
        seconds=seconds,
    )


@dataclass
class RetrievalReport:
    outcomes: list[Outcome] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Outcome]:
        return [o for o in self.outcomes if o.item.kind == kind]

    @staticmethod
    def _recall(outcomes: list[Outcome], rank: str, k: int) -> float | None:
        if not outcomes:
            return None
        hits = sum(1 for o in outcomes if (getattr(o, rank) or 10**6) <= k)
        return hits / len(outcomes)

    def judgment_recall(self, kind: str, k: int) -> float | None:
        return self._recall(self.of_kind(kind), "judgment_rank", k)

    def paragraph_recall(self, kind: str, k: int) -> float | None:
        return self._recall(self.of_kind(kind), "paragraph_rank", k)

    def line_accuracy(self, kind: str) -> float | None:
        """Of the searches that found the right paragraph, how many named the right line in it."""
        found = [o for o in self.of_kind(kind) if o.paragraph_rank is not None]
        if not found:
            return None
        return sum(1 for o in found if o.line_matched) / len(found)

    def seconds_per_query(self) -> float:
        timed = [o.seconds for o in self.outcomes if o.seconds]
        return sum(timed) / len(timed) if timed else 0.0


def run_retrieval(
    session: Session, items: list[RetrievalItem], *, top: int = 10, dense: bool = False, role_boost: bool = False, on_result=None
) -> RetrievalReport:
    report = RetrievalReport()
    for index, item in enumerate(items, start=1):
        outcome = run_item(session, item, top=top, dense=dense, role_boost=role_boost)
        report.outcomes.append(outcome)
        if on_result is not None:
            on_result(outcome, index, len(items))
    return report


def format_retrieval(report: RetrievalReport, *, top: int = 10) -> list[str]:
    lines = [f"{len(report.outcomes)} queries over the corpus", ""]
    header = f"{'':<10}{'case @1':>9}{'case @5':>9}{f'case @{top}':>9}{'para @5':>9}{'line':>9}"
    lines.append(header)
    for kind in (VERBATIM, FRAGMENT, PARAPHRASE):
        if not report.of_kind(kind):
            continue

        def cell(value: float | None) -> str:
            return "  -" if value is None else f"{value:8.0%}"

        lines.append(
            f"{kind:<10}"
            + cell(report.judgment_recall(kind, 1))
            + cell(report.judgment_recall(kind, 5))
            + cell(report.judgment_recall(kind, top))
            + cell(report.paragraph_recall(kind, 5))
            + cell(report.line_accuracy(kind))
        )
    lines.append("")
    lines.append(f"seconds per query: {report.seconds_per_query():.2f}")
    return lines


def format_misses(report: RetrievalReport, limit: int = 12) -> list[str]:
    """The searches that did not find their own paragraph, with what came back instead."""
    lines = ["misses"]
    for outcome in report.outcomes:
        if outcome.paragraph_rank is not None:
            continue
        item = outcome.item
        lines.append(f"  [{item.kind}] {item.judgment_key} para {item.paragraph_label}")
        lines.append(f"    query  {item.query[:140]}")
        lines.append(f"    case   {'found at ' + str(outcome.judgment_rank) if outcome.judgment_rank else 'not found'}")
        lines.append(f"    top    {outcome.top_answer or '-'}")
        if len(lines) > limit * 4:
            break
    if len(lines) == 1:
        lines.append("  none: every proposition found its own paragraph")
    return lines


def write_items(items: list[RetrievalItem], path: Path) -> int:
    """Keep a query set as JSON Lines, so a run repeats without a model and anyone can read them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
    return len(items)


def read_items(path: Path) -> list[RetrievalItem]:
    if not path.exists():
        return []
    return [
        RetrievalItem(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def restate(sentence: str, model: StructuredModel) -> str | None:
    """Ask for the same proposition in different words. Returns None if nothing usable came back.

    A restatement that keeps a long run of the original is not a restatement, and letting one through
    would flatter the paraphrase score with a query that is really a quotation. Ten consecutive words
    is the same bar the pinpoint check uses for "not a coincidence".
    """
    try:
        answer = model.invoke(RESTATE_PROMPT.format(sentence=sentence.strip()))
    except Exception:  # noqa: BLE001 - one refusal must not end the run
        return None
    if not isinstance(answer, Restatement) or not answer.restatement.strip():
        return None
    text = answer.restatement.strip()
    if longest_shared_run(text, sentence).is_distinctive:
        return None
    return text


def build_paraphrases(
    session: Session,
    model: StructuredModel,
    *,
    judgments: int = 40,
    per_judgment: int = 2,
    seed_value: int = 20260904,
    on_result=None,
) -> list[RetrievalItem]:
    """Draw the same propositions as `build_items` and have each one restated.

    The same draw, so the paraphrase score sits beside the verbatim and fragment scores over the same
    propositions and the three can be compared. A sentence the model declines to restate, or restates
    by copying, is dropped rather than replaced: a smaller set honestly built beats a full one.
    """
    verbatim = [
        item
        for item in build_items(
            session, judgments=judgments, per_judgment=per_judgment, seed_value=seed_value
        )
        if item.kind == VERBATIM
    ]
    items: list[RetrievalItem] = []
    for index, item in enumerate(verbatim, start=1):
        restatement = restate(item.sentence, model)
        if on_result is not None:
            on_result(item, index, len(verbatim))
        if restatement:
            items.append(
                RetrievalItem(
                    item.judgment_key, item.paragraph_label, item.sentence, restatement, PARAPHRASE
                )
            )
    return items
