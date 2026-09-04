"""Quote-or-nothing.

A claim is "supported" only if a verbatim quote the model returned can be found, by string comparison,
in the judgment text we hold. This module is pure Python and never calls a model. It normalises both
sides (Unicode, quotes, dashes, whitespace, soft hyphens, case), finds the quote, and maps the match
back to character offsets in the original text so the viewer can highlight it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

MIN_QUOTE_WORDS = 6
FUZZY_THRESHOLD = 97.0

_QUOTE_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "–": "-",
        "—": "-",
        "‒": "-",
        "−": "-",
        " ": " ",
        " ": " ",
        " ": " ",
        "­": "",  # soft hyphen
    }
)
_FOOTNOTE_MARK = re.compile(r"(?<=[A-Za-z.,;:)])\d{1,2}(?=\s|$)")


@dataclass(frozen=True)
class NormalizedText:
    text: str
    index_map: list[int]  # normalized position -> original position


@dataclass(frozen=True)
class QuoteMatch:
    found: bool
    match_type: str  # exact | fuzzy_ocr | not_found | too_short
    char_start: int | None = None
    char_end: int | None = None
    score: float = 0.0
    matched_text: str | None = None


def normalize(text: str) -> NormalizedText:
    """Lower-case, NFKC, unify punctuation, collapse whitespace, keep an index map to the original."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        ch = unicodedata.normalize("NFKC", ch).translate(_QUOTE_MAP)
        if not ch:
            continue
        for c in ch:
            if c.isspace():
                if prev_space:
                    continue
                out.append(" ")
                idx.append(i)
                prev_space = True
            else:
                out.append(c.lower())
                idx.append(i)
                prev_space = False
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return NormalizedText("".join(out), idx)


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def find_quote(quote: str, source: str, *, ocr_derived: bool = False) -> QuoteMatch:
    """Locate `quote` inside `source`.

    Exact normalised substring first. If the source is OCR-derived, a fuzzy alignment at or above the
    threshold is accepted and labelled as such. Born-digital text never fuzzy-matches: if the model's
    quote is not literally there, it is not there.
    """
    if word_count(quote) < MIN_QUOTE_WORDS:
        return QuoteMatch(False, "too_short")
    q = normalize(quote)
    s = normalize(source)
    if not q.text or not s.text:
        return QuoteMatch(False, "not_found")

    pos = s.text.find(q.text)
    if pos >= 0:
        start = s.index_map[pos]
        end = s.index_map[pos + len(q.text) - 1] + 1
        return QuoteMatch(True, "exact", start, end, 100.0, source[start:end])

    if ocr_derived:
        align = fuzz.partial_ratio_alignment(q.text, s.text)
        if align is not None and align.score >= FUZZY_THRESHOLD and align.dest_end > align.dest_start:
            start = s.index_map[align.dest_start]
            end = s.index_map[min(align.dest_end, len(s.index_map)) - 1] + 1
            return QuoteMatch(True, "fuzzy_ocr", start, end, float(align.score), source[start:end])

    return QuoteMatch(False, "not_found")


def verify_quotes(quotes: list[str], source: str, *, ocr_derived: bool = False) -> list[QuoteMatch]:
    return [find_quote(q, source, ocr_derived=ocr_derived) for q in quotes]
