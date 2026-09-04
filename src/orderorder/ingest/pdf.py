"""Fetch and clean Supreme Court Reports PDFs.

The official SCR PDFs in the open-data bucket are born-digital, so text comes out with pypdfium2 and no
OCR is needed. What comes out is noisy in ways specific to this publisher, and each kind of noise would
corrupt a pinpoint if left in:

  * margin reference letters A to H down the side of every page (SCR cites as "593F")
  * running headers: the page number, "SUPREME COURT REPORTS [2019] 9 S.C.R.", the party names
  * the reporter citation repeated on each page
  * U+FFFD where the en-dash should be

Most importantly the file opens with an **editorial headnote** written by the SCR editors, including a
"HELD:" summary with its own numbering. Those are not the court's words. Citing them as the holding is
failure mode 5 in the taxonomy, so this module finds the boundary and labels the two regions
separately; the judgment text is what pinpoints resolve against.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from orderorder.ingest.corpus import BASE_URL, download

# A bare margin letter on its own line.
MARGIN_RE = re.compile(r"^\s*[A-H]\s*$")
# "594 SUPREME COURT REPORTS [2019] 9 S.C.R." and the bare reporter citation line.
REPORTS_HEADER_RE = re.compile(r"^\s*\d{0,5}\s*SUPREME COURT REPORTS.*$", re.IGNORECASE)
CITATION_LINE_RE = re.compile(r"^\s*\[?\d{4}\]?\s*\d{0,3}\s*S\.?C\.?R\.?\s*\d{0,5}\s*$", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")

# Where the court's own words begin. Tried in order, most specific first.
#
# The Reports changed format around 2020. Modern volumes print an explicit
# "Judgment / Order of the Supreme Court" line after the counsel appearances; older ones open with
# "The Judgment of the Court was delivered by". The jurisdiction line is only a fallback, because it
# heads a block of case details and advocates' names that are not the court's words either.
JUDGMENT_START_PATTERNS = [
    re.compile(r"^[ \t]*Judgment\s*/\s*Order of the Supreme Court[ \t]*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"The Judgment of the Court was delivered by", re.IGNORECASE),
    re.compile(r"^\s*J\s*U\s*D\s*G\s*M\s*E\s*N\s*T\s*$", re.MULTILINE),
    re.compile(r"^\s*ORDER\s*$", re.MULTILINE),
    re.compile(r"CIVIL APPELLATE JURISDICTION", re.IGNORECASE),
    re.compile(r"CRIMINAL APPELLATE JURISDICTION", re.IGNORECASE),
    re.compile(r"^\s*Leave granted", re.MULTILINE | re.IGNORECASE),
]

# A dissent or concurrence usually announces itself.
DISSENT_RE = re.compile(
    r"^\s*(?P<judge>[A-Z][A-Za-z.\s]{2,60}),?\s*J\.?\s*\(\s*(?P<kind>dissenting|concurring)\s*\)",
    re.IGNORECASE | re.MULTILINE,
)
DELIVERED_BY_RE = re.compile(
    r"The Judgment of the Court was delivered by\s*\n?\s*(?P<judge>[A-Z][A-Za-z.\s]{2,60}?),?\s*J\.",
    re.IGNORECASE,
)
# The modern format simply prints the author on its own line: "Vikram Nath, J." or "J.B. Pardiwala, J."
# The character class excludes newlines deliberately: with re.MULTILINE a class containing \s would run
# past the line start and swallow the preceding "Judgment" heading into the judge's name.
AUTHOR_LINE_RE = re.compile(
    r"^[ \t]*(?P<judge>[A-Z][A-Za-z. \t]{2,60}?)[ \t]*,[ \t]*(?:C\.?J\.?I?\.?|J\.)[ \t]*$", re.MULTILINE
)
AUTHOR_SEARCH_WINDOW = 800

# The coram as printed above the headnote: "[DR. DHANANJAYA Y. CHANDRACHUD AND M. R. SHAH, JJ.]".
# This is the authority on bench strength. The open-data metadata names only the presiding judge, so
# counting judges there under-reports a two-judge bench as one, and bench strength decides which
# precedents bind which (failure mode 3).
CORAM_RE = re.compile(r"\[\s*(?P<judges>[A-Z][^\]]{4,200}?)\s*,?\s*(?:JJ|J|CJI|C\.J\.I)\.?\s*\]")
_CORAM_SPLIT = re.compile(r"\s+AND\s+|,\s*", re.IGNORECASE)


def find_author(judgment_text: str) -> str | None:
    """Name the judge who wrote the judgment, across both Reports formats."""
    if delivered := DELIVERED_BY_RE.search(judgment_text):
        return re.sub(r"\s+", " ", delivered.group("judge")).strip()
    if line := AUTHOR_LINE_RE.search(judgment_text[:AUTHOR_SEARCH_WINDOW]):
        return re.sub(r"\s+", " ", line.group("judge")).strip()
    return None


def find_coram(text: str) -> list[str]:
    """Every judge on the bench, from the coram line. Empty when the line is absent or unparseable."""
    match = CORAM_RE.search(text)
    if not match:
        return []
    judges = []
    for part in _CORAM_SPLIT.split(match.group("judges")):
        # The Reports mark the authoring judge with a trailing asterisk; keep the name, drop the mark.
        name = re.sub(r"\s+", " ", part).strip(" .,*")
        name = re.sub(r"^(?:DR|MR|MRS|MS|SHRI|SMT|HON'?BLE|JUSTICE)\.?\s+", "", name, flags=re.IGNORECASE)
        if len(name) > 2 and any(c.isalpha() for c in name):
            judges.append(name)
    return judges


@dataclass
class ExtractedJudgment:
    """One SCR PDF, cleaned and split into its editorial and judicial regions."""

    source_path: str
    page_count: int
    headnote: str
    judgment: str
    author: str | None = None
    coram: list[str] = field(default_factory=list)
    removed_lines: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def bench_strength(self) -> int | None:
        """How many judges decided the case, from the coram line rather than the metadata."""
        return len(self.coram) or None

    @property
    def full_text(self) -> str:
        """The judgment text, which is what pinpoints resolve against. The headnote is deliberately excluded."""
        return self.judgment

    @property
    def has_judgment(self) -> bool:
        return len(self.judgment.strip()) > 500


def pdf_key(source_path: str, year: int | str, language: str = "english") -> str:
    """Bucket key for one judgment PDF, derived from the `path` column of the metadata."""
    suffix = {"english": "EN"}.get(language, language.upper()[:3])
    return f"data/pdf/year={year}/{language}/{source_path}_{suffix}.pdf"


def pdf_url(source_path: str, year: int | str, language: str = "english") -> str:
    return f"{BASE_URL}/{pdf_key(source_path, year, language)}"


def fetch_pdf(source_path: str, year: int | str, corpus_dir: Path, language: str = "english") -> Path:
    """Download one judgment PDF into `corpus_dir/pdf/`, skipping it if already present."""
    destination = corpus_dir / "pdf" / f"{source_path}_{language}.pdf"
    return download(pdf_key(source_path, year, language), destination)


def extract_pages(pdf_path: Path) -> list[str]:
    """Raw text per page. Import is local so the dependency is only needed when parsing."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        return [document[i].get_textpage().get_text_range() for i in range(len(document))]
    finally:
        document.close()


def _repeated_lines(pages: list[str], *, min_share: float = 0.34) -> set[str]:
    """Lines that appear on a third or more of the pages are running headers or footers, not content.

    This catches the party-name header without hard-coding it, which matters because it differs per case.
    """
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        for line in {ln.strip() for ln in page.splitlines() if ln.strip()}:
            counts[line] += 1
    threshold = max(2, int(len(pages) * min_share))
    return {line for line, n in counts.items() if n >= threshold and len(line) < 120}


def clean_pages(pages: list[str]) -> tuple[str, int]:
    """Strip publisher furniture. Returns the cleaned text and how many lines were dropped."""
    repeated = _repeated_lines(pages)
    kept: list[str] = []
    removed = 0
    for page in pages:
        for raw in page.splitlines():
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                kept.append("")
                continue
            if (
                MARGIN_RE.match(stripped)
                or REPORTS_HEADER_RE.match(stripped)
                or CITATION_LINE_RE.match(stripped)
                or PAGE_NUMBER_RE.match(stripped)
                or stripped in repeated
            ):
                removed += 1
                continue
            kept.append(line)
    text = "\n".join(kept)
    text = text.replace("�", "–")  # the en-dash the publisher's encoding loses
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), removed


def split_headnote(text: str) -> tuple[str, str, str | None, list[str]]:
    """Separate the editorial headnote from the court's judgment.

    Returns (headnote, judgment, author, notes). If no boundary marker is found the whole document is
    treated as judgment text and a note records the uncertainty, because silently discarding text would
    be worse than keeping an unlabelled region.
    """
    notes: list[str] = []
    for pattern in JUDGMENT_START_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        headnote = text[: match.start()].strip()
        judgment = text[match.start() :].strip()
        if len(judgment) < 400:
            continue
        notes.append(f"headnote boundary at {pattern.pattern[:40]!r}")
        return headnote, judgment, find_author(judgment), notes

    notes.append("no headnote boundary found; whole document treated as judgment text")
    return "", text.strip(), None, notes


def find_separate_opinions(judgment_text: str) -> list[tuple[int, str, str]]:
    """Offsets where a dissenting or concurring opinion announces itself: (offset, kind, judge)."""
    found = []
    for match in DISSENT_RE.finditer(judgment_text):
        found.append(
            (match.start(), match.group("kind").lower(), re.sub(r"\s+", " ", match.group("judge")).strip())
        )
    return found


def extract(pdf_path: Path, source_path: str) -> ExtractedJudgment:
    """Full pipeline for one PDF: pages, cleaning, headnote split."""
    pages = extract_pages(pdf_path)
    cleaned, removed = clean_pages(pages)
    headnote, judgment, author, notes = split_headnote(cleaned)
    # The coram sits above the headnote, so search the whole cleaned document.
    coram = find_coram(cleaned)
    return ExtractedJudgment(
        source_path=source_path,
        page_count=len(pages),
        headnote=headnote,
        judgment=judgment,
        author=author,
        coram=coram,
        removed_lines=removed,
        notes=notes,
    )
