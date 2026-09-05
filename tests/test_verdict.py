"""Verdict assembly and the grading rubric.

The grade is a rule applied in Python, never an opinion asked of a model, so it is pinned by tests.
The distinction the tests care most about is between "checked and found wanting" and "could not be
checked": reporting the second as the first would be the overclaiming this product exists to catch.
"""

from __future__ import annotations

from orderorder.engine.locator import PinpointCheck
from orderorder.engine.scope import ScopeVerdict
from orderorder.engine.verdict import (
    MODE_MINORITY,
    MODE_NOT_THERE,
    MODE_OBITER,
    MODE_OVERSTATEMENT,
    MODE_PHANTOM,
    MODE_QUOTED,
    MODE_WRONG_PINPOINT,
    MODE_WRONG_VOICE,
    build_verdict,
)
from orderorder.engine.voice import VoiceVerdict
from orderorder.engine.weight import WeightVerdict
from orderorder.resolver import Resolution

CITATION = "(2019) 4 SCC 1"
CLAIM = "A misrepresentation vitiates consent."

FOUND = Resolution(status="found", method="exact", judgment_id="j1", canonical_key="INSC:2019:770", score=100.0)
NOT_FOUND = Resolution(status="not_found", method="exact", note="no judgment carries the alias SCC:2019:4:1")
BY_PARTY = Resolution(
    status="found", method="party_name", judgment_id="j1", canonical_key="INSC:2019:770", score=97.0,
    note="citation string not in the corpus; matched on party names instead",
)

GOOD_PINPOINT = PinpointCheck("3", "ok", "16", 18, ["1", "2", "3"])
BAD_PINPOINT = PinpointCheck("73", "out_of_range", "16", 18, ["1", "2", "3"], note="numbering stops at 16")


def _scope(**kwargs) -> ScopeVerdict:
    base = {
        "claim": CLAIM,
        "support": "full",
        "model_support": "full",
        "quote": "A misrepresentation vitiates consent only where it induced",
        "quote_verified": True,
        "matched_paragraph_label": "3",
        "paragraph_label": "3",
    }
    base.update(kwargs)
    return ScopeVerdict(**base)


def test_a_sound_citation_grades_a() -> None:
    verdict = build_verdict(CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=_scope())
    assert verdict.grade == "A"
    assert verdict.is_sound
    assert verdict.findings == []


def test_phantom_is_f_and_terminal() -> None:
    verdict = build_verdict(CITATION, CLAIM, NOT_FOUND)
    assert verdict.grade == "F"
    assert verdict.existence == "not_found"
    assert [f.mode for f in verdict.findings] == [MODE_PHANTOM]
    assert verdict.needs_review


def test_mis_cite_is_reported_when_only_party_names_matched() -> None:
    verdict = build_verdict(CITATION, CLAIM, BY_PARTY, pinpoint=GOOD_PINPOINT, scope=_scope())
    assert any(f.mode == 2 for f in verdict.findings)
    assert verdict.grade == "C"


def test_bad_pinpoint_drops_the_grade() -> None:
    verdict = build_verdict(CITATION, CLAIM, FOUND, pinpoint=BAD_PINPOINT, scope=_scope())
    assert any(f.mode == MODE_WRONG_PINPOINT for f in verdict.findings)
    assert verdict.grade == "C"


def test_overstatement_is_reported_with_the_conditions() -> None:
    scope = _scope(
        support="partial",
        dropped_conditions=["where the misrepresentation induced the contract"],
        gap="The court confined the rule to inducement.",
    )
    verdict = build_verdict(CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=scope)
    finding = next(f for f in verdict.findings if f.mode == MODE_OVERSTATEMENT)
    assert "induced the contract" in finding.detail
    assert verdict.grade == "C"


def test_unsupported_is_f() -> None:
    scope = _scope(support="none", model_support="none", quote=None, quote_verified=False)
    verdict = build_verdict(CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=scope)
    assert verdict.grade == "F"
    assert any(f.mode == MODE_NOT_THERE for f in verdict.findings)


def test_contradicted_is_f() -> None:
    scope = _scope(support="contradicted", model_support="contradicted", gap="The court held the opposite.")
    verdict = build_verdict(CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=scope)
    assert verdict.grade == "F"


def test_not_assessed_is_not_reported_as_unsupported() -> None:
    """No model available. That is a gap in the check, not a finding against the brief."""
    scope = ScopeVerdict(
        claim=CLAIM, support="none", model_support="not_assessed",
        needs_review=True, review_reason="no language model is configured",
    )
    verdict = build_verdict(CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=scope)
    assert verdict.support == "not_assessed"
    assert not any(f.mode == MODE_NOT_THERE for f in verdict.findings)
    assert verdict.grade != "F"
    assert verdict.needs_review


def test_provider_failure_is_also_not_a_finding() -> None:
    scope = ScopeVerdict(
        claim=CLAIM, support="none", model_support="error",
        needs_review=True, review_reason="every configured model provider failed",
    )
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=scope)
    assert verdict.support == "not_assessed"
    assert verdict.findings == []


def test_quoted_passage_is_flagged() -> None:
    verdict = build_verdict(
        CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=_scope(), likely_quoted=True
    )
    assert any(f.mode == MODE_QUOTED for f in verdict.findings)
    assert verdict.grade == "B"


def test_a_quote_verified_away_from_the_brief_s_pinpoint_is_reported() -> None:
    scope = _scope(wrong_pinpoint=True, paragraph_label="5", matched_paragraph_label="3")
    verdict = build_verdict(
        CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=scope, claimed_pinpoint="5"
    )
    finding = next(f for f in verdict.findings if f.mode == MODE_WRONG_PINPOINT)
    assert "paragraph 3" in finding.detail
    assert "paragraph 5" in finding.detail


def test_a_pinpoint_covering_the_paragraph_is_not_a_wrong_pinpoint() -> None:
    """A brief citing "paras 3-6" has not misdirected anyone by a quote verifying in paragraph 3."""
    scope = _scope(wrong_pinpoint=True, paragraph_label="6", matched_paragraph_label="3")
    verdict = build_verdict(
        CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=scope, claimed_pinpoint="3-6"
    )
    assert not any(f.mode == MODE_WRONG_PINPOINT for f in verdict.findings)


def test_a_model_disagreeing_with_its_own_quote_asks_for_review_not_a_finding() -> None:
    """With no pinpoint in the brief there is no pinpoint to be wrong; there is something to look at.

    `wrong_pinpoint` records that the model named one paragraph and its quote verified in another.
    That is the model disagreeing with itself, and reporting it as a defect in the citation would
    mark an advocate down for the engine's own uncertainty.
    """
    scope = _scope(wrong_pinpoint=True, paragraph_label="5", matched_paragraph_label="3")
    verdict = build_verdict(CITATION, CLAIM, FOUND, pinpoint=GOOD_PINPOINT, scope=scope)
    assert not any(f.mode == MODE_WRONG_PINPOINT for f in verdict.findings)
    assert verdict.needs_review
    assert "paragraph 3" in (verdict.review_reason or "")


def test_deductions_accumulate() -> None:
    scope = _scope(support="partial", gap="narrower than claimed")
    verdict = build_verdict(CITATION, CLAIM, FOUND, pinpoint=BAD_PINPOINT, scope=scope, likely_quoted=True)
    assert len(verdict.findings) == 3
    assert verdict.grade == "F"


def test_ambiguous_resolution_asks_for_review() -> None:
    ambiguous = Resolution(status="ambiguous", method="party_name", note="two titles match")
    verdict = build_verdict(CITATION, CLAIM, ambiguous)
    assert verdict.needs_review
    assert verdict.grade == "C"


def test_findings_render_with_their_mode_number() -> None:
    verdict = build_verdict(CITATION, CLAIM, NOT_FOUND)
    assert str(verdict.findings[0]).startswith("[1] no such case")


# --- voice, opinion and weight ------------------------------------------------


def _voice(**kwargs) -> VoiceVerdict:
    base = {"voice": "court_majority", "opinion_kind": "majority"}
    base.update(kwargs)
    return VoiceVerdict(**base)


def test_the_courts_own_words_cost_nothing() -> None:
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=_scope(), voice=_voice(), pinpoint=GOOD_PINPOINT)
    assert verdict.grade == "A"
    assert not verdict.findings


def test_a_dissent_cited_as_the_holding_drops_to_d() -> None:
    voice = _voice(voice="court_dissent", opinion_kind="dissenting", opinion_author="Nariman, J.")
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=_scope(), voice=voice)
    assert any(f.mode == MODE_MINORITY for f in verdict.findings)
    assert verdict.grade == "D"
    assert "Nariman" in str(verdict.findings[0])


def test_counsels_argument_cited_as_the_holding_drops_to_d() -> None:
    voice = _voice(voice="counsel_argument", cue="it was contended", reason="the passage follows a submission")
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=_scope(), voice=voice)
    assert any(f.mode == MODE_WRONG_VOICE for f in verdict.findings)
    assert verdict.grade == "D"


def test_a_voice_finding_never_improves_a_worse_grade() -> None:
    """The floor pushes a grade down, never up: an unsupported citation stays at F."""
    scope = _scope(support="none", model_support="none", quote_verified=False)
    voice = _voice(voice="counsel_argument")
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=scope, voice=voice)
    assert verdict.grade == "F"


def test_a_quoted_precedent_adopted_by_the_court_is_not_a_finding() -> None:
    voice = _voice(voice="quoted_precedent", endorsed=True)
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=_scope(), voice=voice)
    assert not verdict.findings
    assert verdict.grade == "A"


def test_obiter_drops_one_grade() -> None:
    weight = WeightVerdict(label="obiter", method="rule", reason="the court declined to decide the point")
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=_scope(), voice=_voice(), weight=weight)
    assert any(f.mode == MODE_OBITER for f in verdict.findings)
    assert verdict.grade == "B"


def test_unclear_weight_costs_nothing() -> None:
    weight = WeightVerdict(label="unclear", method="not_assessed", reason="no model configured")
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=_scope(), voice=_voice(), weight=weight)
    assert verdict.grade == "A"
    assert not verdict.findings


def test_the_out_of_sequence_heuristic_yields_to_the_voice_check() -> None:
    """Both look at the same thing; reporting both would mark one passage down twice."""
    voice = _voice(voice="quoted_precedent", method="sequence")
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=_scope(), voice=voice, likely_quoted=True)
    assert [f.mode for f in verdict.findings] == [MODE_WRONG_VOICE]


def test_the_heuristic_still_speaks_when_no_paragraph_could_be_attributed() -> None:
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=_scope(), voice=None, likely_quoted=True)
    assert any(f.mode == MODE_QUOTED for f in verdict.findings)


def test_a_dissent_is_reported_even_when_support_was_never_assessed() -> None:
    """With no model the extent of support is unknown, but whose words they are is still known."""
    scope = ScopeVerdict(
        claim=CLAIM,
        support="none",
        model_support="not_assessed",
        needs_review=True,
        review_reason="no language model is configured",
    )
    voice = _voice(voice="court_dissent", opinion_kind="dissenting")
    verdict = build_verdict(CITATION, CLAIM, FOUND, scope=scope, voice=voice, claimed_pinpoint="89")
    assert verdict.support == "not_assessed"
    assert any(f.mode == MODE_MINORITY for f in verdict.findings)
    assert verdict.grade == "D"
