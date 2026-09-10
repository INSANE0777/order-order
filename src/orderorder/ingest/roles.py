"""Rhetorical role labels for stored paragraphs.

Every paragraph carries one of the OpenNyAI labels the architecture commits to (docs/ARCHITECTURE.md
§3.2): preamble, facts, lower_court, issues, argument_petitioner, argument_respondent, statute,
precedent_relied, precedent_not_relied, analysis, ratio, disposition, none. The labels exist because
`ratio`, `precedent_relied` and `precedent_not_relied` map directly onto the weight and voice checks.

This is a cue classifier, not a model: the same philosophy as the rest of the no-model engine. A cue
classifier is wrong in the same way a first-year reader is wrong -- it over-reads phrases -- and it
is fully inspectable, which matters more here than the last few points of accuracy. The cues were
written against the wording of real Supreme Court judgments in the corpus. Unknown paragraphs are
labelled `none`, which is the honest label for a sentence like "List after four weeks." -- the
classifier abstains rather than guesses, as weight.py does for ratio vs obiter.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import bindparam, select
from sqlalchemy.orm import Session

from orderorder.db.models import JudgmentTextVersion, Paragraph
from orderorder.engine.weight import DISPOSITION_CUES

# The roles, in the order the classifier tries them: the most specific wording wins. A paragraph
# that says both "learned counsel for the appellant" and "placed reliance on" is counsel arguing,
# so argument sits above precedent; a paragraph that disposes of the appeal is that, whatever else
# it mentions, so disposition sits at the top (after the headnote, which is positional).
ROLE_ORDER = [
    "preamble",
    "disposition",
    "issues",
    "argument_petitioner",
    "argument_respondent",
    "lower_court",
    "statute",
    "facts",
    "ratio",
    "analysis",
    "precedent_not_relied",
    "precedent_relied",
]

PREAMBLE_CUES = re.compile(
    r"""(?ix)
    (?: leave\s+granted
      | special\s+leave\s+(?:to\s+)?appeal
      | petition(?:\(s\))?\s+for\s+special\s+leave
      | civil\s+(?:appeal|writ)\s+no\.?\s*(?:of|s?l\.p)
      | writ\s+petition\s*\(?(?:c|cr)\)?\s*(?:no|of)
      | transfer\s+petition
      | review\s+petition
      | contempt\s+petition
      | under\s+article\s+32
      | judgment\s+reserved
    )
    """
)

ISSUES_CUES = re.compile(
    r"""(?ix)
    (?: questions?\s+(?:of\s+law\s+)?
          (?:that\s+arise|arise|arising|for\s+consideration|for\s+determination|involved)
      | the\s+(?:following\s+)?(?:substantial\s+)?questions?\s+(?:of\s+law\s+)?(?:arise|are)
      | the\s+(?:following\s+)?issues?\s+(?:arise|for|that\s+arise|are\s+framed)
      | (?:issues?|points?)\s+(?:framed\s+)?for\s+(?:consideration|determination)
      | following\s+questions
      | the\s+short\s+question
      | the\s+point\s+(?:that\s+)?(?:falls|arises|for)
      | what\s+(?:falls|is)\s+for\s+(?:consideration|decision)
    )
    """
)

ARGUMENT_PETITIONER_CUES = re.compile(
    r"""(?ix)
    (?: (?:learned\s+)?
        (?:counsel|senior\s+counsel|asc?|asg|sg|ag|advocate)
        \s+(?:for|appearing\s+for|on\s+behalf\s+of)\s+the\s+
        (?:petitioners?|appellants?|accused|complainant|writ\s+petitioners?|applicants?)
      | (?:counsel|mr\.?|ms\.?|learned\s+counsel)\s+for\s+the\s+(?:petitioners?|appellants?)
      | it\s+is\s+contended\s+by\s+the\s+(?:petitioners?|appellants?|learned)
      | the\s+(?:petitioners?|appellants?)'?s?\s+(?:submission|contention|case)\s+is
      | submission\s+of\s+(?:mr\.?|ms\.?|the\s+)?(?:learned\s+)?(?:counsel|asg|sg|asc)
        [^.]{0,40}(?:for|appearing\s+for)\s+the\s+(?:petitioners?|appellants?|accused)
      | (?:the\s+)?(?:petitioners?|appellants?)\s+(?:submit|contend|argue)
    )
    """
)

ARGUMENT_RESPONDENT_CUES = re.compile(
    r"""(?ix)
    (?: (?:learned\s+)?
        (?:counsel|senior\s+counsel|asc?|asg|sg|ag|advocate)
        \s+(?:for|appearing\s+for|on\s+behalf\s+of)\s+the\s+
        (?:respondents?|state|defendant|union\s+of\s+india|uoi|complainant|
            authorities?|commission|board|bank|corporation)
      | (?:counsel|mr\.?|ms\.?|learned\s+counsel)\s+for\s+the\s+(?:respondents?|state|defendant|uoi)
      | the\s+(?:respondents?)?'?s?\s+(?:submission|contention|case)\s+is
      | (?:the\s+)?respondents?\s+(?:submit|contend|argue|support)
      | it\s+is\s+contended\s+by\s+the\s+(?:respondents?|state|learned\s+(?:asg|sg|ag|counsel))
    )
    """
)

LOWER_COURT_CUES = re.compile(
    r"""(?ix)
    (?: (?:the\s+)?(?:high\s+court|trial\s+court|sessions?\s+(?:court|judge)|tribunal|
          division\s+bench|single\s+judge|learned\s+single\s+judge|labour\s+court|
          consumer\s+(?:commission|forum)|district\s+(?:court|judge|forum)|motor\s+accidents?\s+tribunal)
        [^.]{0,80}?\s+
        (?:held|observed|was\s+of\s+the\s+view|convicted|acquitted|dismissed|allowed|
           set\s+aside|quashed|remanded|answered|concurred|took\s+the\s+view|upheld|refused)
      | the\s+(?:high\s+court|trial\s+court|tribunal)\s+(?:came\s+to\s+(?:hold|conclude)|proceeded)
      | (?:conviction|sentence|order|judgment|decree|award)\s+(?:of|by)\s+the\s+
        (?:high\s+court|trial\s+court|sessions?\s+(?:court|judge)|tribunal|single\s+judge)
    )
    """
)

STATUTE_CUES = re.compile(
    r"""(?ix)
    (?: (?:reads?|provides?)\s+as\s+(?:under|follows)
      | extract\s+of\s+(?:section|article|rule|provision)
      | (?:section|article|rule)\s+[0-9ivxlc]+\b[^.]{0,60}?\s+(?:of\s+the\s+\S+\s+act\s+)?
        (?:reads|provides|runs)\s+(?:as\s+)?(?:under|follows)
      | the\s+(?:relevant\s+)?provisions?\s+of\s+(?:section|article|rule)
        \s+[0-9ivxlc]+\b[^.]{0,60}?\s+(?:are|is)\s+(?:extracted|reproduced|quoted)
      | for\s+convenience.{0,40}(?:extract|reproduc)
    )
    """
)

FACTS_CUES = re.compile(
    r"""(?ix)
    (?: (?:brief\s+|short\s+|relevant\s+)?facts\s+(?:of\s+the\s+case|in\s+brief|leading|giving\s+rise)
      | the\s+facts\s+(?:are|as\s+follows|relate|disclosed)
      | briefly\s+(?:stated|put),?\s+the\s+facts
      | the\s+(?:prosecution\s+|complainant'?s\s+)?case,\s+(?:in\s+(?:brief|short|nutshell))
      | the\s+prosecution\s+(?:case|story|version)
      | shorn\s+of\s+(?:details|unnecessary)
      | facts\s+of\s+the\s+(?:case|present\s+case|matter)
      | (?:undisputed|admitted|broad)\s+facts\s+(?:are|of)
      | to\s+(?:briefly\s+)?narrate\s+the\s+facts
      | the\s+case\s+of\s+the\s+(?:complainant|prosecution|petitioner|appellant)\s+in\s+(?:brief|short)
    )
    """
)

RATIO_CUES = re.compile(
    r"""(?ix)
    (?: we\s+are\s+of\s+the\s+(?:clear\s+|considered\s+|firm\s+|considered\s+)?view
      | (?:in|as\s+per)\s+our\s+(?:considered\s+)?(?:opinion|view)
      | it\s+is\s+(?:well\s+)?settled\s+(?:law|position|that)
      | (?:it\s+is|we\s+)?held\s+that
      | we\s+hold\s+that
      | the\s+proposition\s+(?:that\s+)?(?:emerges|follows|is)
      | the\s+law\s+(?:is|can\s+be\s+stated)\s+(?:well\s+)?settled
      | we\s+are\s+clearly\s+of\s+the\s+opinion
      | our\s+answer\s+to\s+(?:the\s+)?question
      | the\s+position,\s+therefore,\s+is
      | to\s+sum\s+up
      | from\s+the\s+(?:above|aforesaid)\s+(?:discussion|analysis|enunciation)
    )
    """
)

ANALYSIS_CUES = re.compile(
    r"""(?ix)
    (?: having\s+heard\s+(?:the\s+)?learned\s+(?:counsel|counsels?|asc?s?|asg|sg|ag)
      | we\s+have\s+(?:carefully\s+)?(?:perused|heard|examined|considered)
      | on\s+a\s+(?:careful\s+|anxious\s+|close\s+|duly\s+)?(?:consideration|perusal|reading|analysis|examination)
      | (?:after|upon|on)\s+(?:giving\s+)?(?:our\s+|anxious\s+|careful\s+)+(?:consideration|thought)
      | a\s+(?:careful\s+|close\s+|plain\s+)?(?:perusal|reading)\s+of
      | from\s+a\s+(?:careful\s+|perusal|conjunctive\s+reading)
      | (?:this\s+court|we)\s+(?:has\s+|have\s+)?(?:had\s+occasion|examined|considered)\s+(?:the\s+)?(?:question|issue|contention)
    )
    """
)

PRECEDENT_NOT_RELIED_CUES = re.compile(
    r"""(?ix)
    (?: distinguish(?:es|ed|ing)
      | does\s+not\s+(?:apply|lay\s+down|support|advance|help|assist)
      | no\s+assistance
      | cannot\s+be\s+pressed\s+into\s+service
      | not\s+applicable
      | has\s+no\s+(?:application|bearing|relevance)
      | is\s+of\s+no\s+(?:avail|assistance|help)
      | inapplicable
      | does\s+not\s+appear\s+to\s+be\s+apposite
      | not\s+apposite
      | does\s+not\s+apply\s+to\s+the\s+facts
    )
    """
)

PRECEDENT_RELIED_CUES = re.compile(
    r"""(?ix)
    (?: relied\s+(?:on|upon)
      | placed\s+(?:reliance|dependence)\s+(?:on|upon)
      | in\s+reliance\s+(?:on|upon)
      | laid\s+down\s+in
      | laid\s+down\s+by\s+(?:this\s+court|the\s+constitution\s+bench)
      | is\s+(?:squarely\s+)?applicable
      | squarely\s+covers
      | supports\s+the\s+(?:case|contention|submission)
      | follows\s+from
      | binding\s+(?:on|precedent)
      | it\s+is\s+settled\s+by
    )
    """
)

# (role, regex) tried in this order -- ROLE_ORDER, table construction kept beside the regexes.
ROLE_CUES: list[tuple[str, re.Pattern[str]]] = [
    ("disposition", DISPOSITION_CUES),
    ("issues", ISSUES_CUES),
    ("argument_petitioner", ARGUMENT_PETITIONER_CUES),
    ("argument_respondent", ARGUMENT_RESPONDENT_CUES),
    ("lower_court", LOWER_COURT_CUES),
    ("statute", STATUTE_CUES),
    ("facts", FACTS_CUES),
    ("ratio", RATIO_CUES),
    ("analysis", ANALYSIS_CUES),
    ("precedent_not_relied", PRECEDENT_NOT_RELIED_CUES),
    ("precedent_relied", PRECEDENT_RELIED_CUES),
]

NONE = "none"


def classify_role(body: str, *, is_first: bool = False) -> str:
    """One label for one paragraph, by the first cue set that matches."""
    if is_first and PREAMBLE_CUES.search(body):
        return "preamble"
    for role, pattern in ROLE_CUES:
        if pattern.search(body):
            return role
    return NONE


@dataclass
class RoleResult:
    """Counts of what was labelled, for the CLI line."""

    labelled: int = 0
    skipped_already: int = 0
    by_role: Counter = field(default_factory=Counter)

    def __str__(self) -> str:
        top = ", ".join(f"{role}={count:,}" for role, count in self.by_role.most_common())
        return f"{self.labelled:,} paragraphs ({top})"


def mark_roles(
    session: Session, *, dry_run: bool = False, relabel: bool = False
) -> RoleResult:
    """Classify every paragraph's role and write it back.

    Paragraphs that already carry a role are left alone unless `relabel`: the printed form is the
    better evidence pattern from mark_separate_opinions, and re-running this must stay idempotent.
    Text versions stream one at a time so the pass holds a bounded working set against a corpus of
    700k paragraphs.
    """
    result = RoleResult()
    if relabel and not dry_run:
        session.execute(Paragraph.__table__.update().values(role=None))
        session.commit()

    version_ids = session.scalars(select(JudgmentTextVersion.id)).all()
    for version_id in version_ids:
        rows = session.execute(
            select(Paragraph.id, Paragraph.body, Paragraph.seq, Paragraph.role)
            .where(Paragraph.text_version_id == version_id)
            .order_by(Paragraph.seq)
        ).all()
        updates: list[tuple[str, str]] = []
        for pid, body, seq, role in rows:
            if role is not None and not relabel:
                result.skipped_already += 1
                continue
            label = classify_role(body, is_first=(seq == 1))
            result.by_role[label] += 1
            if role != label:
                updates.append((pid, label))
            result.labelled += 1
        if updates and not dry_run:
            session.execute(
                Paragraph.__table__.update()
                .where(Paragraph.__table__.c.id == bindparam("bid"))
                .values(role=bindparam("role_label")),
                [{"bid": pid, "role_label": label} for pid, label in updates],
            )
            session.commit()
            session.commit()
    return result
