"""The assembled draft as a document: one structure, two files.

`docs/PRD.md` B7 asks for Indian written-submission format and B9 for a DOCX that opens cleanly in
Word. Those are the same document, so they are built once, here, as a list of blocks — a kind and
some text — and `drafting.word` maps the kinds onto Word styles while this module maps them onto
Markdown. Anything else drifts: a heading added to the Word path and forgotten in the other is a
document that says two different things depending on which file the judge opens.

The order is the one an Indian written submission is filed in: the cause title, the synopsis and list
of dates, the issues for consideration, the submissions issue by issue, the prayer, and the list of
authorities. Then one section that is not part of a filed document and is the reason this tool
exists — the **verification appendix**, which gives, for every citation in the draft, the paragraph
it came from and the words that were matched in it. A person can check the whole submission against
the reports from that appendix without running any of this again, and the disclaimer says plainly
that they should.

Every citation in the body carries its pinpoint at the point of use, because a submission that cites
a judgment without a paragraph number is asking the court to read the whole thing, and because the
pinpoint is the only part of a citation this engine can actually verify.
"""

from __future__ import annotations

from dataclasses import dataclass

from orderorder.drafting.assemble import MARKS, Draft, Point
from orderorder.drafting.attack import NOT_CHECKED, Attack
from orderorder.engine.authority import BOUND, NARROWED, REFUSED, UNCHECKED

# The kinds of block a submission is made of. `word.py` has a style for each.
TITLE = "title"
CENTRED = "centred"
HEADING = "heading"
SUBHEADING = "subheading"
BODY = "body"
NUMBERED = "numbered"
QUOTE = "quote"
NOTE = "note"

# What every export carries. `docs/PRD.md` §5: the lawyer decides, and a document that leaves this off
# invites exactly the reliance the engine is built to prevent.
DISCLAIMER = (
    "Prepared with OrderOrder. Every citation below was checked against a stored copy of the judgment "
    "and the verified words are set out in the appendix. Nothing here is legal advice, no check is a "
    "substitute for reading the judgment, and the draft must be settled by counsel before it is filed."
)

# The lead-in every Indian prayer is written under.
PRAYER_LEAD = "In the premises, it is most respectfully prayed that this Hon'ble Court may be pleased to:"
PRAYER_TAIL = "and pass such further orders as this Hon'ble Court may deem fit."


@dataclass
class Block:
    """One piece of the document: what it is, and what it says."""

    kind: str
    text: str


def blocks(draft: Draft, attacks: list[Attack] | None = None) -> list[Block]:
    """The whole document, in filing order."""
    out: list[Block] = []
    out.extend(_cause_title(draft))
    out.extend(_synopsis(draft))
    out.extend(_dates(draft))
    out.extend(_issues(draft))
    out.extend(_submissions(draft))
    out.extend(_prayer(draft))
    out.extend(_authorities(draft))
    out.extend(_appendix(draft))
    if attacks is not None:
        out.extend(_self_attack(attacks))
    return out


def _self_attack(attacks: list[Attack]) -> list[Block]:
    """What the other side will say. `docs/PRD.md` B8.

    The closing line matters as much as the list. A self-attack section that stops at what it found
    reads as a statement that this is all there is, and the two largest questions about any draft --
    whether these authorities govern these facts, and whether something in the corpus says the
    opposite -- are not on it.
    """
    out = [
        Block(HEADING, "APPENDIX: WHAT THE OTHER SIDE WILL SAY"),
        Block(NOTE, "Not part of the submission. Remove before filing."),
    ]
    if not attacks:
        out.append(Block(BODY, "Nothing found in the citation graph against the authorities cited."))
    for index, attack in enumerate(attacks, start=1):
        head = f"{index}. {attack.says}"
        lines = [head, f"   on: {attack.proposition.strip()}"]
        if attack.citation:
            lines.append(f"   cited: {attack.citation}")
        lines.append(f"   fix: {attack.fix}")
        out.append(Block(BODY, "\n".join(lines)))
    out.append(Block(NOTE, NOT_CHECKED))
    return out


def _cause_title(draft: Draft) -> list[Block]:
    plan = draft.plan
    out: list[Block] = []
    if plan.court:
        out.append(Block(TITLE, plan.court.upper()))
    if plan.cause:
        out.append(Block(CENTRED, plan.cause))
    if plan.parties:
        out.append(Block(CENTRED, plan.parties))
    heading = "WRITTEN SUBMISSIONS"
    if plan.appearing_for:
        heading = f"WRITTEN SUBMISSIONS ON BEHALF OF {plan.appearing_for.upper()}"
    out.append(Block(TITLE, heading))
    if plan.counsel or plan.date:
        out.append(Block(CENTRED, " | ".join(x for x in (plan.counsel, plan.date) if x)))
    out.append(Block(NOTE, DISCLAIMER))
    return out


def _synopsis(draft: Draft) -> list[Block]:
    if not draft.plan.synopsis:
        return []
    return [Block(HEADING, "SYNOPSIS"), *[Block(BODY, line) for line in draft.plan.synopsis]]


def _dates(draft: Draft) -> list[Block]:
    if not draft.plan.dates:
        return []
    return [Block(HEADING, "LIST OF DATES"), *[Block(BODY, line) for line in draft.plan.dates]]


def _issues(draft: Draft) -> list[Block]:
    out = [Block(HEADING, "ISSUES FOR CONSIDERATION")]
    for number, argument in enumerate(draft.arguments, start=1):
        out.append(Block(NUMBERED, f"{_roman(number)}. {argument.title}"))
    return out


def _submissions(draft: Draft) -> list[Block]:
    out = [Block(HEADING, "SUBMISSIONS")]
    number = 0
    for index, argument in enumerate(draft.arguments, start=1):
        out.append(Block(SUBHEADING, f"{_roman(index)}. {argument.title}"))
        for point in argument.points:
            number += 1
            out.extend(_point(point, number))
    return out


def _point(point: Point, number: int) -> list[Block]:
    """One submission: the sentence, its authority, and the words that authority actually uses."""
    citation = point.citation
    sentence = point.argued.rstrip(".") + "."
    if citation:
        out = [Block(NUMBERED, f"{number}. {sentence} {citation}.")]
        quote = point.binding.quote
        if quote:
            out.append(Block(QUOTE, '"' + quote.strip() + '"'))
        if point.status == NARROWED:
            # The advocate asked for more than the court said. They are entitled to know which
            # sentence of theirs was replaced, and to put it back if they think the reading is wrong.
            out.append(Block(NOTE, f"Narrowed from: {point.proposition.strip()}"))
        return out
    return [
        Block(NUMBERED, f"{number}. {sentence}"),
        Block(NOTE, f"{MARKS[point.status]} {point.binding.reason}"),
    ]


def _prayer(draft: Draft) -> list[Block]:
    if not draft.plan.prayer:
        return []
    out = [Block(HEADING, "PRAYER"), Block(BODY, PRAYER_LEAD)]
    for index, line in enumerate(draft.plan.prayer, start=1):
        letter = chr(ord("a") + index - 1)
        out.append(Block(NUMBERED, f"{letter}. {line.rstrip('.;')};"))
    out.append(Block(BODY, PRAYER_TAIL))
    return out


def _authorities(draft: Draft) -> list[Block]:
    entries = draft.authorities()
    out = [Block(HEADING, "LIST OF AUTHORITIES")]
    if not entries:
        out.append(Block(NOTE, "No authority in this draft was verified. Nothing may be listed here."))
        return out
    for index, entry in enumerate(entries, start=1):
        out.append(Block(NUMBERED, f"{index}. {entry.render()}"))
    return out


def _appendix(draft: Draft) -> list[Block]:
    """Every citation, where it came from, and the words that were matched.

    This is the part of the document that is not filed. It exists so that the person who signs the
    submission can check it, and so that the check does not require this tool: a paragraph number and
    a quoted sentence are enough to open the report and see for yourself.
    """
    counts = draft.counts
    out = [
        Block(HEADING, "APPENDIX: VERIFICATION"),
        Block(NOTE, "Not part of the submission. Remove before filing."),
        Block(
            BODY,
            f"{len(draft.points)} propositions were put to the engine: "
            f"{counts[BOUND]} bound to an authority, {counts[NARROWED]} bound after narrowing, "
            f"{counts[UNCHECKED]} left unchecked, {counts[REFUSED]} refused.",
        ),
    ]
    number = 0
    for argument in draft.arguments:
        for point in argument.points:
            number += 1
            out.extend(_appendix_entry(point, number))
    if draft.unsupported:
        out.append(Block(SUBHEADING, "Read these before filing"))
        for point in draft.unsupported:
            out.append(Block(BODY, f"- {point.proposition.strip()} - {point.binding.reason}"))
    return out


def _appendix_entry(point: Point, number: int) -> list[Block]:
    binding = point.binding
    chosen = binding.chosen
    if chosen is None:
        # A refusal. The list of what was looked at and rejected *is* the answer here: it says where
        # the next hour of research starts, and dropping it leaves an advocate with "no" and nothing.
        lines = [f"{number}. nothing could be put behind this proposition", f"   {binding.reason}"]
    else:
        lines = [f"{number}. {chosen.authority.title}", f"   {chosen.pinpoint}"]
        treatment = chosen.authority.treatment or (chosen.verdict.treatment if chosen.verdict else None)
        if treatment is not None:
            lines.append("   subsequent history: " + treatment.status.replace("_", " "))
        if binding.quote:
            lines.append('   verified words: "' + binding.quote.strip() + '"')
        elif chosen.authority.line:
            # Never called a quote. Nothing checked that this line says what the proposition claims,
            # and the appendix is the last place to blur that line.
            lines.append('   unverified line: "' + chosen.authority.line.strip()[:300] + '"')
        lines.append(f"   {binding.reason}")

    rejected = [c for c in binding.considered if c is not chosen]
    lines.extend(f"   considered: {c.pinpoint} - {c.reason}" for c in rejected)
    return [Block(BODY, "\n".join(lines))]


def _roman(number: int) -> str:
    """Issue numbering. Indian submissions number issues in roman and paragraphs in arabic."""
    numerals = (("X", 10), ("IX", 9), ("V", 5), ("IV", 4), ("I", 1))
    out = ""
    for numeral, value in numerals:
        while number >= value:
            out += numeral
            number -= value
    return out or "I"


def to_markdown(draft: Draft, attacks: list[Attack] | None = None) -> str:
    """The document as Markdown, for a terminal, an email or any converter."""
    lines: list[str] = []
    for block in blocks(draft, attacks):
        if block.kind == TITLE:
            lines += ["", f"# {block.text}", ""]
        elif block.kind == HEADING:
            lines += ["", f"## {block.text}", ""]
        elif block.kind == SUBHEADING:
            lines += ["", f"### {block.text}", ""]
        elif block.kind in {CENTRED, NOTE}:
            lines += [f"*{block.text}*", ""]
        elif block.kind == QUOTE:
            lines += [f"> {block.text}", ""]
        else:
            lines += [block.text, ""]
    return "\n".join(lines).strip() + "\n"
