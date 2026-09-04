"""The third question, with the model's answer scripted rather than generated.

    uv run python demo/scripted_model.py

Extent of support is the one check that needs a language model, and this machine has no provider key
and no model pulled. So this script runs the **real** engine — the real resolver, the real locator,
the real quote verifier, the real grading rubric — against the **real** judgment text in the knowledge
base, and supplies the model's answer from a script instead of a provider.

Everything except the four scripted answers below is the product. The point of the exercise is that
the engine's treatment of a model answer does not depend on which model produced it: two of the four
answers here are confident and wrong, and the engine catches both by string-matching the quote against
the stored judgment. Swap in a real provider key and the same code runs unchanged.

Nothing here is evidence about any particular model's accuracy. It is evidence about what the engine
does with an answer once it has one.
"""

from __future__ import annotations

from sqlalchemy import select

from orderorder.citations.grammar import extract_citations
from orderorder.db.models import Judgment
from orderorder.db.session import get_session
from orderorder.engine.graph import verify_citation
from orderorder.engine.schemas import ScopeAssessment

CASE = "2019 INSC 770"  # Gurmit Singh Bhatia v. Kiran Kant Robinson, [2019] 9 S.C.R. 593

# Paragraph 7 of that judgment, verbatim:
#
#   "In view of the above and for the reasons stated above, we are in complete agreement with the
#    view taken by the High Court. No interference of this Court is called for. The appellant cannot
#    be impleaded as a defendant in the suit for specific performance of the contract between the
#    original plaintiffs and original defendant no.1 against the wish of the plaintiffs."

TRUE_QUOTE = (
    "The appellant cannot be impleaded as a defendant in the suit for specific performance of the "
    "contract between the original plaintiffs and original defendant no.1 against the wish of the "
    "plaintiffs"
)


class ScriptedModel:
    """Returns a fixed answer. Stands where `build_structured(ScopeAssessment)` would return a model."""

    def __init__(self, answer: ScopeAssessment) -> None:
        self.answer = answer

    def invoke(self, prompt: str) -> ScopeAssessment:
        return self.answer


CASES: list[tuple[str, str, str, ScopeAssessment]] = [
    (
        "1. Honest and accurate",
        "The appellant cannot be impleaded as a defendant in the suit for specific performance "
        f"against the wish of the plaintiffs: {CASE}, para 7.",
        "The model reads paragraph 7 and copies the sentence that carries the claim. The quote is "
        "found in the stored judgment, so the claim is supported and the citation is sound.",
        ScopeAssessment(
            paragraph_label="7",
            quote=TRUE_QUOTE,
            support="full",
            court_modality="must",
            confidence=0.92,
        ),
    ),
    (
        "2. Overstated by the brief",
        "No third party may ever be impleaded in a suit for specific performance in any circumstances "
        f"whatsoever: {CASE}, para 7.",
        "The court decided this appellant, on these facts, against the plaintiffs' wish. The brief "
        "turns that into a rule admitting no exception. The quote still verifies, so the finding is "
        "not that the case is fabricated but that the brief claims more than the court held: mode 8, "
        "with the proposition the judgment does support offered as the fix.",
        ScopeAssessment(
            paragraph_label="7",
            quote=TRUE_QUOTE,
            support="partial",
            dropped_conditions=[
                "the impleadment was sought against the wish of the plaintiffs",
                "the party sought to be added claimed under an independent title, not under the contract",
            ],
            court_modality="observed",
            court_scope="a suit for specific performance where the stranger claims independent title",
            gap="The court decided who may not be added to this suit; it did not lay down a rule for every case.",
            narrowed_proposition=(
                "A stranger to the contract claiming under an independent title cannot be impleaded in a "
                "suit for specific performance against the wish of the plaintiff."
            ),
            confidence=0.88,
        ),
    ),
    (
        "3. Fabricated quote, high confidence",
        f"A subsequent purchaser is always a necessary party to a suit for specific performance: {CASE}, para 7.",
        "The model is confident and the sentence reads like a judgment, but no such sentence is in "
        "the text. The quote fails the string match, so the claim is recorded as unsupported "
        "whatever the model's confidence. This is the check that makes 'supported' mean something.",
        ScopeAssessment(
            paragraph_label="7",
            quote=(
                "A subsequent purchaser holding a prior agreement to sell is a necessary party and must "
                "be impleaded in a suit for specific performance"
            ),
            support="full",
            confidence=0.95,
        ),
    ),
    (
        "4. Right sentence, wrong paragraph",
        f"The appellant cannot be impleaded against the wish of the plaintiffs: {CASE}, para 16.",
        "The model names paragraph 16, but the sentence it copied is in paragraph 7. The quote "
        "verifies, so the claim stands; the pinpoint does not, so the brief is told where the text "
        "actually is. A wrong pinpoint and an invented quote are different mistakes and get different "
        "verdicts.",
        ScopeAssessment(
            paragraph_label="16",
            quote=TRUE_QUOTE,
            support="full",
            confidence=0.9,
        ),
    ),
]


def main() -> None:
    with get_session() as session:
        judgment = session.scalars(select(Judgment).where(Judgment.canonical_key == "INSC:2019:770")).first()
        if judgment is None:
            raise SystemExit("run: orderorder ingest metadata 2019 && orderorder ingest text INSC:2019:770")

        for title, sentence, commentary, answer in CASES:
            citation = extract_citations(sentence)[0]
            verdict = verify_citation(session, citation, sentence, ScriptedModel(answer))

            print("=" * 100)
            print(f"{title}")
            print("=" * 100)
            print(f"  brief says      : {sentence}")
            print(f"  model answered  : support={answer.support!r} para={answer.paragraph_label!r} "
                  f"confidence={answer.confidence}")
            print(f'  model quoted    : "{(answer.quote or "")[:88]}..."')
            print()
            print(f"  ENGINE VERDICT  : grade {verdict.grade}   support={verdict.support}   "
                  f"quote_verified={verdict.quote_verified}")
            if verdict.paragraph_label:
                print(f"  paragraph       : {verdict.paragraph_label} "
                      f"(brief cited {verdict.claimed_pinpoint}) voice={verdict.voice.voice if verdict.voice else '-'}")
            for finding in verdict.findings:
                print(f"  finding         : {finding}")
            if verdict.needs_review:
                print(f"  needs review    : {verdict.review_reason}")
            if verdict.scope and verdict.scope.narrowed_proposition:
                print(f"  supported instead: {verdict.scope.narrowed_proposition}")
            print()
            print(f"  why             : {commentary}")
            print()


if __name__ == "__main__":
    main()
