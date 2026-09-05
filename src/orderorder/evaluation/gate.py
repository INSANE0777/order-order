"""Measuring the drafting gate: what does it let through, and what does it throw out?

Both other directions of this engine have a number against them. The gate does not, and it is the
component with the most to lose by being wrong, because it is the one that *writes*. A verification
miss leaves a bad citation in somebody else's brief; a gate miss puts one in yours, over your
signature, with a pinpoint that makes it look checked.

The measurement has to avoid a trap. The gate refuses a passage that is not the court's own words,
and `engine.voice` is what decides that — so an evaluation that picks counsel's submissions using
`engine.voice` and then asks whether the gate refused them measures nothing at all. It would be a
detector grading itself.

So what is measured here is not the detector but the **traffic**: propositions are drawn from real
paragraphs of real judgments, they are put to the search the way an advocate would put them, and the
question is what comes back up the pipe.

  * Take a sentence a court actually wrote. The corpus contains it verbatim, so retrieval will find
    it. Does anything get bound?
  * Take a sentence from a paragraph reciting **counsel's submission**. It is not authority, and an
    advocate who searched for it would be offered it by any tool that ranks on words alone — a
    submission is stated without the qualifications a holding carries, so it matches a proposition's
    wording *better* than the holding does. How much of the raw lexical field is passages like that?
  * Same for a sentence from a **dissent**.

The filtering happens in two places and the report follows the chain. `engine.search` drops anything
that is not the court speaking before it ranks, and the gate in `engine.authority` refuses it again
on the way into a draft. So each item is retrieved **twice**: once unfiltered, which is what a plain
word search would return, and once as shipped. The difference between the two columns is the work the
filter does, stated per proposition rather than in principle.

Be clear about the one thing this cannot measure. The same `attribute_voice` that labels a paragraph
counsel's submission when the item is built is what drops it during retrieval, so "the filter removed
the paragraph we labelled" is true by construction and is not evidence the detector is right. What is
*not* circular is the size of the field it removes it from: how many paragraphs a word-matching
search puts within reach of a drafting tool, and how many of them are things nobody may cite. That
number is about the corpus and the retriever, and it is why the filter is not ceremony.

Two passes, because they cost different things. The retrieval pass needs no key. The end-to-end pass
runs `bind_proposition` exactly as the drafting surface does, and is the only part that needs a model.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.db.models import Judgment, JudgmentTextVersion
from orderorder.engine.authority import (
    BOUND,
    DEFAULT_CHECKED,
    NARROWED,
    REFUSED,
    UNCHECKED,
    _gate,
    bind_proposition,
)
from orderorder.engine.providers import StructuredModel
from orderorder.engine.search import find_authorities
from orderorder.evaluation.generate import collect_seed

HOLDING = "holding"
COUNSEL = "counsel"
DISSENT = "dissent"
# In the order they are reported, worst-consequence last.
KINDS = [HOLDING, COUNSEL, DISSENT]
KIND_NAMES = {
    HOLDING: "the court's own words",
    COUNSEL: "counsel's submission",
    DISSENT: "a dissenting opinion",
}
# How wide a field the model-free pass gates. The same number the drafting surface checks, so the
# traffic measured is the traffic the gate actually sees.
FIELD = DEFAULT_CHECKED


@dataclass
class GateItem:
    """One proposition, and the paragraph it was lifted from."""

    judgment_key: str
    paragraph_label: str
    proposition: str
    kind: str


@dataclass
class GateOutcome:
    """What one proposition met on the way through: the raw field, the filter, and the gate."""

    item: GateItem
    # What a plain word search would have returned.
    raw_candidates: int
    raw_not_the_court: int
    raw_source_rank: int | None
    # What actually reaches the gate.
    candidates: int
    source_survived: bool
    # What the gate then refused, over the field it did see.
    refused_not_the_court: int
    refused_doubtful: int
    source_refusal: str | None
    # The end-to-end pass, exactly as `orderorder draft` runs it.
    status: str
    chosen_key: str | None
    chosen_label: str | None
    seconds: float

    @property
    def bound_to_source(self) -> bool:
        return (
            self.status in {BOUND, NARROWED}
            and self.chosen_key == self.item.judgment_key
            and self.chosen_label == self.item.paragraph_label
        )


@dataclass
class GateReport:
    outcomes: list[GateOutcome] = field(default_factory=list)
    model_configured: bool = False
    judgments: int = 0

    def of(self, kind: str) -> list[GateOutcome]:
        return [o for o in self.outcomes if o.item.kind == kind]

    @property
    def false_binds(self) -> list[GateOutcome]:
        """Bound to a paragraph that was counsel's submission or a dissent. Should be empty."""
        return [o for o in self.outcomes if o.item.kind != HOLDING and o.bound_to_source]


def build_items(
    session: Session, *, judgments: int = 40, per_judgment: int = 1, seed_value: int = 20260904
) -> list[GateItem]:
    """Draw propositions of each kind from judgments the corpus holds text for.

    A judgment only contributes if it has a paragraph of each kind wanted, so the three rows of the
    report are drawn from the same judgments and cannot be compared across different corpora by
    accident.
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

    items: list[GateItem] = []
    used = 0
    for judgment in pool:
        if used >= judgments:
            break
        seed = collect_seed(session, judgment)
        if seed is None or not seed.court_sentences:
            continue
        drawn: list[GateItem] = []
        for kind, sentences in (
            (HOLDING, seed.court_sentences),
            (COUNSEL, seed.counsel_sentences),
            (DISSENT, seed.dissent_sentences),
        ):
            for label, sentence in rng.sample(sentences, min(per_judgment, len(sentences))):
                drawn.append(GateItem(judgment.canonical_key, label, sentence, kind))
        # A judgment with no counsel paragraph and no dissent contributes only a holding, which is
        # fine; one with nothing at all is not worth the retrieval.
        if len(drawn) > 1 or seed.court_sentences:
            used += 1
            items.extend(drawn)
    return items


def run_item(
    session: Session, item: GateItem, model: StructuredModel | None, *, checked: int = FIELD
) -> GateOutcome:
    """Put one proposition through the whole chain: raw field, filter, gate, draft."""
    started = time.monotonic()

    def is_source(candidate) -> bool:
        return (
            candidate.canonical_key == item.judgment_key
            and str(candidate.paragraph_label) == item.paragraph_label
        )

    # What a word search alone would put in front of a lawyer.
    raw = find_authorities(
        session,
        item.proposition,
        top=checked,
        one_per_judgment=False,
        court_voice_only=False,
        check_treatment=False,
    )
    raw_rank = next((i for i, c in enumerate(raw, start=1) if is_source(c)), None)

    # And what reaches the gate once `engine.search` has dropped everything that is not the court.
    field_ = find_authorities(session, item.proposition, top=checked, one_per_judgment=False)

    refused_voice = refused_doubtful = 0
    source_survived = False
    source_refusal: str | None = None
    for candidate in field_:
        # `None` for the verdict runs only the half of the gate that needs no model: voice, opinion
        # and subsequent history. That is the half this pass is about.
        status, reason = _gate(candidate, None)
        if is_source(candidate):
            source_survived = True
            if status == REFUSED:
                source_refusal = reason
        if status != REFUSED:
            continue
        if "not the court" in reason or "dissent" in reason:
            refused_voice += 1
        else:
            refused_doubtful += 1

    binding = bind_proposition(session, item.proposition, model, checked=checked)
    chosen = binding.chosen.authority if binding.chosen else None
    return GateOutcome(
        item=item,
        raw_candidates=len(raw),
        raw_not_the_court=sum(1 for c in raw if c.voice is not None and not c.voice.is_the_court),
        raw_source_rank=raw_rank,
        candidates=len(field_),
        source_survived=source_survived,
        refused_not_the_court=refused_voice,
        refused_doubtful=refused_doubtful,
        source_refusal=source_refusal,
        status=binding.status,
        chosen_key=chosen.canonical_key if chosen else None,
        chosen_label=str(chosen.paragraph_label) if chosen and chosen.paragraph_label else None,
        seconds=round(time.monotonic() - started, 3),
    )


def run_gate(
    session: Session,
    items: list[GateItem],
    model: StructuredModel | None = None,
    *,
    checked: int = FIELD,
    on_item=None,
) -> GateReport:
    report = GateReport(model_configured=model is not None)
    report.judgments = len({i.judgment_key for i in items})
    for index, item in enumerate(items, start=1):
        report.outcomes.append(run_item(session, item, model, checked=checked))
        if on_item is not None:
            on_item(index, len(items))
    return report


def format_gate(report: GateReport) -> list[str]:
    """The report, as lines."""
    lines = [
        f"{len(report.outcomes)} propositions from {report.judgments} judgments"
        f"{'' if report.model_configured else ', no model configured'}",
        "",
        "Per proposition: what a word search returns, and what survives to reach the gate.",
        "",
        f"  {'drawn from':<24}{'n':>4}{'retrieved':>11}{'not court':>11}{'to the gate':>13}"
        f"{'gate drops':>12}",
    ]
    for kind in KINDS:
        outcomes = report.of(kind)
        if not outcomes:
            continue
        n = len(outcomes)
        lines.append(
            f"  {KIND_NAMES[kind]:<24}{n:>4}"
            f"{sum(o.raw_candidates for o in outcomes) / n:>11.1f}"
            f"{sum(o.raw_not_the_court for o in outcomes) / n:>11.1f}"
            f"{sum(o.candidates for o in outcomes) / n:>13.1f}"
            f"{sum(o.refused_not_the_court + o.refused_doubtful for o in outcomes) / n:>12.2f}"
        )

    lines += ["", "What the drafting surface answered, end to end:", ""]
    lines.append(f"  {'drawn from':<24}{'bound':>8}{'narrowed':>10}{'unchecked':>11}{'refused':>9}")
    for kind in KINDS:
        outcomes = report.of(kind)
        if not outcomes:
            continue
        n = len(outcomes)
        counts = {s: sum(1 for o in outcomes if o.status == s) for s in (BOUND, NARROWED, UNCHECKED, REFUSED)}
        lines.append(
            f"  {KIND_NAMES[kind]:<24}"
            f"{counts[BOUND] / n:>8.0%}{counts[NARROWED] / n:>10.0%}"
            f"{counts[UNCHECKED] / n:>11.0%}{counts[REFUSED] / n:>9.0%}"
        )

    lines += ["", *_source_lines(report), ""]
    false_binds = report.false_binds
    if false_binds:
        lines.append(f"{len(false_binds)} propositions were BOUND to the paragraph they were lifted from,")
        lines.append("which was counsel's submission or a dissent. Each one is a citation this tool")
        lines.append("would have written into a draft:")
        lines.extend(
            f"  {o.item.kind}: {o.chosen_key} para {o.chosen_label} - {o.item.proposition[:70]}"
            for o in false_binds
        )
    else:
        lines.append("No proposition was bound to the paragraph it was lifted from where that")
        lines.append("paragraph was counsel's submission or a dissent.")

    if not report.model_configured:
        lines += [
            "",
            "With no model configured nothing can be bound, so the `bound` and `narrowed` columns",
            "are structurally zero and say nothing about the gate. What they do measure is the",
            "three-state honesty: an unchecked passage is offered to read and never as authority.",
        ]
    return lines


def _source_lines(report: GateReport) -> list[str]:
    """The chain, for the two kinds that must never be cited: retrieved, filtered, refused, bound."""
    out = []
    for kind in (COUNSEL, DISSENT):
        outcomes = report.of(kind)
        if not outcomes:
            # An absent row is not a clean row, and a report that simply omits it invites the reader
            # to assume the kind was tested and nothing was found.
            out.append(
                f"No judgment in this draw carried {KIND_NAMES[kind]}, so that row is missing rather "
                "than clean."
            )
            continue
        reachable = [o for o in outcomes if o.raw_source_rank is not None]
        survived = [o for o in reachable if o.source_survived]
        bound = [o for o in outcomes if o.bound_to_source]
        out.append(
            f"{KIND_NAMES[kind].capitalize()}: a word search put the source paragraph within reach "
            f"for {len(reachable)} of {len(outcomes)} propositions; {len(survived)} survived the "
            f"voice filter to reach the gate; {len(bound)} were bound."
        )
    return out


def write_report(report: GateReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(format_gate(report)) + "\n", encoding="utf-8")
