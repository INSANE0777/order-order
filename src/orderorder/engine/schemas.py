"""Structured outputs the language model is allowed to return.

Every model call in the engine is constrained to one of these schemas. Nothing here is trusted on its
own: a quote the model returns is checked against the stored judgment text by `engine.quotes` before
any claim can be called supported, and a support level that arrives without a verified quote is
overridden. The schemas exist to make the model's answer *checkable*, not to make it credible.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SupportLevel = Literal["full", "partial", "none", "contradicted"]
Modality = Literal["must", "may", "should", "observed", "unclear"]


class AtomicClaim(BaseModel):
    """One indivisible assertion pulled out of a proposition in a brief."""

    text: str = Field(description="The single assertion, stated in one sentence.")
    subject: str | None = Field(default=None, description="What the assertion is about.")
    conditions_stated: list[str] = Field(
        default_factory=list,
        description="Conditions or qualifications the brief itself attaches to the assertion.",
    )
    modality: Modality = Field(
        default="unclear",
        description="How strongly the brief puts it: must, may, should, or merely observed.",
    )
    generality: str | None = Field(
        default=None,
        description="How broadly the brief states it, for example 'all commercial contracts'.",
    )


class ClaimDecomposition(BaseModel):
    """A proposition split into the assertions it actually makes."""

    claims: list[AtomicClaim] = Field(
        default_factory=list, description="One entry per distinct assertion. Do not merge or invent."
    )


class ScopeAssessment(BaseModel):
    """The model's reading of whether one paragraph supports one claim, and how far.

    `quote` must be copied verbatim from the paragraph. It is string-matched afterwards, so an
    approximate or remembered quote fails and the claim is not treated as supported.
    """

    paragraph_label: str | None = Field(
        default=None,
        description="Printed label of the paragraph relied on, exactly as given in the candidates, or null.",
    )
    quote: str | None = Field(
        default=None,
        description="A verbatim sentence copied from that paragraph, at least six words, or null.",
    )
    support: SupportLevel = Field(
        description="full if the paragraph states the claim as broadly as the brief does; "
        "partial if it states it more narrowly; none if it does not state it; "
        "contradicted if it states the opposite."
    )
    dropped_conditions: list[str] = Field(
        default_factory=list,
        description="Conditions the court attached that the brief's claim leaves out.",
    )
    court_modality: Modality = Field(default="unclear", description="How strongly the court put it.")
    court_scope: str | None = Field(
        default=None, description="The situation the court confined its statement to, if any."
    )
    gap: str | None = Field(
        default=None, description="One sentence naming the difference between claim and holding."
    )
    narrowed_proposition: str | None = Field(
        default=None, description="A rewrite of the claim that the paragraph does support."
    )
    # Nullable, and not defaulted to zero. A model that omits the field has made no claim about its
    # confidence; one that answers 0.0 has claimed none. Collapsing the two into 0.0 means either
    # treating silence as certainty or treating it as doubt, and both are wrong. Gemini omits it.
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="How sure you are, 0 to 1. Omit only if you genuinely cannot say.",
    )


class VoiceAssessment(BaseModel):
    """Whose words a paragraph carries. A passage can be in a judgment without being the court's view."""

    voice: Literal["court", "counsel_argument", "lower_court", "quoted_precedent", "headnote", "unclear"] = (
        Field(description="Whose words the paragraph carries.")
    )
    endorsed: bool | None = Field(
        default=None,
        description="If the paragraph quotes another source, whether this court adopted it or rejected it.",
    )
    reason: str | None = Field(default=None, description="One sentence of justification.")


class WeightAssessment(BaseModel):
    """Was the proposition necessary to the outcome, or a remark made along the way?

    `quote` must be copied verbatim from the paragraph, as in `ScopeAssessment`. A classification of
    `obiter` that cannot be grounded in the text is downgraded to `unclear`, because reporting a
    holding as a passing remark is as damaging as the reverse.
    """

    label: Literal["ratio", "obiter", "unclear"] = Field(
        description="ratio if the statement was necessary to the court's decision; "
        "obiter if it was said along the way and the outcome would stand without it; "
        "unclear if the paragraph does not show which."
    )
    necessary_to_outcome: bool | None = Field(
        default=None,
        description="Whether the decision would have to change if this statement were removed.",
    )
    quote: str | None = Field(
        default=None,
        description="A verbatim sentence from the paragraph showing why, at least six words, or null.",
    )
    reason: str | None = Field(default=None, description="One sentence of justification.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ApplicabilityAssessment(BaseModel):
    """Whether the cited case governs the facts of the matter actually before the court.

    `quote` must be copied verbatim from the judgment, and is required when the answer is
    `inapplicable`. Declaring an authority inapplicable is the strong claim: an advocate who believes
    it drops a good case, so the fact said to distinguish it has to be shown in the judgment's text.
    """

    status: Literal["strong", "moderate", "weak", "inapplicable"] = Field(
        description="strong if the cited case governs these facts; moderate if it applies with "
        "adjustment; weak if it is only analogous; inapplicable if the facts it turned on are "
        "materially absent here."
    )
    distinguishing_facts: list[str] = Field(
        default_factory=list,
        description="Facts the cited case turned on that are absent from, or different in, this matter.",
    )
    shared_facts: list[str] = Field(
        default_factory=list, description="Facts the two matters have in common that make it apply."
    )
    paragraph_label: str | None = Field(
        default=None, description="Printed label of the paragraph stating the distinguishing fact."
    )
    quote: str | None = Field(
        default=None,
        description="A verbatim sentence from that paragraph stating the fact, at least six words.",
    )
    reason: str | None = Field(default=None, description="One sentence of justification.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Restatement(BaseModel):
    """A proposition put in a lawyer's own words rather than the court's.

    This one is not part of the engine. It exists so the retrieval evaluation can ask a question the
    corpus cannot answer for itself: how well does search do when the words a lawyer uses and the
    words the court used share only the idea. Every other query shape the harness can build is a run
    of the judgment's own text, which measures quoted search and says nothing about paraphrase.

    Using a model to write the queries does not make the measurement circular, because the model is
    not the thing being measured: the retrieval is lexical and has never seen the model's output.
    """

    restatement: str = Field(
        description=(
            "The same proposition of law, restated as an advocate would write it in a brief, "
            "using different words from the original wherever the meaning allows."
        )
    )
    kept_terms: list[str] = Field(
        default_factory=list,
        description="Terms of art that had to be kept because no synonym carries the same meaning.",
    )
