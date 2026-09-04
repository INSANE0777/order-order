"""Does the paragraph support the claim, and to what extent?

This is the third of the product's three questions and the one nobody else answers. A citation can be
real, and the paragraph can exist, and the brief can still be wrong: the court may have held the point
only where certain conditions were met, or said "may" where the brief says "must", or confined itself
to one statute where the brief claims a general rule.

The model reads the candidate paragraphs and answers. Its answer is then **checked, not believed**:

  * a claim marked supported must come with a quote that string-matches the stored judgment text
  * a quote that fails to match downgrades the claim to unsupported and flags it for review
  * a quote that matches a different paragraph than the model named is recorded as such

That check is why a model's fluency cannot turn into a false verdict. It is ordinary Python, and it
runs whatever model produced the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orderorder.engine.locator import Candidate
from orderorder.engine.prompts import (
    DECOMPOSE_PROMPT,
    DECOMPOSE_VERSION,
    SCOPE_PROMPT,
    SCOPE_VERSION,
    format_candidates,
)
from orderorder.engine.providers import StructuredModel
from orderorder.engine.quotes import MIN_QUOTE_WORDS, QuoteMatch, find_quote, word_count
from orderorder.engine.schemas import AtomicClaim, ClaimDecomposition, ScopeAssessment

MIN_CONFIDENCE_FOR_SUPPORT = 0.35


@dataclass
class ScopeVerdict:
    """What the model said, what the text actually confirms, and the difference between them."""

    claim: str
    support: str  # final, after verification
    model_support: str  # what the model answered before checking
    paragraph_label: str | None = None
    matched_paragraph_label: str | None = None
    quote: str | None = None
    quote_verified: bool = False
    quote_match_type: str = "not_attempted"
    char_start: int | None = None
    char_end: int | None = None
    dropped_conditions: list[str] = field(default_factory=list)
    court_modality: str | None = None
    court_scope: str | None = None
    gap: str | None = None
    narrowed_proposition: str | None = None
    confidence: float = 0.0
    needs_review: bool = False
    review_reason: str | None = None
    wrong_pinpoint: bool = False
    prompt_version: str = SCOPE_VERSION

    @property
    def is_supported(self) -> bool:
        return self.support in {"full", "partial"}

    @property
    def overstated(self) -> bool:
        """The court said it, but not as broadly as the brief does. Failure modes 8 and 9."""
        return self.support == "partial" and bool(self.dropped_conditions or self.gap)


def decompose_claim(
    proposition: str, model: StructuredModel | None, *, prompt_version: str = DECOMPOSE_VERSION
) -> list[AtomicClaim]:
    """Split a proposition into the assertions it makes.

    With no model available the proposition is treated as a single claim, which keeps the rest of the
    pipeline working; a brief asserting five things then gets checked as one, which is weaker but not
    wrong.
    """
    _ = prompt_version
    if model is None:
        return [AtomicClaim(text=proposition.strip())]
    result = model.invoke(DECOMPOSE_PROMPT.format(proposition=proposition.strip()))
    if isinstance(result, ClaimDecomposition) and result.claims:
        return result.claims
    return [AtomicClaim(text=proposition.strip())]


def _verify(
    assessment: ScopeAssessment, candidates: list[Candidate], *, ocr_derived: bool
) -> tuple[Candidate | None, QuoteMatch | None]:
    """Find which candidate actually contains the model's quote.

    The paragraph the model named is tried first, but every candidate is tried, because a model that
    copies the right sentence from the wrong paragraph is making a different mistake from one that
    invents a sentence, and the two deserve different verdicts.
    """
    quote = (assessment.quote or "").strip()
    if not quote or not candidates:
        return None, None

    named = next(
        (c for c in candidates if c.printed_label and c.printed_label == assessment.paragraph_label),
        None,
    )
    ordered = ([named] if named else []) + [c for c in candidates if c is not named]
    for candidate in ordered:
        match = find_quote(quote, candidate.body, ocr_derived=ocr_derived)
        if match.found:
            return candidate, match
    return None, find_quote(quote, ordered[0].body, ocr_derived=ocr_derived)


def assess_scope(
    claim: str,
    candidates: list[Candidate],
    model: StructuredModel | None,
    *,
    ocr_derived: bool = False,
) -> ScopeVerdict:
    """Ask how far the candidate paragraphs support the claim, then verify the answer against the text."""
    if model is None:
        return ScopeVerdict(
            claim=claim,
            support="none",
            model_support="not_assessed",
            needs_review=True,
            review_reason="no language model is configured, so extent of support was not assessed",
        )
    if not candidates:
        # Retrieval found nothing sharing vocabulary with the proposition. That is not evidence the
        # judgment fails to support it; it means the question was never put, so it asks for review.
        return ScopeVerdict(
            claim=claim,
            support="none",
            model_support="not_assessed",
            needs_review=True,
            review_reason=(
                "no paragraph of the judgment shares wording with this proposition, so extent of "
                "support was not assessed"
            ),
        )

    prompt = SCOPE_PROMPT.format(
        claim=claim.strip(),
        candidates=format_candidates([(c.printed_label or f"#{c.seq}", c.body) for c in candidates]),
    )
    try:
        assessment = model.invoke(prompt)
    except Exception as exc:  # noqa: BLE001 - a provider outage must not lose the other detectors
        return ScopeVerdict(
            claim=claim,
            support="none",
            model_support="error",
            needs_review=True,
            review_reason=(
                f"every configured model provider failed ({type(exc).__name__}), so extent of "
                "support was not assessed"
            ),
        )
    if not isinstance(assessment, ScopeAssessment):
        return ScopeVerdict(
            claim=claim,
            support="none",
            model_support="malformed",
            needs_review=True,
            review_reason="the model did not return a usable assessment",
        )

    verdict = ScopeVerdict(
        claim=claim,
        support=assessment.support,
        model_support=assessment.support,
        paragraph_label=assessment.paragraph_label,
        quote=(assessment.quote or "").strip() or None,
        dropped_conditions=list(assessment.dropped_conditions),
        court_modality=assessment.court_modality,
        court_scope=assessment.court_scope,
        gap=assessment.gap,
        narrowed_proposition=assessment.narrowed_proposition,
        confidence=assessment.confidence,
    )

    if assessment.support not in {"full", "partial"}:
        # Nothing to ground: "none" and "contradicted" stand on the model's reading of the text it saw.
        verdict.quote_match_type = "not_required"
        return verdict

    # Quote-or-nothing, from here down.
    if not verdict.quote:
        verdict.support = "none"
        verdict.needs_review = True
        verdict.quote_match_type = "missing"
        verdict.review_reason = (
            f"the model answered {assessment.support!r} but returned no quote, so nothing could be verified"
        )
        return verdict

    if word_count(verdict.quote) < MIN_QUOTE_WORDS:
        verdict.support = "none"
        verdict.needs_review = True
        verdict.quote_match_type = "too_short"
        verdict.review_reason = (
            f"the quote is shorter than {MIN_QUOTE_WORDS} words, which is too short to verify"
        )
        return verdict

    candidate, match = _verify(assessment, candidates, ocr_derived=ocr_derived)
    if candidate is None or match is None or not getattr(match, "found", False):
        verdict.support = "none"
        verdict.needs_review = True
        verdict.quote_verified = False
        verdict.quote_match_type = "not_found"
        verdict.review_reason = (
            "the quote the model gave does not appear in the judgment text, so the claim is "
            "recorded as unsupported"
        )
        return verdict

    verdict.quote_verified = True
    verdict.quote_match_type = match.match_type
    verdict.char_start = match.char_start
    verdict.char_end = match.char_end
    verdict.matched_paragraph_label = candidate.printed_label
    if assessment.paragraph_label and candidate.printed_label != assessment.paragraph_label:
        verdict.wrong_pinpoint = True

    if assessment.confidence and assessment.confidence < MIN_CONFIDENCE_FOR_SUPPORT:
        verdict.needs_review = True
        verdict.review_reason = (
            f"the model's own confidence was {assessment.confidence:.2f}, below the threshold for "
            "reporting support without review"
        )
    return verdict
