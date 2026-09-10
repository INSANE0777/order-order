"""Rhetorical role labels: every paragraph gets one of the OpenNyAI labels by cue matching.

The classifier is a pure function over the paragraph body, so most of what these tests assert is
that the cue wording actually fires on the sentences the Supreme Court writes -- the tables were
written against real judgments, and these sentences are lifted from the same register. The DB tests
assert the pass is idempotent: a second run changes nothing, because the printed role is the better
evidence, in the same way mark_separate_opinions never adds a second opinion.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from orderorder.db.models import Judgment, Paragraph
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.roles import (
    NONE,
    ROLE_CUES,
    ROLE_ORDER,
    ROLE_PATTERNS,
    classify_role,
    mark_roles,
)
from orderorder.ingest.store import store_extracted


@pytest.mark.parametrize(
    ("expected", "text"),
    [
        ("disposition", "The appeals are accordingly allowed. No order as to costs."),
        (
            "disposition",
            "In view of the aforesaid, the impugned judgment of the High Court is set aside.",
        ),
        ("issues", "The following questions arise for consideration in this appeal:"),
        ("issues", "The substantial question of law that arises is whether the suit was barred."),
        (
            "argument_petitioner",
            "Learned counsel for the appellant submitted that the suit was barred by limitation.",
        ),
        (
            "argument_petitioner",
            "It is contended by the learned senior counsel for the petitioners that the impugned "
            "order violates Article 14.",
        ),
        (
            "argument_respondent",
            "Learned counsel for the respondent, on the other hand, supported the decree passed by "
            "the trial court.",
        ),
        (
            "argument_respondent",
            "The learned ASG appearing for the Union of India opposed the writ petition.",
        ),
        (
            "lower_court",
            "The High Court, however, held that the notice under Section 106 was validly served.",
        ),
        (
            "lower_court",
            "The trial court convicted the appellant under Section 302 of the Indian Penal Code.",
        ),
        ("statute", "Section 27 of the Indian Contract Act reads as under:"),
        ("statute", "The relevant extract of Section 14 of the Act is reproduced below:"),
        (
            "facts",
            "Briefly stated, the facts of the case are that the plaintiff was employed with the "
            "defendant from 1998 until his services were terminated.",
        ),
        (
            "facts",
            "The prosecution case, in brief, is that the accused entered the house at about 10 pm.",
        ),
        ("ratio", "We are of the considered view that the second notice was valid."),
        ("ratio", "It is well settled that a fee once levied cannot be refunded on a change of mind."),
        (
            "analysis",
            "Having heard learned counsel for the parties, we have perused the record carefully.",
        ),
        (
            "precedent_relied",
            "The decision in Kasturi Lal v. State, (1965) 1 SCR 481, was relied upon by the High Court.",
        ),
        (
            "precedent_relied",
            "This Court in Basheshar Nath laid down in no uncertain terms that a waiver of a "
            "fundamental right is contrary to the scheme of the Constitution.",
        ),
        (
            "precedent_not_relied",
            "The said decision is clearly distinguishable and has no application to the facts of this case.",
        ),
        ("none", "List the matter after four weeks."),
        ("none", "Re-notify on 14th March, 2025."),
    ],
)
def test_the_label_the_paragraph_earns(expected: str, text: str) -> None:
    assert classify_role(text) == expected


def test_a_paragraph_only_labelled_preamble_if_it_is_first() -> None:
    text = "Leave granted."
    assert classify_role(text, is_first=True) == "preamble"
    assert classify_role(text, is_first=False) == "none"


def test_the_order_tried_is_the_order_declared() -> None:
    """ROLE_CUES is derived from ROLE_ORDER, so the two cannot drift apart.

    The order is not decoration -- it is what decides that a paragraph naming both counsel and a
    precedent is counsel arguing. It used to be written out twice, once as a list nothing read and
    once as the table that actually ran, which is one edit away from disagreeing in silence.
    """
    assert [role for role, _ in ROLE_CUES] == [r for r in ROLE_ORDER if r != "preamble"]
    # `preamble` is positional, tried separately, and so has no cue set of its own.
    assert "preamble" not in ROLE_PATTERNS
    assert set(ROLE_PATTERNS) == set(ROLE_ORDER) - {"preamble"}
    # Every label the classifier can return is one the architecture declares.
    assert set(ROLE_ORDER) | {NONE} >= {role for role, _ in ROLE_CUES} | {"preamble", NONE}


def test_argument_outranks_precedent_when_counsel_does_the_citing() -> None:
    """A paragraph that is counsel citing authority is an argument, not a relied precedent."""
    text = (
        "Learned counsel for the appellant placed reliance on State of Punjab v. Bakshish Singh, "
        "(1997) 8 SCC 224, to contend that the demand notice was valid."
    )
    assert classify_role(text) == "argument_petitioner"


def test_disposition_outranks_everything_that_mentions_the_appeal_earlier() -> None:
    """A paragraph disposing of the appeal is that, whatever else it recites."""
    text = (
        "The issue, therefore, is answered. The appeals are accordingly allowed and the order of "
        "the Tribunal is set aside."
    )
    assert classify_role(text) == "disposition"


JUDGMENT_TEXT = """1. Leave granted.

2. Briefly stated, the facts of the case are that the plaintiff's services were terminated
without a departmental enquiry.

3. Learned counsel for the appellant contended that Article 311 was attracted.

4. The High Court held that no enquiry was necessary in view of the conduct rule.

5. We are of the considered view that the enquiry could not have been dispensed with.

6. The decision in State of U.P. v. Mohd. Nooh, AIR 1958 SC 86, was relied upon.

7. The appeal is allowed accordingly.
"""


def _store(session, key: str, text: str) -> Judgment:
    judgment = Judgment(
        canonical_key=key,
        court="Supreme Court of India",
        title=f"{key} ALPHA versus BETA",
        source="aws_open_data",
        source_id=key,
        bench_strength=2,
        decided_on=dt.date(2019, 6, 1),
    )
    session.add(judgment)
    session.flush()
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path=key, page_count=1, headnote="", judgment=text),
    )
    session.commit()
    return judgment


def _roles(session, judgment: Judgment) -> list[str]:
    version = judgment.versions[0]
    return [
        p.role
        for p in session.scalars(
            select(Paragraph)
            .where(Paragraph.text_version_id == version.id)
            .order_by(Paragraph.seq)
        ).all()
    ]


def test_mark_roles_labels_the_stored_judgment(session) -> None:
    judgment = _store(session, "INSC:2019:1", JUDGMENT_TEXT)

    result = mark_roles(session)

    assert result.labelled == 7
    assert result.skipped_already == 0
    labels = _roles(session, judgment)
    assert labels == [
        "preamble",
        "facts",
        "argument_petitioner",
        "lower_court",
        "ratio",
        "precedent_relied",
        "disposition",
    ]


def test_mark_roles_is_idempotent_and_relabel_redoes_it(session) -> None:
    judgment = _store(session, "INSC:2019:2", JUDGMENT_TEXT)

    mark_roles(session)
    again = mark_roles(session)
    assert again.labelled == 0
    assert again.skipped_already == 7

    relabelled = mark_roles(session, relabel=True)
    assert relabelled.labelled == 7
    assert _roles(session, judgment)[4] == "ratio"
