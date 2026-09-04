"""Assemble a verdict for one citation, and grade it.

The grade is a rubric applied in Python, not an opinion asked of a model. Every deduction names the
failure mode from docs/PRD.md that caused it, so a reader can see why a citation was marked down and
disagree with the rule rather than with a black box.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orderorder.engine.locator import PinpointCheck
from orderorder.engine.scope import ScopeVerdict
from orderorder.engine.voice import VoiceVerdict
from orderorder.engine.weight import WeightVerdict
from orderorder.resolver import Resolution

GRADES = ["A", "B", "C", "D", "E", "F"]

# Failure modes from docs/PRD.md section 6.
MODE_PHANTOM = 1
MODE_MISCITE = 2
MODE_NOT_THERE = 4
MODE_QUOTED = 5
MODE_WRONG_VOICE = 5
MODE_MINORITY = 6
MODE_OBITER = 7
MODE_OVERSTATEMENT = 8
MODE_WRONG_PINPOINT = 12


@dataclass
class Finding:
    """One thing wrong with a citation, tied to the taxonomy."""

    mode: int
    label: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.mode}] {self.label}: {self.detail}"


@dataclass
class CitationVerdict:
    citation_raw: str
    proposition: str
    existence: str  # found | not_found | ambiguous
    canonical_key: str | None = None
    judgment_title: str | None = None
    resolution_method: str | None = None
    support: str = "not_assessed"
    quote: str | None = None
    quote_verified: bool = False
    paragraph_label: str | None = None
    claimed_pinpoint: str | None = None
    voice: VoiceVerdict | None = None
    weight: WeightVerdict | None = None
    findings: list[Finding] = field(default_factory=list)
    grade: str = "A"
    needs_review: bool = False
    review_reason: str | None = None
    scope: ScopeVerdict | None = None
    pinpoint: PinpointCheck | None = None

    @property
    def is_sound(self) -> bool:
        return self.grade in {"A", "B"} and not self.findings


def _drop(grade: str, steps: int = 1) -> str:
    return GRADES[min(GRADES.index(grade) + steps, len(GRADES) - 1)]


def _floor(grade: str, worst: str) -> str:
    """Push a grade down to `worst` if it is not already there or below. Never improves a grade."""
    return grade if GRADES.index(grade) >= GRADES.index(worst) else worst


def voice_label(voice: VoiceVerdict, verdict: CitationVerdict) -> str:
    """Name the paragraph a voice finding is about, however the verdict came to know it."""
    return verdict.paragraph_label or verdict.claimed_pinpoint or "the passage relied on"


def build_verdict(
    citation_raw: str,
    proposition: str,
    resolution: Resolution,
    *,
    judgment_title: str | None = None,
    pinpoint: PinpointCheck | None = None,
    scope: ScopeVerdict | None = None,
    voice: VoiceVerdict | None = None,
    weight: WeightVerdict | None = None,
    claimed_pinpoint: str | None = None,
    likely_quoted: bool = False,
) -> CitationVerdict:
    """Combine the detectors into one verdict, then grade it."""
    verdict = CitationVerdict(
        citation_raw=citation_raw,
        proposition=proposition,
        existence=resolution.status,
        canonical_key=resolution.canonical_key,
        judgment_title=judgment_title,
        resolution_method=resolution.method,
        claimed_pinpoint=claimed_pinpoint,
        pinpoint=pinpoint,
        scope=scope,
        voice=voice,
        weight=weight,
    )

    # Existence. A well-formed citation matching nothing is the phantom case and is terminal.
    if resolution.status == "not_found":
        verdict.findings.append(
            Finding(MODE_PHANTOM, "no such case", resolution.note or "no judgment carries this citation")
        )
        verdict.grade = "F"
        verdict.needs_review = True
        verdict.review_reason = "the citation could not be resolved against the corpus"
        return verdict

    if resolution.status == "ambiguous":
        verdict.needs_review = True
        verdict.review_reason = resolution.note or "several judgments match this citation"
        verdict.grade = "C"
        return verdict

    if resolution.method == "party_name":
        verdict.findings.append(
            Finding(
                MODE_MISCITE,
                "citation string is wrong",
                resolution.note or "matched on party names, not on the citation given",
            )
        )
        verdict.grade = _drop(verdict.grade, 2)

    # Pinpoint.
    if pinpoint is not None and pinpoint.is_problem:
        verdict.findings.append(Finding(MODE_WRONG_PINPOINT, "pinpoint does not exist", pinpoint.note or ""))
        verdict.grade = _drop(verdict.grade, 2)

    # The out-of-sequence heuristic is the weakest form of the voice check, so it only speaks when the
    # voice check itself has nothing to say; otherwise the same passage would be marked down twice.
    if likely_quoted and voice is None:
        verdict.findings.append(
            Finding(
                MODE_QUOTED,
                "passage may be quoted from another judgment",
                "its paragraph number breaks this judgment's sequence, so the words may not be this court's",
            )
        )
        verdict.grade = _drop(verdict.grade)

    if scope is not None:
        verdict.quote = scope.quote
        verdict.quote_verified = scope.quote_verified
        verdict.paragraph_label = scope.matched_paragraph_label or scope.paragraph_label

    # Voice and opinion. These are about the paragraph the brief actually relies on, and they are
    # decided from the judgment's own structure and cues, so they hold even with no model configured.
    if voice is not None:
        if voice.is_dissent:
            verdict.findings.append(
                Finding(
                    MODE_MINORITY,
                    "the passage is from a dissent",
                    (
                        f"paragraph {voice_label(voice, verdict)} falls in the dissenting opinion"
                        + (f" of {voice.opinion_author}" if voice.opinion_author else "")
                        + ", which decided nothing and binds no one"
                    ),
                )
            )
            verdict.grade = _floor(verdict.grade, "D")
        elif voice.is_problem:
            verdict.findings.append(
                Finding(MODE_WRONG_VOICE, f"not the court's words ({voice.voice})", voice.reason or "")
            )
            verdict.grade = _floor(verdict.grade, "D")
        if voice.needs_review and not verdict.needs_review:
            verdict.needs_review = True
            verdict.review_reason = voice.reason

    # Weight. Only a grounded classification costs a grade; "unclear" is the honest default.
    if weight is not None and weight.is_obiter:
        verdict.findings.append(
            Finding(MODE_OBITER, "obiter, not the holding", weight.reason or "")
        )
        verdict.grade = _drop(verdict.grade)

    # Scope.
    if scope is not None:
        # "Could not check" is not "checked and found wanting". Reporting the first as the second
        # would be the same overclaiming this product exists to catch, so it only asks for review.
        if scope.model_support in {"not_assessed", "error", "malformed"}:
            verdict.support = "not_assessed"
            verdict.needs_review = True
            verdict.review_reason = scope.review_reason
            return verdict

        verdict.support = scope.support
        if scope.support == "contradicted":
            verdict.findings.append(
                Finding(MODE_NOT_THERE, "the judgment says the opposite", scope.gap or "")
            )
            verdict.grade = "F"
        elif scope.support == "none":
            detail = scope.review_reason or scope.gap or "no paragraph supports this proposition"
            verdict.findings.append(Finding(MODE_NOT_THERE, "not supported by this judgment", detail))
            verdict.grade = "F"
        elif scope.support == "partial":
            detail = scope.gap or "the court stated this more narrowly than the brief does"
            if scope.dropped_conditions:
                detail += " Conditions omitted: " + "; ".join(scope.dropped_conditions) + "."
            verdict.findings.append(Finding(MODE_OVERSTATEMENT, "overstated", detail))
            verdict.grade = _drop(verdict.grade, 2)

        if scope.wrong_pinpoint and scope.quote_verified:
            verdict.findings.append(
                Finding(
                    MODE_WRONG_PINPOINT,
                    "quote is in a different paragraph",
                    f"the supporting text is in paragraph {scope.matched_paragraph_label}, "
                    f"not {scope.paragraph_label}",
                )
            )
            verdict.grade = _drop(verdict.grade)

        if scope.needs_review:
            verdict.needs_review = True
            verdict.review_reason = scope.review_reason

    return verdict
