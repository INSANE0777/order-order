"""Read a brief out of whatever the advocate has: a PDF, a DOCX, or plain text.

`docs/PRD.md` A1. This is the front door of the stress-test, and it is deliberately separate from
`ingest.pdf`, which reads the *court's* Reports and knows a great deal about their margin letters,
running headers and editorial headnotes. A brief has none of that and would be damaged by the
assumptions: the cleaning that saves a judgment from its publisher would strip an advocate's own
numbering.

What matters here is only that the text comes out in reading order and that footnotes survive, because
a citation is as often in a footnote as in the body — the footnote is where an advocate puts the
authority they are least sure of.

Extraction is never silent. The text is handed back to be shown before anything is checked, because a
verdict on a brief the reader has not seen is a verdict on a document neither of you can point at, and
a PDF that came out mangled should be obvious in a second rather than discovered through nine
inexplicable phantom citations.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

# What a scanned page looks like once a text layer that is not there has been asked for. Below this
# many characters a page has effectively yielded nothing, whatever the extractor returned.
MIN_CHARS_PER_PAGE = 40


@dataclass
class ExtractedBrief:
    """The text of a brief, and how confident we are that it is all of it."""

    text: str
    kind: str
    pages: int = 0
    empty_pages: int = 0
    note: str | None = None

    @property
    def looks_scanned(self) -> bool:
        """Most pages gave up nothing, which means an image where the words should be."""
        return self.pages > 0 and self.empty_pages >= max(1, self.pages // 2)


def read_brief(data: bytes, filename: str) -> ExtractedBrief:
    """Text out of an uploaded file, by what the name says it is."""
    lowered = (filename or "").lower()
    if lowered.endswith(".pdf"):
        return _from_pdf(data)
    if lowered.endswith(".docx"):
        return _from_docx(data)
    if lowered.endswith(".doc"):
        raise ValueError(
            "the old .doc format cannot be read directly; save it as .docx or PDF and upload that"
        )
    return _from_text(data, lowered)


def _from_text(data: bytes, filename: str) -> ExtractedBrief:
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return ExtractedBrief(text=data.decode(encoding), kind="text")
        except UnicodeDecodeError:
            continue
    raise ValueError(f"could not read {filename or 'that file'} as text in any common encoding")


def _from_pdf(data: bytes) -> ExtractedBrief:
    """Page text in reading order, with a count of the pages that yielded nothing.

    A brief filed as a scan has no text layer, and every page comes back empty. Saying so is the
    difference between "this needs OCR" and a page of results that makes no sense.
    """
    import pypdfium2

    document = pypdfium2.PdfDocument(io.BytesIO(data))
    try:
        pages: list[str] = []
        empty = 0
        for index in range(len(document)):
            page = document[index]
            text = page.get_textpage().get_text_range()
            if len(text.strip()) < MIN_CHARS_PER_PAGE:
                empty += 1
            pages.append(text)
        joined = "\n".join(pages).strip()
    finally:
        document.close()

    result = ExtractedBrief(text=joined, kind="pdf", pages=len(pages), empty_pages=empty)
    if result.looks_scanned:
        result.note = (
            f"{empty} of {len(pages)} pages carry no text layer, so this is probably a scan. "
            "What was checked is only what came out."
        )
    return result


def _from_docx(data: bytes) -> ExtractedBrief:
    """Paragraphs and table cells, in document order.

    Tables matter: a table of authorities is a table, and it is exactly the place a reader wants
    every citation checked.
    """
    from docx import Document

    document = Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append("\t".join(cells))
    return ExtractedBrief(text="\n".join(parts).strip(), kind="docx")
