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
# The largest step that still reads as the court numbering onwards. One clear paragraph ahead, plus
# room for a sub-label; anything further is a leap that wants a second signal before it counts.
MAX_STEP = 1.5

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


def find_out_of_sequence(paragraphs: list[SegParagraph]) -> set[int]:
    """Sequence numbers of paragraphs whose printed label breaks the ascending order.

    A court numbers its own paragraphs in order. When a judgment quotes another judgment at length it
    reproduces that judgment's numbering, so a high label appears among lower ones and the sequence
    jumps backwards afterwards. Those paragraphs are very likely quoted from elsewhere, which matters
    because attributing them to the citing court is failure mode 5 in the taxonomy.

    This is a signal, not a verdict: the voice check confirms it. It costs nothing and needs no model.
    """
    labelled = [(p.seq, label_value(p.printed_label)) for p in paragraphs if p.printed_label]
    labelled = [(seq, value) for seq, value in labelled if value is not None]
    if len(labelled) < 3:
        return set()

    # Walk forwards, tracking where the court's own numbering has reached. Two shapes betray quoted
    # matter, and nothing else does:
    #
    #   * a **restart** — a label at or below the mark, which is a quoted judgment beginning again at
    #     its own paragraph 1 while the citing court is at 13;
    #   * a **spike** — a label above the mark that the very next label comes back down from, which is
    #     a single quoted paragraph carrying a foreign number ("... 4. 12. 5. ...").
    #
    # A plain forward gap is neither. Judgments skip numbers, and extraction loses paragraphs, so a
    # jump from 1 to 5 is ordinary; treating it as suspicious flagged the court's own holding.
    #
    # Comparing each label against the *following* ones instead — flagging any label that some later
    # label undercuts — reads a quoted block near the end as evidence against everything before it. On
    # a real judgment numbered 1 to 19 with quoted matter interleaved, that flagged 22 of 39
    # paragraphs, and half of a set of sound citations were marked possibly-quoted on the strength of
    # it. Measured, not guessed: see the eval harness.
    quoted: set[int] = set()
    reached = 0.0
    for index, (seq, value) in enumerate(labelled):
        following = labelled[index + 1][1] if index + 1 < len(labelled) else None
        restart = value <= reached
        # A spike both leaps ahead of the sequence and is immediately undercut. Either alone is
        # ordinary: judgments skip numbers, and the label after the court's last paragraph is often a
        # quoted block restarting low.
        spike = value > reached + MAX_STEP and following is not None and following < value
        if restart or spike:
            quoted.add(seq)
        else:
            reached = value
    return quoted
