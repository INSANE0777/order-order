"""Everything about the citation is sound. Does the case actually apply?

Failure mode 11, and the last of the twelve. The case is real, the paragraph exists, it is the court's
own holding, it is good law, and it says what the brief claims — and the facts before this court are
materially different, so it decides nothing here. This is the objection opposing counsel makes when
there is nothing else to say, and it is the one an advocate is least able to anticipate about their
own brief.

It is also the only check in the engine that cannot be made from the judgment alone. It needs the
facts of the present matter, which nobody but the user has, so it runs only when they are supplied and
otherwise reports that it was not asked.

The discipline is the one used everywhere else, and it matters more here than anywhere. Declaring an
authority inapplicable is a strong claim: an advocate who believes it drops a good case. So the model
must quote the sentence of the judgment that states the fact it says differs, and that quote is
string-matched against the stored text. A distinguishing fact that cannot be found in the judgment is
not a distinguishing fact; the answer becomes `not_assessed` and asks for review, never `inapplicable`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orderorder.engine.locator import Candidate
from orderorder.engine.prompts import APPLICABILITY_PROMPT, APPLICABILITY_VERSION, format_candidates
from orderorder.engine.providers import StructuredModel
from orderorder.engine.quotes import MIN_QUOTE_WORDS, find_quote, word_count
from orderorder.engine.schemas import ApplicabilityAssessment

STRONG = "strong"
MODERATE = "moderate"
WEAK = "weak"
INAPPLICABLE = "inapplicable"
NOT_ASSESSED = "not_assessed"

MIN_CONFIDENCE = 0.4


@dataclass
class ApplicabilityVerdict:
    """How far the cited case governs the matter actually before the court."""

    status: str
    distinguishing_facts: list[str] = field(default_factory=list)
    shared_facts: list[str] = field(default_factory=list)
    reason: str | None = None
    quote: str | None = None
    quote_verified: bool = False
    paragraph_label: str | None = None
    confidence: float = 0.0
    needs_review: bool = False
    review_reason: str | None = None
    prompt_version: str | None = None

    @property
    def is_problem(self) -> bool:
        """Only a grounded finding of inapplicability counts against a citation."""
        return self.status == INAPPLICABLE and self.quote_verified

    @property
    def was_assessed(self) -> bool:
        return self.status != NOT_ASSESSED


def assess_applicability(
    proposition: str,
    matter_facts: str,
    candidates: list[Candidate],
    model: StructuredModel | None,
    *,
    ocr_derived: bool = False,
) -> ApplicabilityVerdict:
    """Compare the facts the cited case turned on with the facts of the present matter."""
    if not (matter_facts or "").strip():
        return ApplicabilityVerdict(
            status=NOT_ASSESSED,
            review_reason=(
                "the facts of the present matter were not supplied, so whether this authority applies "
                "to them was not assessed"
            ),
        )
    if model is None:
        return ApplicabilityVerdict(
            status=NOT_ASSESSED,
            needs_review=True,
            review_reason=(
                "no language model is configured, so whether the cited case is distinguishable on its "
                "facts was not assessed"
            ),
        )
    if not candidates:
        return ApplicabilityVerdict(
            status=NOT_ASSESSED,
            needs_review=True,
            review_reason="no paragraph of the judgment was located, so its facts could not be compared",
        )

    prompt = APPLICABILITY_PROMPT.format(
        claim=proposition.strip(),
        facts=matter_facts.strip(),
        candidates=format_candidates(
            [(c.printed_label or f"#{c.seq}", c.body) for c in candidates], claim=proposition
        ),
    )
    try:
        answer = model.invoke(prompt)
    except Exception as exc:  # noqa: BLE001 - a provider outage must not lose the other detectors
        return ApplicabilityVerdict(
            status=NOT_ASSESSED,
            needs_review=True,
            review_reason=f"every configured model provider failed ({type(exc).__name__})",
        )
    if not isinstance(answer, ApplicabilityAssessment):
        return ApplicabilityVerdict(
            status=NOT_ASSESSED,
            needs_review=True,
            review_reason="the model did not return a usable assessment",
        )

    verdict = ApplicabilityVerdict(
        status=answer.status,
        distinguishing_facts=list(answer.distinguishing_facts),
        shared_facts=list(answer.shared_facts),
        reason=answer.reason,
        quote=(answer.quote or "").strip() or None,
        paragraph_label=answer.paragraph_label,
        confidence=answer.confidence,
        prompt_version=APPLICABILITY_VERSION,
    )

    if answer.status != INAPPLICABLE:
        # Only the strong claim has to be grounded. Saying a case applies takes nothing away from the
        # advocate, and the rest of the engine has already checked that it says what they claim.
        return verdict

    if not verdict.quote or word_count(verdict.quote) < MIN_QUOTE_WORDS:
        verdict.status = NOT_ASSESSED
        verdict.needs_review = True
        verdict.review_reason = (
            "the model called the authority inapplicable without quoting the fact it relies on, so "
            "nothing could be verified"
        )
        return verdict

    for candidate in candidates:
        match = find_quote(verdict.quote, candidate.body, ocr_derived=ocr_derived)
        if match.found:
            verdict.quote_verified = True
            verdict.paragraph_label = candidate.printed_label or verdict.paragraph_label
            break

    if not verdict.quote_verified:
        verdict.status = NOT_ASSESSED
        verdict.needs_review = True
        verdict.review_reason = (
            "the fact the model says distinguishes this case does not appear in the judgment, so the "
            "authority is not recorded as inapplicable"
        )
        return verdict

    if answer.confidence and answer.confidence < MIN_CONFIDENCE:
        verdict.needs_review = True
        verdict.review_reason = (
            f"the model's own confidence was {answer.confidence:.2f}, below the threshold for calling "
            "an authority inapplicable without review"
        )
    return verdict
