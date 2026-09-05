"""A second opinion on whether the quote is really the authority for the claim.

`docs/PRD.md` §5 says the engine is adversarial. That principle is already carried by `engine.memo`,
which argues against a citation once it has been graded. This module applies it one step earlier, to
the grading itself, and it exists because of a specific measured failure.

Run against a live model, the drafting gate bound three propositions to paragraphs that did not
support them. Every quote was genuine, verbatim, correctly attributed and from good law, so
quote-or-nothing held and nothing structural was wrong with any of it. The model had simply answered
`full` where the honest answer was `partial` or `none`. One of the three:

    claim: "A subsequent purchaser who holds a prior agreement to sell is a necessary party to a
            suit for specific performance."
    quote: "...two things are necessary for the adjudication, they are; (i) ... readiness and
            willingness ... and (ii) whether the subsequent transferee was having prior knowledge..."

The sentence is about what must be *decided*. The claim is about who must be *joined*. Nothing in the
verdict's shape reveals that; only reading the two texts against each other does.

**Why a second call rather than a better prompt.** The first model is asked to grade, and a model
asked to grade a thing it has just been shown will find a way to grade it. This one is never shown the
first answer and is never asked whether it agrees. It is asked what the claim asserts that the
sentence does not state — a question whose easy answer is a list, not an endorsement. The asymmetry is
the point: "what is missing?" makes a model look, where "is this right?" makes it nod.

**What it may do.** It may take support down and it may never put support up. A challenge that finds a
gap moves `full` to `partial` and asks for review; one that finds nothing changes nothing at all. That
follows the same rule as the rest of the engine — between two readings, the one claiming less stands —
and it means a broken or absent challenge model can only ever make the engine more cautious.

**What it costs.** One extra model call per citation that would otherwise have been supported, and
only those: a refusal, an unverified quote or a citation that never got that far pays nothing.

**It does not work with Gemini 2.5 Flash, and it is off.** Measured on seven cases: four where the
sentence plainly does state the claim, including one where the claim *is* the sentence word for word,
and the three overstatements above that a live run had bound.

    prompt                     controls upheld   overstatements caught
    v1, written as opposing
      counsel, "saying no
      costs nothing"                  0 of 4                  3 of 3
    v2, balanced, symmetric
      guidance both ways              4 of 4                  0 of 2

The v2 run was cut off by its timeout before the third overstatement, so that cell is two cases and
not three. It does not change the reading: the two it did reach are the clearest of them — a sentence
about what must be *decided* offered for a claim about who must be *joined*, and a claim that drops
the "unless" the sentence attaches — and v2 upheld both.

The model is not reading the two texts against each other. It is following whichever way the prompt
leans: tell it that no is the safe answer and it says no to its own quote; take the thumb off the
scale and it says yes to a sentence about a different question. A check whose answer is set by its
framing is not a check, and shipping it on would have replaced one wrong answer with another and
called it verification.

So `challenge_model` defaults to `None` everywhere and `orderorder draft --challenge` turns it on.
What the measurement rules out is this task on a small fast model; what it leaves open is the same
seam with a stronger one, which is a flag and a re-run of the numbers above. What it does *not*
license is tuning the prompt until the seven cases pass -- seven cases chosen after seeing the
failures would then be measuring the tuning, and the honest version of this experiment needs the gold
set and an overnight run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orderorder.engine.prompts import CHALLENGE_PROMPT, CHALLENGE_VERSION
from orderorder.engine.providers import StructuredModel
from orderorder.engine.schemas import ChallengeAssessment

# What the challenge concluded. `upheld` means it could not fault the quote; `gap` means it named
# something the claim asserts and the quote does not; `not_run` means there was no model, or the
# model failed, and the engine says so rather than treating silence as agreement.
UPHELD = "upheld"
GAP = "gap"
NOT_RUN = "not_run"


@dataclass
class Challenge:
    """The second reading, and what it found."""

    status: str
    missing: list[str] = field(default_factory=list)
    reason: str | None = None
    prompt_version: str | None = None

    @property
    def found_a_gap(self) -> bool:
        return self.status == GAP

    def describe(self) -> str:
        """The finding, as a sentence an advocate can act on."""
        if self.status != GAP:
            return ""
        if self.reason:
            return self.reason.strip()
        if self.missing:
            return "the quote does not state: " + "; ".join(m.strip() for m in self.missing[:3])
        return "a second reading found the quote does not state the claim"


def challenge(claim: str, quote: str, model: StructuredModel | None) -> Challenge:
    """Ask, independently, what the claim asserts that the quote does not state."""
    if model is None or not claim.strip() or not quote.strip():
        return Challenge(NOT_RUN, reason="no second reading was made")

    try:
        answer = model.invoke(CHALLENGE_PROMPT.format(claim=claim.strip(), quote=quote.strip()))
    except Exception as exc:  # noqa: BLE001 - a provider outage must not lose the first reading
        # Not a gap. An outage is not evidence of anything, and treating it as one would refuse
        # citations for the sake of a failed HTTP request.
        return Challenge(NOT_RUN, reason=f"the second reading could not be made ({type(exc).__name__})")

    if not isinstance(answer, ChallengeAssessment):
        return Challenge(NOT_RUN, reason="the second reading did not come back in a usable form")

    missing = [m.strip() for m in answer.missing if m and m.strip()]
    if answer.states_the_claim and not missing:
        return Challenge(UPHELD, prompt_version=CHALLENGE_VERSION)

    # A model that answers "yes, it states the claim" and then lists what is missing has contradicted
    # itself, and the list is the half with the reasoning attached. The same rule as everywhere else.
    return Challenge(
        GAP,
        missing=missing,
        reason=(answer.reason or "").strip() or None,
        prompt_version=CHALLENGE_VERSION,
    )
