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
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


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
