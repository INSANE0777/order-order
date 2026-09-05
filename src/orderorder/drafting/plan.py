"""The case plan: what an advocate has before the draft exists.

`docs/PRD.md` B7 asks for a written submission in Indian format — synopsis, list of dates, issues,
arguments, prayer, table of authorities. Everything in that list except the arguments is the
advocate's own knowledge of their case, and no amount of retrieval produces it. So the plan is
written by hand, in a plain text file, and this module reads it.

The format is a header and sections, and it is deliberately the smallest thing that could carry a
submission::

    court: In the High Court of Delhi at New Delhi
    cause: W.P.(C) 4521 of 2025
    parties: Ashok Kumar versus Union of India
    for: the Petitioner

    # dates
    12 March 2019 - the lease was executed
    12 November 2024 - the notice to quit was issued

    # issue Whether a notice under Section 106 was mandatory
    A notice under Section 106 of the Transfer of Property Act is mandatory before eviction.
    Its absence is fatal to the suit however strong the merits may be.

    # prayer
    set aside the impugned judgment and decree

Each line under an issue is one **proposition**: a sentence the advocate intends to argue, which the
engine will then try to bind to an authority and mostly fail to. That is the unit because it is the
unit the rest of the engine already works in — `engine.authority` binds a proposition, the verifier
checks a proposition against a paragraph, and the gate refuses a proposition. A draft assembled from
anything larger could not be checked sentence by sentence, and a draft that cannot be checked
sentence by sentence is the thing this project exists to refuse to produce.

Nothing here calls a model. A parser that guessed at the advocate's issues would be inventing the
case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# A section header. `# issue <title>` carries its title on the same line; the others do not.
SECTION = re.compile(r"^#\s*(synopsis|dates|issue|prayer)\b[ \t]*(.*)$", re.IGNORECASE)
# A header line, before any section: `key: value`.
HEADER = re.compile(r"^([A-Za-z][A-Za-z ]{0,30}):\s*(.+)$")
# What a header key is called in the document it ends up in.
HEADER_FIELDS = {
    "court": "court",
    "cause": "cause",
    "case": "cause",
    "parties": "parties",
    "for": "appearing_for",
    "counsel": "counsel",
    "date": "date",
}
# A proposition shorter than this is a fragment, not something anyone argues. The same threshold the
# `argue` command uses, for the same reason: six words is where a sentence starts making a claim.
MIN_WORDS = 6


class PlanError(ValueError):
    """The plan cannot be read. The message says which line and what to do about it."""


@dataclass
class Issue:
    """One question the court has to decide, and the propositions advanced under it."""

    title: str
    propositions: list[str] = field(default_factory=list)


@dataclass
class Plan:
    """A case, as its advocate describes it before any authority is found."""

    court: str | None = None
    cause: str | None = None
    parties: str | None = None
    appearing_for: str | None = None
    counsel: str | None = None
    date: str | None = None
    synopsis: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    prayer: list[str] = field(default_factory=list)

    @property
    def propositions(self) -> list[str]:
        return [p for issue in self.issues for p in issue.propositions]

    @property
    def title(self) -> str:
        """What the document is called, for a file name or a heading."""
        return self.parties or self.cause or "Written Submissions"


def parse_plan(text: str) -> Plan:
    """Read a plan, or say precisely why it cannot be read."""
    plan = Plan()
    section: str | None = None
    issue: Issue | None = None
    short: list[tuple[int, str]] = []

    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue

        header = SECTION.match(line)
        if header:
            section = header.group(1).lower()
            if section == "issue":
                title = header.group(2).strip()
                if not title:
                    raise PlanError(f"line {number}: an issue needs a title on the same line as `# issue`")
                issue = Issue(title)
                plan.issues.append(issue)
            continue

        if section is None:
            field_line = HEADER.match(line)
            if field_line is None:
                raise PlanError(
                    f"line {number}: expected `key: value` or a section like `# issue ...`, got {line[:40]!r}"
                )
            key = field_line.group(1).strip().lower()
            if key not in HEADER_FIELDS:
                known = ", ".join(sorted(HEADER_FIELDS))
                raise PlanError(f"line {number}: unknown field {key!r}; known fields are {known}")
            setattr(plan, HEADER_FIELDS[key], field_line.group(2).strip())
            continue

        if section == "synopsis":
            plan.synopsis.append(line)
        elif section == "dates":
            plan.dates.append(line)
        elif section == "prayer":
            plan.prayer.append(line)
        elif section == "issue":
            assert issue is not None  # a `# issue` header always makes one
            if len(line.split()) < MIN_WORDS:
                short.append((number, line))
            else:
                issue.propositions.append(line)

    if not plan.issues:
        raise PlanError("the plan has no issues; add at least one `# issue <title>` section")
    if not plan.propositions:
        detail = ""
        if short:
            n, first = short[0]
            detail = f" (line {n}, {first[:40]!r}, is under {MIN_WORDS} words)"
        raise PlanError(f"no issue has a proposition to argue{detail}")
    return plan


def read_plan(path: str | Path) -> Plan:
    return parse_plan(Path(path).read_text(encoding="utf-8"))
