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
MODEL_DEPENDENT = {7, 8, 9, 11}


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
    def false_positive(self) -> bool:
        """A clean citation the engine flagged anyway."""
        return self.item.is_clean and bool(self.modes_found)


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
