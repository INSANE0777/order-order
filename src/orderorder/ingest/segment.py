"""Paragraph segmentation for judgment text.

A pinpoint can only be as good as the paragraphs it points at, so this module is deliberate about what
counts as a paragraph. Indian judgments number their paragraphs ("1.", "23.") and often sub-number them
("5.1", "5.2"), and a citation may pinpoint either. Two modes:

  * **labelled** (the usual case): a new paragraph starts at every line carrying a printed label. Line
    breaks inside a paragraph come from the PDF's line wrapping and are repaired.
  * **unlabelled** (plain text, older judgments): blank lines separate paragraphs.

The mode is chosen by counting labels, so text extracted from a PDF (few blank lines, many labels) and
plain text (many blank lines, no labels) both segment correctly. Every paragraph keeps its character
offsets into the source so a verified quote can be highlighted in the original.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass

# "1." / "23." / "(6)" / "[5]" / "Para 7." / "5.1" — the label plus the space after it.
#
# Sub-labels ("5.1") are matched before plain ones and carry a negative lookahead for a further dot or
# digit. Without it a date at the start of a line ("10.07.2008. The appellant...") reads as a paragraph
# label and invents a paragraph, which would corrupt every pinpoint after it.
LABEL_RE = re.compile(
    r"^\s*(?:"
    r"\[(?P<bracket>\d{1,3}(?:\.\d{1,2})?)\]"
    r"|\((?P<paren>\d{1,3}(?:\.\d{1,2})?)\)"
    r"|Para(?:graph)?\s*(?P<word>\d{1,3}(?:\.\d{1,2})?)\s*[.:)]?"
    r"|(?P<sub>\d{1,3}\.\d{1,2})(?![.\d])\s*[.)]?"
    r"|(?P<plain>\d{1,3})\s*[.)]"
    r")\s+(?=\S)"
)
MIN_LABELS_FOR_LABEL_MODE = 3
# How much of a judgment's numbering has to ascend before the numbering is worth reading at all.
# Column-formatted reports extract out of order, and there the labels carry no information about whose
# words a paragraph holds — so the honest answer is silence, not a judgment flagged half over.
MIN_ASCENDING_SHARE = 0.5

HEADING_RE = re.compile(r"^\s*(?:JUDGMENT|ORDER|J U D G M E N T|O R D E R)\s*$", re.IGNORECASE)
SIGNATURE_RE = re.compile(r"^\s*(?:\.{3,}|…)?\s*[A-Z][A-Za-z.\s]{2,60},?\s*(?:C\.?J\.?I?\.?|J\.?)\s*\.?\s*$")

_SENTENCE_END = re.compile(r"[.:;!?\"'”’)\]]\s*$")
_CONTINUES = re.compile(r"^[a-z(\"'“‘0-9]")


@dataclass
class SegParagraph:
    """One paragraph of a judgment.

    The last three fields are empty during segmentation and filled when a paragraph is read back from
    the database, where the opinion it belongs to is known. Whose words a paragraph carries is not a
    property of the text alone: the same sentence is binding in the majority and merely a minority view
    in the dissent, so the opinion travels with the paragraph into the locator and the voice check.
    """

    seq: int
    printed_label: str | None
    body: str
    char_start: int
    char_end: int
    opinion_kind: str | None = None
    opinion_author: str | None = None
    role: str | None = None


def _label_of(line: str) -> str | None:
    match = LABEL_RE.match(line)
    if not match:
        return None
    groups = match.groupdict()
    return groups["bracket"] or groups["paren"] or groups["word"] or groups["sub"] or groups["plain"]


def _join_lines(lines: list[str]) -> str:
    """Repair PDF line wrapping: rejoin hyphen splits and continuation lines, keep real breaks."""
    out: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        # A trailing hyphen is a split word: join with no space. Checked before the space-join below.
        if out and out[-1].endswith("-") and re.match(r"^[a-z]", stripped):
            out[-1] = out[-1][:-1] + stripped
        elif out and not _SENTENCE_END.search(out[-1]) and _CONTINUES.match(stripped):
            out[-1] = out[-1] + " " + stripped
        else:
            out.append(stripped)
    return "\n".join(out)


def _emit(paragraphs: list[SegParagraph], label: str | None, lines: list[str], start: int, end: int) -> None:
    body = _join_lines(lines)
    if label:
        body = LABEL_RE.sub("", body, count=1).strip()
    body = body.strip()
    if not body:
        return
    paragraphs.append(SegParagraph(len(paragraphs) + 1, label, body, start, end))


def segment(text: str) -> list[SegParagraph]:
    """Split judgment text into paragraphs, preserving printed labels and character offsets."""
    if not text.strip():
        return []

    # Walk lines once, recording each line's absolute offset.
    spans: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        spans.append((offset, offset + len(line.rstrip("\n")), line.rstrip("\n")))
        offset += len(line)

    label_count = sum(1 for _, _, line in spans if _label_of(line))
    labelled_mode = label_count >= MIN_LABELS_FOR_LABEL_MODE

    paragraphs: list[SegParagraph] = []
    current: list[str] = []
    current_label: str | None = None
    current_start = 0
    current_end = 0

    for start, end, line in spans:
        label = _label_of(line) if labelled_mode else None
        blank = not line.strip()

        starts_new = bool(label) or (not labelled_mode and blank and current)
        if starts_new and current:
            _emit(paragraphs, current_label, current, current_start, current_end)
            current, current_label = [], None

        if blank and not labelled_mode:
            continue
        if blank and labelled_mode and not current:
            continue

        if not current:
            current_start = start
            current_label = label
        current.append(line)
        current_end = end

    if current:
        _emit(paragraphs, current_label, current, current_start, current_end)
    return paragraphs


def label_index(paragraphs: list[SegParagraph]) -> dict[str, SegParagraph]:
    """First paragraph for each printed label; duplicates keep the first occurrence.

    Duplicates are real: a judgment that quotes another judgment carries that judgment's numbering too.
    Keeping the first occurrence favours the court's own paragraphs, which appear in order.
    """
    out: dict[str, SegParagraph] = {}
    for paragraph in paragraphs:
        if paragraph.printed_label and paragraph.printed_label not in out:
            out[paragraph.printed_label] = paragraph
    return out


def find_paragraph(paragraphs: list[SegParagraph], label: str) -> SegParagraph | None:
    """Look up a paragraph by its printed label, which is what a pinpoint names."""
    return label_index(paragraphs).get(str(label).strip())


def label_value(label: str | None) -> float | None:
    """Numeric value of a printed label, so '5.1' sorts between 5 and 6."""
    if not label:
        return None
    try:
        head, _, tail = label.partition(".")
        value = float(int(head))
        if tail and tail.isdigit():
            value += int(tail) / 100
        return value
    except ValueError:
        return None


def quoted_within(paragraphs: list[SegParagraph]) -> set[int]:
    """The paragraphs whose numbering is not the court's own *and* that the court resumes after.

    `find_out_of_sequence` cannot tell a quoted block from a separate opinion, and should not try:
    both break the numbering, because a dissent restarts at its own paragraph 1 exactly as a quoted
    judgment does. What separates them is what follows. A quotation is followed by the court picking
    its numbering back up; a separate opinion runs to the end of the judgment, because there is
    nothing after it to come back to.

    So this is the set to use where the question is "is this quoted matter" — and the trailing run it
    leaves out is where the question is "does this judgment carry a second opinion".
    """
    quoted = find_out_of_sequence(paragraphs)
    resumes = [p.seq for p in paragraphs if p.printed_label and p.seq not in quoted]
    if not resumes:
        return set()
    return {seq for seq in quoted if seq < max(resumes)}


def _ascending_run(values: list[float]) -> set[int]:
    """Positions of a longest strictly ascending subsequence, by patience sorting."""
    tails: list[float] = []  # tails[k] = smallest possible tail of an ascending run of length k+1
    tail_at: list[int] = []  # the position holding that tail
    came_from: list[int | None] = [None] * len(values)

    for position, value in enumerate(values):
        slot = bisect_left(tails, value)
        came_from[position] = tail_at[slot - 1] if slot else None
        if slot == len(tails):
            tails.append(value)
            tail_at.append(position)
        elif value < tails[slot]:
            # A strictly smaller tail extends further, so it replaces the one held. An *equal* tail
            # extends no further, and keeping the position already held keeps the run early: a
            # judgment whose own paragraphs 18 to 21 are quoted back later offers two runs of the same
            # length, and the court's own came first.
            tails[slot] = value
            tail_at[slot] = position

    run: set[int] = set()
    position = tail_at[-1] if tail_at else None
    while position is not None:
        run.add(position)
        position = came_from[position]
    return run


def _anchored_run(values: list[float]) -> set[int]:
    """The court's own numbering: the longest ascending run that starts where the judgment does.

    Length alone is not enough to tell the court's numbering from a quoted one. A judgment numbered 2
    to 34 that quotes twenty paragraphs in its second half offers two ascending runs of about the same
    size, and the longer one can be the quotation — it borrows the judgment's own closing paragraphs
    to finish on. What separates them is where they begin. The court's numbering starts at the
    judgment's first numbered paragraph, because that is what a judgment is; a quotation cannot.
    """
    if not values:
        return set()
    later = [(position, value) for position, value in enumerate(values) if position and value > values[0]]
    anchored = _ascending_run([value for _position, value in later])
    return {0} | {later[position][0] for position in anchored}


def find_out_of_sequence(paragraphs: list[SegParagraph]) -> set[int]:
    """Sequence numbers of paragraphs whose printed label is not part of the court's own numbering.

    A court numbers its own paragraphs in order, and a judgment that quotes another at length brings
    that judgment's numbering with it. So the court's own paragraphs are the labels that ascend
    through the judgment from beginning to end, and the quoted ones are what is left over. Taking the
    *longest* ascending subsequence says exactly that, and says it in one rule.

    Walking forwards instead — carry a mark of where the numbering has reached, flag anything at or
    below it — reads correctly until a quoted block climbs past the mark. A judgment numbering itself
    1, 2, ... 6.5 and then quoting ten paragraphs numbered 1 to 10 pushes the mark to 10, after which
    the court's own 6.6, 6.7 and everything following it is flagged: one quotation poisons the whole
    tail of the judgment. That is not a tuning problem, and no threshold fixes it, because the mark
    itself is wrong.

    This is a signal, not a verdict: the voice check confirms it. It costs nothing and needs no model.

    Where the numbering is too damaged to read — column-formatted reports extract out of order, and
    then no ascending run is much better than any other — it says nothing at all rather than
    condemning half the judgment.
    """
    labelled = [(p.seq, label_value(p.printed_label)) for p in paragraphs if p.printed_label]
    labelled = [(seq, value) for seq, value in labelled if value is not None]
    if len(labelled) < 3:
        return set()

    values = [value for _seq, value in labelled]
    own = _anchored_run(values)
    if len(own) < len(labelled) * MIN_ASCENDING_SHARE:
        # Either the first label is itself misread, or the text is too scrambled to read. Try without
        # the anchor, and if that is no better say nothing.
        own = _ascending_run(values)
        if len(own) < len(labelled) * MIN_ASCENDING_SHARE:
            return set()
    return {seq for position, (seq, _value) in enumerate(labelled) if position not in own}
