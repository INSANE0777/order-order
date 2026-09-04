"""Ratio or obiter: was the statement necessary to the decision?

Failure mode 7. A court decides a case, and along the way it says other things: an observation about a
question not before it, a view offered while expressly declining to decide, a caution added for
completeness. Those remarks are persuasive at best. A brief that cites one as the holding is claiming
more than the judgment decided, and no reader can tell from the paragraph alone, because an aside and a
holding look identical out of context.

There is no off-the-shelf classifier for this. What the text does give are two kinds of evidence:

  * **Declining cues.** A court that says "it is not necessary for us to decide" or "we leave the
    question open" has told you the passage is obiter, in terms. That is a string match, and it is the
    only classification this module makes without a model.
  * **The disposition.** Whether the outcome would change without the statement is a reading question,
    put to the model with the paragraph and the judgment's disposition, and grounded the same way the
    scope check is: the answer must quote the sentence that shows it, and the quote is verified against
    the paragraph. An answer that cannot be grounded becomes `unclear`.

`unclear` is the honest default and never costs a citation a grade. Calling a holding an aside is as
damaging as the reverse, so the classifier is required to abstain rather than guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orderorder.engine.locator import Candidate
from orderorder.engine.prompts import WEIGHT_PROMPT, WEIGHT_VERSION
from orderorder.engine.providers import StructuredModel
from orderorder.engine.quotes import MIN_QUOTE_WORDS, find_quote, word_count
from orderorder.engine.schemas import WeightAssessment
from orderorder.engine.voice import VoiceVerdict
from orderorder.ingest.segment import SegParagraph

# The court saying, in terms, that it is not deciding the point. Each of these makes what follows
# obiter on the court's own statement, which is why they are trusted without a model.
DECLINING_CUES = re.compile(
    r"""(?ix)
    (?:
        it\s+is\s+(?:not\s+necessary|unnecessary)\s+(?:for\s+us\s+)?to\s+(?:decide|express|go\s+into)
      | we\s+(?:need\s+not|do\s+not\s+propose\s+to|refrain\s+from|express\s+no|
            leave\s+(?:the|this)\s+question\s+open|are\s+not\s+called\s+upon\s+to)
      | (?:this\s+)?question\s+(?:is|does\s+not)\s+(?:left\s+open|arise\s+for\s+consideration)
      | assuming\s+(?:but\s+)?without\s+deciding
      | (?:we\s+may|it\s+may\s+be)\s+(?:only\s+)?(?:observe|add|mention|note)\s+
            (?:in\s+passing|by\s+way\s+of\s+(?:abundant\s+caution|clarification))
      | (?:by\s+the\s+way|in\s+passing(?!\s+(?:the|a|an|this|that|these|those|any)\b)|
         obiter(?:\s+dicta)?|en\s+passant)
      | (?:without\s+expressing\s+any\s+(?:final\s+)?opinion)
    )
    """
)

# Where the court disposes of the matter. Passed to the model as context, because "necessary to the
# outcome" is meaningless without knowing what the outcome was. The wording here was read off real
# Supreme Court judgments rather than guessed: a court writes "the appeal succeeds and is hereby
# allowed" at least as often as "the appeal is allowed", and the Reports print a "Result of the Case"
# line at the foot of every judgment, which is the most reliable marker of all.
DISPOSITION_CUES = re.compile(
    r"""(?ix)
    (?:
        (?:the\s+)?(?:appeals?|(?:writ\s+)?petitions?|applications?)\s+
            (?:is|are|stands?|shall\s+stand)\s+
            (?:accordingly\s+|hereby\s+)?(?:allowed|dismissed|disposed)
      | (?:the\s+)?appeals?\s+(?:succeeds?|fails?)
      | (?:we\s+)?(?:allow|dismiss)\s+the\s+(?:appeals?|petitions?)
      | (?:is|are)\s+hereby\s+(?:allowed|dismissed)
      | result\s+of\s+the\s+case\s*:
        # "The impugned judgment of the High Court is accordingly set aside": the court names which
        # judgment before disposing of it, so a bounded run is allowed between the two halves.
      | the\s+impugned\s+(?:judgment|order)[^.]{0,60}?\s+(?:is|stands?)\s+
            (?:accordingly\s+|hereby\s+)?(?:set\s+aside|upheld|affirmed|quashed|restored)
      | no\s+interference\s+(?:of\s+this\s+Court\s+)?is\s+called\s+for
      | we\s+(?:see\s+no\s+reason\s+to\s+interfere|are\s+in\s+complete\s+agreement)
      | the\s+reference\s+is\s+answered
      | we\s+accordingly\s+pass\s+the\s+following\s+order
    )
    """
)

MIN_CONFIDENCE_FOR_WEIGHT = 0.35


@dataclass
class WeightVerdict:
    """Whether the relied-on passage carried the decision, and the evidence for saying so."""

    label: str  # ratio | obiter | unclear
    method: str = "rule"  # rule | model | voice | not_assessed
    cue: str | None = None
    quote: str | None = None
    quote_verified: bool = False
    necessary_to_outcome: bool | None = None
    confidence: float = 0.0
    reason: str | None = None
    needs_review: bool = False
    prompt_version: str | None = None

    @property
    def is_obiter(self) -> bool:
        """Only a grounded classification counts. `unclear` never costs a citation a grade."""
        return self.label == "obiter"


def find_disposition(paragraphs: list[SegParagraph]) -> SegParagraph | None:
    """The paragraph disposing of the matter, searched from the end where it almost always sits."""
    for paragraph in reversed(paragraphs):
        if DISPOSITION_CUES.search(paragraph.body):
            return paragraph
    return None


def classify_weight(
    candidate: Candidate,
    claim: str,
    *,
    voice: VoiceVerdict | None = None,
    disposition: SegParagraph | None = None,
    model: StructuredModel | None = None,
) -> WeightVerdict:
    """Classify the relied-on paragraph as ratio, obiter or unclear."""
    # Ratio and obiter are both things a court holds. Counsel's argument is neither, and answering the
    # question at all would imply the passage was the court speaking when it was not.
    if voice is not None and not (voice.is_the_court or voice.is_dissent):
        return WeightVerdict(
            label="unclear",
            method="voice",
            reason=f"the passage is not the court's own reasoning ({voice.voice}), so it is neither ratio nor obiter",
        )

    declining = DECLINING_CUES.search(candidate.body)
    if declining:
        return WeightVerdict(
            label="obiter",
            method="rule",
            cue=declining.group(0).strip(),
            quote=declining.group(0).strip(),
            quote_verified=True,
            necessary_to_outcome=False,
            confidence=1.0,
            reason=(
                f"the court said {declining.group(0).strip()!r}, so the passage was not necessary to "
                "the decision"
            ),
        )

    if model is None:
        return WeightVerdict(
            label="unclear",
            method="not_assessed",
            reason="no language model is configured, so ratio and obiter were not told apart",
        )

    context = (
        f"The judgment disposes of the matter at paragraph {disposition.printed_label}:\n{disposition.body}"
        if disposition is not None
        else "The judgment's disposition is not available; judge necessity from the paragraph alone."
    )
    try:
        answer = model.invoke(
            WEIGHT_PROMPT.format(
                claim=claim.strip(),
                label=candidate.printed_label or f"#{candidate.seq}",
                paragraph=candidate.body,
                disposition=context,
            )
        )
    except Exception as exc:  # noqa: BLE001 - a provider outage must not lose the other detectors
        return WeightVerdict(
            label="unclear",
            method="not_assessed",
            reason=f"every configured model provider failed ({type(exc).__name__}), so weight was not assessed",
        )
    if not isinstance(answer, WeightAssessment):
        return WeightVerdict(
            label="unclear",
            method="not_assessed",
            reason="the model did not return a usable classification",
        )

    verdict = WeightVerdict(
        label=answer.label,
        method="model",
        quote=(answer.quote or "").strip() or None,
        necessary_to_outcome=answer.necessary_to_outcome,
        confidence=answer.confidence,
        reason=answer.reason,
        prompt_version=WEIGHT_VERSION,
    )
    if answer.label == "unclear":
        return verdict

    # Quote-or-nothing, as everywhere else the model is allowed to change a verdict.
    if not verdict.quote or word_count(verdict.quote) < MIN_QUOTE_WORDS:
        verdict.label = "unclear"
        verdict.needs_review = True
        verdict.reason = (
            f"the model answered {answer.label!r} without a quote long enough to verify, so weight is "
            "recorded as unclear"
        )
        return verdict

    match = find_quote(verdict.quote, candidate.body)
    if not match.found:
        verdict.label = "unclear"
        verdict.needs_review = True
        verdict.reason = (
            f"the model answered {answer.label!r} but its quote does not appear in paragraph "
            f"{candidate.printed_label}, so weight is recorded as unclear"
        )
        return verdict

    verdict.quote_verified = True
    if answer.confidence and answer.confidence < MIN_CONFIDENCE_FOR_WEIGHT:
        verdict.needs_review = True
        verdict.reason = (
            f"{verdict.reason or ''} The model's own confidence was {answer.confidence:.2f}."
        ).strip()
    return verdict
