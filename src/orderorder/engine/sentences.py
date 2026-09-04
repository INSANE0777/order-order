"""Where one sentence ends and the next begins.

Shared by the brief side and the judgment side, because both get it wrong in the same way. Legal prose
is full of full stops that end nothing: "Kasturi v. Iyyamperumal", "[2019] 9 S.C.R. 593",
"Civil Appeal No. 5522 of 2019", "Ltd.", "Smt.". A splitter that treats those as boundaries hands the
scope comparator half a proposition and shows a reader half a holding.

Two guards do the work. A boundary must follow a lower-case letter or digit and precede a capital,
which excludes citations and initials; and it must not follow one of the abbreviations that end in a
lower-case letter and are routinely followed by a capital, which is every case name.
"""

from __future__ import annotations

import re

ABBREVIATIONS = [
    "v",
    "vs",
    "No",
    "Nos",
    "Anr",
    "Ors",
    "Ltd",
    "Pvt",
    "Smt",
    "Sri",
    "Shri",
    "Mr",
    "Mrs",
    "Dr",
    "Hon",
    "Sec",
    "Art",
    "para",
    "Para",
]

# Each abbreviation gets its own lookbehind: Python requires a fixed width for each one.
SENTENCE_BREAK = re.compile(
    "".join(rf"(?<!\b{abbrev})" for abbrev in ABBREVIATIONS)
    + r"(?<=[a-z0-9\)\"'’”])\.\s+(?=[A-Z\"'“‘])|\n\s*\n"
)


def sentence_around(text: str, position: int) -> str:
    """The sentence containing a character position, whitespace collapsed.

    Collapsing matters: a brief wrapped at seventy characters would otherwise yield a proposition with
    line breaks through the middle of it, and every finding would quote it back in that shape.
    """
    breaks = [m.end() for m in SENTENCE_BREAK.finditer(text)]
    start = max((b for b in breaks if b <= position), default=0)
    end = min((b for b in breaks if b > position), default=len(text))
    return " ".join(text[start:end].split())


OPENING_QUOTES = "“„«"   # “ „ «
CLOSING_QUOTES = "”»"          # ” »


def inside_quotation(text: str, position: int) -> bool:
    """Whether a position falls inside a block quotation.

    Indian judgments quote earlier judgments at length, in curly quotes, and what is said inside those
    marks is the earlier court speaking. A judgment quoting "the decision in X is hereby overruled" is
    reporting an overruling, not performing one, and the difference decides which court gets the
    credit for it.

    Straight quotes are deliberately ignored: they are used for emphasis and for statutory words as
    often as for quotation, and guessing at their pairing would be worse than not looking.
    """
    depth = 0
    for character in text[:position]:
        if character in OPENING_QUOTES:
            depth += 1
        elif character in CLOSING_QUOTES:
            depth = max(0, depth - 1)
    return depth > 0


def split_sentences(text: str) -> list[tuple[str, int]]:
    """Every sentence in the text, with its character offset. Offsets survive so a line can be found
    again in the paragraph it came from and highlighted there."""
    if not text.strip():
        return []
    bounds = [0, *(m.end() for m in SENTENCE_BREAK.finditer(text)), len(text)]
    sentences: list[tuple[str, int]] = []
    for start, end in zip(bounds, bounds[1:], strict=False):
        raw = text[start:end]
        stripped = raw.strip()
        if stripped:
            sentences.append((" ".join(stripped.split()), start + (len(raw) - len(raw.lstrip()))))
    return sentences
