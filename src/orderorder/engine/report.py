"""The three things a stress-test hands back: a board, an annotated brief, and a report.

`docs/PRD.md` A14. The board is a table and lives in the terminal; the other two are documents, and
they exist because a verdict is only useful where the work is done. An advocate revising a memorial
at midnight wants the flags *in the brief*, next to the sentence they have to rewrite, not in a
separate window they have to keep aligned by eye. A supervisor signing off wants one file.

Both are built from the verdicts alone and neither calls a model. The report carries what was checked
and came back sound, what was found wanting, and — the part that is easy to leave out and matters
most — what was never checked at all, because a document that reports only problems reads as a
clean bill of health when it is short.

The report is Markdown rather than the PDF the PRD asks for. Markdown is what a person can read in a
terminal, paste into an email, diff between drafts and convert to PDF with any tool they already
have; a PDF writer would be a dependency and a rendering pass in front of all of that. The content is
the deliverable and the format is not, so this is the format until somebody needs the other one.
"""

from __future__ import annotations

from orderorder.engine.memo import render_memo, write_memo
from orderorder.engine.verdict import GRADES, CitationVerdict

# What each grade means, said once, so a reader of the report never has to guess.
GRADE_MEANING = {
    "A": "nothing found against it in what was checked",
    "B": "sound, with a qualification worth knowing",
    "C": "something needs a person to look at it",
    "D": "a real problem: this will be attacked",
    "E": "the citation does not support the proposition as stated",
    "F": "do not file this",
}


def _flag(verdict: CitationVerdict) -> str:
    """The marker written into the brief beside a citation."""
    # One mode, one number: a citation can raise the same failure twice and "12,5,12" reads as a
    # third problem rather than the same one seen from two directions.
    modes = ",".join(dict.fromkeys(str(f.mode) for f in verdict.findings))
    if modes:
        return f"[!{verdict.grade} {modes}]"
    return f"[?{verdict.grade}]" if verdict.needs_review else "[ok]"


def annotate_brief(text: str, verdicts: list[CitationVerdict]) -> str:
    """The brief with a marker after every citation, and a key at the foot.

    Markers go in from the back so that inserting one does not move the offsets of the citations
    before it. Anything without a recorded span is listed at the end rather than dropped: a citation
    the engine graded and the annotator could not place is exactly the thing that must not disappear
    quietly.
    """
    placed = sorted(
        (v for v in verdicts if v.span), key=lambda v: v.span[1], reverse=True
    )
    annotated = text
    for verdict in placed:
        end = verdict.span[1]
        annotated = f"{annotated[:end]} {_flag(verdict)}{annotated[end:]}"

    lines = [annotated.rstrip(), "", "---", "", "Key"]
    for verdict in verdicts:
        detail = "; ".join(f"[{f.mode}] {f.label}" for f in verdict.findings)
        if not detail:
            detail = verdict.review_reason or GRADE_MEANING.get(verdict.grade, "")
        lines.append(f"  {_flag(verdict):<12} {verdict.citation_raw} - {detail}")

    unplaced = [v for v in verdicts if not v.span]
    if unplaced:
        lines += ["", "Graded but not located in this text:"]
        lines += [f"  {v.citation_raw} - grade {v.grade}" for v in unplaced]
    return "\n".join(lines) + "\n"


def _board(verdicts: list[CitationVerdict]) -> list[str]:
    lines = [
        "| grade | citation | case | support | findings |",
        "|---|---|---|---|---|",
    ]
    for verdict in verdicts:
        findings = ", ".join(str(f.mode) for f in verdict.findings) or "-"
        title = (verdict.judgment_title or "-")[:48]
        lines.append(
            f"| {verdict.grade} | {verdict.citation_raw} | {title} | {verdict.support} | {findings} |"
        )
    return lines


def verification_report(
    verdicts: list[CitationVerdict], *, title: str = "Verification report", source: str | None = None
) -> str:
    """One document covering every citation in a brief: the board, then each citation in full."""
    worst_first = sorted(verdicts, key=lambda v: -GRADES.index(v.grade))
    graded_down = [v for v in verdicts if v.grade in "DEF"]
    review = [v for v in verdicts if v.needs_review]

    lines = [f"# {title}", ""]
    if source:
        lines.append(f"Brief: `{source}`")
        lines.append("")
    lines += [
        f"{len(verdicts)} citations checked. "
        f"{len(graded_down)} graded D or worse. "
        f"{len(review)} need a person to look at them.",
        "",
        "## The board",
        "",
        *_board(verdicts),
        "",
        "Grades: " + "; ".join(f"**{g}** {meaning}" for g, meaning in GRADE_MEANING.items()) + ".",
        "",
        "## Citation by citation",
        "",
    ]

    for verdict in worst_first:
        lines.append(f"### {verdict.citation_raw} — grade {verdict.grade}")
        lines.append("")
        if verdict.judgment_title:
            lines.append(f"*{verdict.judgment_title}*")
            lines.append("")
        lines.append(f"> {verdict.proposition.strip()}")
        lines.append("")
        if verdict.quote_verified and verdict.quote:
            where = verdict.paragraph_label or verdict.claimed_pinpoint or "?"
            lines.append(f"Verified quote, paragraph {where}:")
            lines.append("")
            lines.append(f"> {verdict.quote.strip()}")
            lines.append("")
        # The memo already says what is wrong, what holds up and what was never asked, in the words
        # it will be said in. Repeating the findings above it would be the same list twice.
        lines.append("```")
        lines.extend(render_memo(write_memo(verdict)))
        lines.append("```")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
