"""Assemble a verdict for one citation, and grade it.

The grade is a rubric applied in Python, not an opinion asked of a model. Every deduction names the
failure mode from docs/PRD.md that caused it, so a reader can see why a citation was marked down and
disagree with the rule rather than with a black box.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orderorder.engine.citator import TreatmentReport
from orderorder.engine.facts import ApplicabilityVerdict
from orderorder.engine.hierarchy import HierarchyCheck
from orderorder.engine.locator import PinpointCheck, pinpoint_covers
from orderorder.engine.scope import ScopeVerdict
from orderorder.engine.truncation import Truncation
from orderorder.engine.voice import VoiceVerdict
from orderorder.engine.weight import WeightVerdict
from orderorder.resolver import Resolution

GRADES = ["A", "B", "C", "D", "E", "F"]

# Failure modes from docs/PRD.md section 6.
MODE_PHANTOM = 1
MODE_MISCITE = 2
MODE_WRONG_COURT = 3
MODE_NOT_THERE = 4
MODE_QUOTED = 5
MODE_WRONG_VOICE = 5
MODE_MINORITY = 6
MODE_OBITER = 7
MODE_OVERSTATEMENT = 8
MODE_SELECTIVE = 9
MODE_DEAD_LAW = 10
MODE_DISTINGUISHABLE = 11
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
    treatment: TreatmentReport | None = None
    hierarchy: HierarchyCheck | None = None
    applicability: ApplicabilityVerdict | None = None
    truncation: Truncation | None = None
    findings: list[Finding] = field(default_factory=list)
    grade: str = "A"
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    scope: ScopeVerdict | None = None
    pinpoint: PinpointCheck | None = None
    # Where the citation sits in the brief, so a verdict can be shown against the text it is about.
    span: tuple[int, int] | None = None

    @property
    def is_sound(self) -> bool:
        return self.grade in {"A", "B"} and not self.findings

    @property
    def review_reason(self) -> str | None:
        """Every reason review was asked for, joined.

        A citation can want review twice over for different reasons: the paragraph carries more than
        one voice, and no model was configured to read it. Keeping only the last one arriving would
        hide whichever came first, and the two are not alternatives.
        """
        return "; ".join(self.review_reasons) or None

    def ask_review(self, reason: str | None) -> None:
        """Record that a human should look at this citation, and why."""
        self.needs_review = True
        if reason and reason not in self.review_reasons:
            self.review_reasons.append(reason)


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
    treatment: TreatmentReport | None = None,
    hierarchy: HierarchyCheck | None = None,
    applicability: ApplicabilityVerdict | None = None,
    truncation: Truncation | None = None,
    claimed_pinpoint: str | None = None,
    likely_quoted: bool = False,
    span: tuple[int, int] | None = None,
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
        span=span,
        pinpoint=pinpoint,
        scope=scope,
        voice=voice,
        weight=weight,
        treatment=treatment,
        hierarchy=hierarchy,
        applicability=applicability,
        truncation=truncation,
    )

    # Existence. A well-formed citation matching nothing is the phantom case and is terminal.
    if resolution.status == "not_found":
        verdict.findings.append(
            Finding(MODE_PHANTOM, "no such case", resolution.note or "no judgment carries this citation")
        )
        verdict.grade = "F"
        verdict.ask_review("the citation could not be resolved against the corpus")
        return verdict

    if resolution.status == "ambiguous":
        verdict.ask_review(resolution.note or "several judgments match this citation")
        verdict.grade = "C"
        return verdict

    # The citation exists, but not for the case the brief names.
    if getattr(resolution, "name_mismatch", False):
        verdict.findings.append(
            Finding(
                MODE_MISCITE,
                "citation points at a different case",
                resolution.note or "the party names do not match the judgment this citation resolves to",
            )
        )
        verdict.grade = _drop(verdict.grade, 2)

    if resolution.method == "party_name":
        verdict.findings.append(
            Finding(
                MODE_MISCITE,
                "citation string is wrong",
                resolution.note or "matched on party names, not on the citation given",
            )
        )
        verdict.grade = _drop(verdict.grade, 2)

    # The court. A High Court decision passed off as the Supreme Court's, or two judges called a
    # Constitution Bench, makes an authority binding that is not — and both are settled by the record
    # rather than by reading the judgment.
    if hierarchy is not None and hierarchy.is_problem:
        verdict.findings.append(
            Finding(MODE_WRONG_COURT, f"wrong court or bench ({hierarchy.status})", hierarchy.note or "")
        )
        verdict.grade = _floor(verdict.grade, "D")

    # Pinpoint. Two kinds, and the difference is worth showing: a paragraph that is not in the
    # judgment at all, and a paragraph that is there but is not where the words came from. The second
    # is the commoner mistake and the harder one to see by hand.
    if pinpoint is not None and pinpoint.is_problem:
        label = (
            "pinpoint names the wrong paragraph"
            if pinpoint.status == "wrong_paragraph"
            else "pinpoint does not exist"
        )
        verdict.findings.append(Finding(MODE_WRONG_PINPOINT, label, pinpoint.note or ""))
        verdict.grade = _drop(verdict.grade, 2)

    # Selective quotation. Everything the brief quoted is the court's, word for word; what it did was
    # stop before the qualification. That is a string comparison, so it is made here rather than left
    # to the scope comparator's model, and it names the words that were cut instead of describing
    # them.
    if truncation is not None:
        verdict.findings.append(
            Finding(MODE_SELECTIVE, "quotation cut before the qualification", truncation.note)
        )
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
        if voice.needs_review:
            verdict.ask_review(voice.reason)

    # Treatment. A citation can be sound in every other respect and still be dead law, and nothing in
    # the judgment itself records that: only the judgments that came after it do.
    if treatment is not None and treatment.is_doubtful:
        verdict.findings.append(
            Finding(MODE_DEAD_LAW, f"{treatment.status.replace('_', ' ')} by a later judgment", treatment.note or "")
        )
        verdict.grade = _floor(verdict.grade, "D")

    # Applicability. The last question, and the only one the judgment cannot answer by itself: the
    # facts of the matter now before the court are not in it.
    if applicability is not None:
        if applicability.is_problem:
            detail = applicability.reason or "the facts the cited case turned on are absent here"
            if applicability.distinguishing_facts:
                detail += " Distinguishing facts: " + "; ".join(applicability.distinguishing_facts) + "."
            verdict.findings.append(Finding(MODE_DISTINGUISHABLE, "distinguishable on the facts", detail))
            verdict.grade = _drop(verdict.grade)
        if applicability.needs_review:
            verdict.ask_review(applicability.review_reason)

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
            verdict.ask_review(scope.review_reason)
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
            # A truncated quotation is an overstatement, and it already has its own finding above with
            # the exact words that were cut. Reporting both marks the same act down twice and makes
            # the taxonomy look as though it caught two things.
            if truncation is None:
                verdict.findings.append(Finding(MODE_OVERSTATEMENT, "overstated", detail))
            verdict.grade = _drop(verdict.grade, 2)

        # Where the verified quote turned out to be, against where the *brief* said to look. The
        # comparison has to be with the brief's own pinpoint: `scope.wrong_pinpoint` records that the
        # model named one paragraph and the quote verified in another, which is the model disagreeing
        # with itself and a reason to have someone look, not a finding against the citation. Comparing
        # the two model answers as strings also reported "paragraph 18" against "para 18 and para 19"
        # as a mismatch, which is a citation being marked down for being more precise than the brief.
        if scope.quote_verified and scope.matched_paragraph_label:
            if claimed_pinpoint and not pinpoint_covers(claimed_pinpoint, scope.matched_paragraph_label):
                verdict.findings.append(
                    Finding(
                        MODE_WRONG_PINPOINT,
                        "quote is in a different paragraph",
                        f"the supporting text is in paragraph {scope.matched_paragraph_label}, "
                        f"but the brief cites paragraph {claimed_pinpoint}",
                    )
                )
                verdict.grade = _drop(verdict.grade)
            elif scope.wrong_pinpoint:
                verdict.ask_review(
                    f"the passage was read as paragraph {scope.paragraph_label} but the quote verified "
                    f"in paragraph {scope.matched_paragraph_label}"
                )

        if scope.needs_review:
            verdict.ask_review(scope.review_reason)

    return verdict
