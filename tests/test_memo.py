"""The opposing-counsel memo.

The memo is written from the verdict object and nothing else, and that is the property worth
defending: it can restate what was proved, in the voice of the person who will use it, and it cannot
say anything the checks did not establish.

The other property is the one that is easy to leave out. A memo that lists only attacks reads as an
all-clear when it is short, and a citation with no findings and no model configured has been checked
for existence and pinpoint and for nothing else. Saying so is the difference between a tool that is
trusted and one that is trusted wrongly.
"""

from __future__ import annotations

from orderorder.engine.citator import TreatmentReport
from orderorder.engine.hierarchy import HierarchyCheck
from orderorder.engine.locator import PinpointCheck
from orderorder.engine.memo import ATTACKS, SEVERITY, render_memo, write_memo
from orderorder.engine.verdict import (
    MODE_DEAD_LAW,
    MODE_PHANTOM,
    MODE_QUOTED,
    MODE_WRONG_PINPOINT,
    CitationVerdict,
    Finding,
)
from orderorder.engine.voice import VoiceVerdict


def _verdict(**kwargs) -> CitationVerdict:
    base = {
        "citation_raw": "(2019) 4 SCC 1",
        "proposition": "A misrepresentation vitiates consent.",
        "existence": "found",
        "judgment_title": "ALPHA versus BETA",
        "grade": "A",
    }
    base.update(kwargs)
    return CitationVerdict(**base)


SOUND = {
    "pinpoint": PinpointCheck("3", "ok", "16", 18, ["1", "2", "3"]),
    "voice": VoiceVerdict(voice="court_majority", method="opinion"),
    "treatment": TreatmentReport(judgment_id="j1", status="good_law"),
    "hierarchy": HierarchyCheck(status="ok"),
    "quote_verified": True,
    "support": "full",
}


def test_every_attack_comes_from_a_finding() -> None:
    verdict = _verdict(
        grade="F",
        findings=[Finding(MODE_PHANTOM, "no such case", "no judgment carries this citation")],
    )
    memo = write_memo(verdict)
    assert len(memo.attacks) == 1
    assert memo.attacks[0].mode == MODE_PHANTOM
    assert memo.attacks[0].because == "no judgment carries this citation"
    assert memo.attacks[0].fix


def test_a_citation_with_no_findings_has_nothing_to_attack() -> None:
    memo = write_memo(_verdict(**SOUND))
    assert memo.is_safe
    assert memo.worst is None
    assert not memo.attacks


def test_attacks_are_ordered_by_what_an_opponent_leads_with() -> None:
    """A shifted pinpoint is a nuisance; a case that does not exist ends the argument."""
    verdict = _verdict(
        grade="F",
        findings=[
            Finding(MODE_WRONG_PINPOINT, "pinpoint", "paragraph 73 does not exist"),
            Finding(MODE_DEAD_LAW, "overruled", "overruled in 2021"),
            Finding(MODE_PHANTOM, "no such case", "nothing carries this citation"),
        ],
    )
    assert [a.mode for a in write_memo(verdict).attacks] == [
        MODE_PHANTOM,
        MODE_DEAD_LAW,
        MODE_WRONG_PINPOINT,
    ]


def test_two_findings_of_one_kind_become_one_line_in_court() -> None:
    verdict = _verdict(
        grade="D",
        findings=[
            Finding(MODE_QUOTED, "quoted", "the paragraph number breaks the sequence"),
            Finding(MODE_QUOTED, "quoted", "the passage follows 'the High Court held'"),
        ],
    )
    memo = write_memo(verdict)
    assert len(memo.attacks) == 1
    assert "breaks the sequence" in memo.attacks[0].because
    assert "High Court held" in memo.attacks[0].because


def test_every_failure_mode_the_engine_raises_has_a_line_and_a_fix() -> None:
    """A finding with no entry falls back to a generic line, which is worth never needing."""
    for mode in SEVERITY:
        line, fix = ATTACKS[mode]
        assert line.endswith((".", "!"))
        assert fix


# --- the two halves that are easy to leave out -----------------------------------------------------


def test_what_was_checked_and_held_up_is_said_as_well_as_what_did_not() -> None:
    memo = write_memo(_verdict(**SOUND))
    joined = " ".join(memo.survives)
    assert "resolves to a judgment" in joined
    assert "paragraph cited exists" in joined
    assert "court's own words" in joined
    assert "overrules or doubts" in joined
    assert "verified word for word" in joined


def test_a_check_that_could_not_run_is_named_rather_than_passed_over() -> None:
    """Silence reads as safety. A citation nobody could assess is not a citation that passed."""
    memo = write_memo(_verdict(support="not_assessed", quote_verified=False))
    unchecked = " ".join(memo.unchecked)
    assert "needs a language model" in unchecked
    assert "no facts were supplied" in unchecked
    assert "whose words the passage carries" in unchecked


def test_a_citation_resolving_to_nothing_says_the_rest_was_unreachable() -> None:
    """Nothing after existence could be asked, and a memo listing them one by one would mislead."""
    verdict = _verdict(
        existence="not_found",
        grade="F",
        findings=[Finding(MODE_PHANTOM, "no such case", "nothing carries this citation")],
    )
    memo = write_memo(verdict)
    assert any("resolved to none" in item for item in memo.unchecked)
    assert not memo.survives


def test_a_brief_with_no_pinpoint_is_told_so() -> None:
    memo = write_memo(_verdict(pinpoint=PinpointCheck(None, "none_claimed", "16", 18, [])))
    assert any("no pinpoint" in item for item in memo.unchecked)


def test_the_rendered_memo_carries_the_grade_and_every_part() -> None:
    verdict = _verdict(
        grade="D",
        findings=[Finding(MODE_DEAD_LAW, "overruled", "overruled by a larger bench in 2021")],
        treatment=TreatmentReport(judgment_id="j1", status="good_law"),
    )
    text = "\n".join(render_memo(write_memo(verdict)))
    assert "grade D" in text
    assert "What the other side will say" in text
    assert "overruled by a larger bench in 2021" in text
    assert "What was not checked" in text
