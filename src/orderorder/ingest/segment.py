"""Paragraph segmentation for judgment text.

Judgments are segmented into paragraphs using printed paragraph numbers where present ("23.", "(23)",
"Para 23", "[23]"), and blank-line structure otherwise. Line wraps left by PDF extraction are repaired.
Each paragraph keeps its character offsets into the source text so quotes can be highlighted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LABEL_RE = re.compile(
    r"^\s*(?:\[(?P<b>\d{1,3})\]|\((?P<p>\d{1,3})\)|(?P<n>\d{1,3})\s*[.)]|Para(?:graph)?\s*(?P<w>\d{1,3})\s*[.:)]?)\s+(?=\S)"
)
HEADING_RE = re.compile(r"^\s*(?:JUDGMENT|ORDER|J U D G M E N T|O R D E R)\s*$", re.IGNORECASE)
SIGNATURE_RE = re.compile(r"^\s*(?:\.{3,}|…)?\s*[A-Z][A-Za-z.\s]{2,60},?\s*(?:C\.?J\.?I?\.?|J\.?)\s*\.?\s*$")


@dataclass
class SegParagraph:
    seq: int
    printed_label: str | None
    body: str
    char_start: int
    char_end: int


def _repair_wraps(block: str) -> str:
    """Join hard-wrapped lines inside a paragraph; keep genuine sentence breaks."""
    lines = [ln.rstrip() for ln in block.splitlines()]
    out: list[str] = []
    for ln in lines:
        if not ln.strip():
            continue
        stripped = ln.strip()
        # A trailing hyphen is a split word: join with no space. Check this before the space-join below.
        if out and out[-1].endswith("-") and re.match(r"^[a-z]", stripped):
            out[-1] = out[-1][:-1] + stripped
        elif (
            out and not re.search(r"[.:;!?\"'”’)\]]\s*$", out[-1]) and re.match(r"^[a-z(\"'“‘0-9]", stripped)
        ):
            out[-1] = out[-1] + " " + stripped
        else:
            out.append(stripped)
    return "\n".join(out)


def segment(text: str) -> list[SegParagraph]:
    """Split judgment text into numbered paragraphs.

    Strategy: first split on blank lines; then, within the resulting blocks, start a new paragraph at any
    line that carries a printed label. Blocks without labels stay one paragraph each. Headings such as
    "JUDGMENT" become their own unlabeled paragraphs so offsets stay contiguous.
    """
    paragraphs: list[SegParagraph] = []
    seq = 0
    pos = 0
    # Walk blank-line-delimited blocks keeping absolute offsets.
    for block_match in re.finditer(r"(?:[^\n]+\n?)+", text):
        block = block_match.group(0)
        block_start = block_match.start()
        # Split block into label-led chunks.
        chunks: list[tuple[int, str | None, str]] = []
        cur_start, cur_label, cur_lines = 0, None, []
        offset = 0
        for line in block.splitlines(keepends=True):
            m = LABEL_RE.match(line)
            if m and cur_lines:
                chunks.append((cur_start, cur_label, "".join(cur_lines)))
                cur_start, cur_label, cur_lines = offset, None, []
            if m and not cur_lines:
                cur_label = m.group("b") or m.group("p") or m.group("n") or m.group("w")
            cur_lines.append(line)
            offset += len(line)
        if cur_lines:
            chunks.append((cur_start, cur_label, "".join(cur_lines)))
        for rel_start, label, chunk in chunks:
            body = _repair_wraps(chunk)
            if label:
                body = LABEL_RE.sub("", body, count=1).strip()
            if not body.strip():
                continue
            seq += 1
            start = block_start + rel_start
            paragraphs.append(SegParagraph(seq, label, body.strip(), start, start + len(chunk.rstrip("\n"))))
        pos = block_match.end()
    _ = pos
    return paragraphs


def label_index(paragraphs: list[SegParagraph]) -> dict[str, SegParagraph]:
    """First paragraph for each printed label; duplicates keep the first occurrence."""
    out: dict[str, SegParagraph] = {}
    for p in paragraphs:
        if p.printed_label and p.printed_label not in out:
            out[p.printed_label] = p
    return out
