"""Run the engine over a gold set and score it.

The metrics are those in `docs/ARCHITECTURE.md` section 11.2, and three of them carry the weight.

**Recall per mode** — of the items where a given failure was planted, how many did the engine find.
This is what people mean by "does it work".

**False positive rate on clean items** — of the citations that were sound in every respect, how many
did the engine flag anyway. Recall alone cannot see this, and an engine that flags everything scores
perfectly on recall while being worthless: an advocate warned about every citation checks none of
them. This is the number to watch when a detector is made more sensitive.

**Quote-grounding rate** — of the verdicts claiming support, how many rest on a quote that string-
matches the stored judgment. The architecture says this must be 100%, and it is not an aspiration but
an invariant: anything less means the verifier let an ungrounded claim through, which is the one
failure this whole design exists to make impossible.

A run with no model configured still scores every model-free mode, and reports the rest as unassessed
rather than as failures.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from orderorder.citations.grammar import extract_citations
from orderorder.engine.graph import verify_citation
from orderorder.engine.providers import StructuredModel
from orderorder.engine.verdict import CitationVerdict
from orderorder.evaluation.gold import MODE_NAMES, GoldItem

# Modes that need a language model to be detected at all. Without one they are reported as unassessed
# rather than counted as misses, because a miss and a question never asked are different things.
#
# Mode 9 was here until the truncation check was written. It had scored 0/20 *with* a model, which the
# report showed was not a miss at all: the model found the dropped condition every time and the
# verdict recorded it as mode 8. Truncation is a string operation, so it now has its own model-free
# check and its own number, and scores 20/20 with nothing configured.
MODEL_DEPENDENT = {4, 7, 8, 11}

# Which gold label a finding would have to contradict. A mode absent from this table contradicts a
# clean item by existing at all: a sound citation resolves, and its paragraph is where its words
# are, and it does not overstate its bench. The modes listed here need the label to have been
# recorded, and where it was not, the finding is neither confirmed nor a false positive.
WARRANTED_BY = {7: "weight", 10: "treatment", 11: "applicability"}


@dataclass
class ItemResult:
    """What the engine said about one gold item."""

    item: GoldItem
    verdict: CitationVerdict | None
    seconds: float = 0.0
    error: str | None = None

    @property
    def modes_found(self) -> set[int]:
        return {f.mode for f in self.verdict.findings} if self.verdict else set()

    @property
    def caught(self) -> bool:
        """The planted mode is among the findings."""
        return self.item.planted_error in self.modes_found if self.item.planted_error else False

    @property
    def unwarranted(self) -> set[int]:
        """Findings on a clean item that the gold labels do not actually contradict.

        A clean item is warranted to be the court's own words, correctly cited, at the paragraph
        named. It is *not* warranted to be the ratio: nothing in the corpus says whether a sentence
        was necessary to the decision, and the generator does not pretend otherwise — the label is
        left empty. So a mode 7 finding on one of these contradicts nothing the gold set claimed, and
        counting it as a false positive would mark the engine down for answering a question the item
        never asked.

        That is not the same as the finding being right. It means this set cannot say, and the number
        below has to be read as covering the checks the labels cover. The rest needs paragraphs a
        person has read.
        """
        labels = self.item.labels
        return {
            mode
            for mode in self.modes_found
            if (field := WARRANTED_BY.get(mode)) is not None and getattr(labels, field, None) is None
        }

    @property
    def false_positive(self) -> bool:
        """A clean citation the engine flagged with something the gold labels contradict."""
        return self.item.is_clean and bool(self.modes_found - self.unwarranted)


@dataclass
class Report:
    results: list[ItemResult] = field(default_factory=list)
    model_configured: bool = False

    @property
    def clean(self) -> list[ItemResult]:
        return [r for r in self.results if r.item.is_clean]

    @property
    def planted(self) -> list[ItemResult]:
        return [r for r in self.results if not r.item.is_clean]

    def recall_by_mode(self) -> dict[int, tuple[int, int]]:
        """{mode: (caught, total)} over the planted items."""
        counts: dict[int, list[int]] = {}
        for result in self.planted:
            mode = result.item.planted_error
            if mode is None:
                continue
            entry = counts.setdefault(mode, [0, 0])
            entry[1] += 1
            entry[0] += int(result.caught)
        return {mode: (caught, total) for mode, (caught, total) in sorted(counts.items())}

    @property
    def false_positive_rate(self) -> float | None:
        clean = self.clean
        if not clean:
            return None
        return sum(r.false_positive for r in clean) / len(clean)

    @property
    def quote_grounding_rate(self) -> float | None:
        """Of verdicts claiming support, the share whose quote verified. Must be 1.0."""
        claimed = [
            r.verdict
            for r in self.results
            if r.verdict and r.verdict.support in {"full", "partial"}
        ]
        if not claimed:
            return None
        return sum(1 for v in claimed if v.quote_verified) / len(claimed)

    @property
    def abstention_rate(self) -> float | None:
        graded = [r.verdict for r in self.results if r.verdict]
        if not graded:
            return None
        return sum(1 for v in graded if v.needs_review) / len(graded)

    @property
    def seconds_per_item(self) -> float:
        timed = [r.seconds for r in self.results if r.seconds]
        return sum(timed) / len(timed) if timed else 0.0

    def unassessed_modes(self) -> set[int]:
        """Planted modes that could not be judged because no model was configured."""
        if self.model_configured:
            return set()
        return {r.item.planted_error for r in self.planted if r.item.planted_error in MODEL_DEPENDENT}


def run_item(
    session: Session,
    item: GoldItem,
    model: StructuredModel | None = None,
    *,
    voice_model: StructuredModel | None = None,
    weight_model: StructuredModel | None = None,
    facts_model: StructuredModel | None = None,
) -> ItemResult:
    """Put one gold item through the engine exactly as a brief would arrive."""
    sentence = item.brief_sentence
    citations = extract_citations(sentence)
    if not citations:
        return ItemResult(item, None, error="the grammar found no citation in the item")

    started = time.monotonic()
    try:
        verdict = verify_citation(
            session,
            citations[0],
            sentence,
            model,
            voice_model=voice_model,
            weight_model=weight_model,
            facts_model=facts_model,
            matter_facts=item.user_facts or "",
        )
    except Exception as exc:  # noqa: BLE001 - one bad item must not end the run
        return ItemResult(item, None, seconds=time.monotonic() - started, error=f"{type(exc).__name__}: {exc}")
    return ItemResult(item, verdict, seconds=time.monotonic() - started)


def run_gold(
    session: Session,
    items: list[GoldItem],
    model: StructuredModel | None = None,
    *,
    voice_model: StructuredModel | None = None,
    weight_model: StructuredModel | None = None,
    facts_model: StructuredModel | None = None,
    on_result=None,
) -> Report:
    """Score the engine over a whole gold set."""
    report = Report(model_configured=model is not None)
    for index, item in enumerate(items, start=1):
        result = run_item(
            session,
            item,
            model,
            voice_model=voice_model,
            weight_model=weight_model,
            facts_model=facts_model,
        )
        report.results.append(result)
        if on_result is not None:
            on_result(result, index, len(items))
    return report


def format_report(report: Report) -> list[str]:
    """The report as lines, for the terminal or a file."""
    lines: list[str] = []
    lines.append(f"{len(report.results)} items: {len(report.planted)} planted, {len(report.clean)} clean")
    lines.append(f"model configured: {report.model_configured}")
    lines.append("")

    lines.append("recall by planted failure mode")
    unassessed = report.unassessed_modes()
    for mode, (caught, total) in report.recall_by_mode().items():
        name = MODE_NAMES.get(mode, str(mode))
        if mode in unassessed:
            lines.append(f"  [{mode:>2}] {name:<22} {caught}/{total}  (needs a model; not counted)")
        else:
            lines.append(f"  [{mode:>2}] {name:<22} {caught}/{total}  {caught / total:6.0%}")

    lines.append("")
    rate = report.false_positive_rate
    if rate is not None:
        flagged = sum(r.false_positive for r in report.clean)
        lines.append(f"false positives on clean citations : {flagged}/{len(report.clean)}  {rate:.0%}")
    grounding = report.quote_grounding_rate
    if grounding is not None:
        verdict_word = "ok" if grounding == 1.0 else "INVARIANT BROKEN"
        lines.append(f"quote grounding (must be 100%)     : {grounding:.0%}  {verdict_word}")
    abstention = report.abstention_rate
    if abstention is not None:
        lines.append(f"abstention rate                    : {abstention:.0%}")
    lines.append(f"seconds per item                   : {report.seconds_per_item:.1f}")

    errors = [r for r in report.results if r.error]
    if errors:
        lines.append("")
        lines.append(f"{len(errors)} items errored:")
        for result in errors[:5]:
            lines.append(f"  {result.item.id}: {result.error}")
    return lines


def format_disagreements(report: Report) -> list[str]:
    """Every item the engine and the gold label disagree about, with enough to act on.

    A score that moves tells you something changed and nothing about what. This is the view to read
    next: the clean citations that were flagged and what was said about them, and the planted errors
    that went by. Modes needing a model are left out of the misses when there was none, since a
    question never asked is not a wrong answer.
    """
    unassessed = report.unassessed_modes()
    lines = ["disagreements"]

    for result in report.clean:
        if not result.false_positive:
            continue
        lines.append(f"  FALSE POSITIVE  {result.item.id}")
        lines.append(f"    cited   {result.item.citation_raw}")
        lines.append(f"    claim   {result.item.claim_text[:150]}")
        for finding in result.verdict.findings if result.verdict else []:
            unwarranted = " (not counted: the gold set does not label this)" if finding.mode in result.unwarranted else ""
            lines.append(f"      -> {finding}{unwarranted}")

    for result in report.planted:
        mode = result.item.planted_error
        if result.caught or mode in unassessed:
            continue
        name = MODE_NAMES.get(mode or 0, str(mode))
        lines.append(f"  MISSED [{mode}] {name}  {result.item.id}")
        lines.append(f"    cited   {result.item.citation_raw}")
        lines.append(f"    claim   {result.item.claim_text[:150]}")
        if result.error:
            lines.append(f"    errored {result.error}")
        elif result.verdict:
            lines.append(f"    graded  {result.verdict.grade}, existence {result.verdict.existence}")
            for finding in result.verdict.findings:
                lines.append(f"      -> said instead: {finding}")

    if len(lines) == 1:
        lines.append("  none: every planted error was caught and no clean citation was flagged")
    return lines
