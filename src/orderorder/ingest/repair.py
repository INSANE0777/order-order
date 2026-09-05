"""Repairs to text already in the database, for when extraction is corrected after the fact.

Re-extracting the corpus means re-parsing nine thousand PDFs, which takes hours and is wasted work
when the fix touches text the database already holds. These repairs read the stored paragraphs, apply
the corrected rule, and write back — seconds instead of hours — and they are written so that running
one twice changes nothing the second time.

Each one names the extraction fix it stands in for, so that a fresh corpus built from the PDFs and a
repaired one agree.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from orderorder.db.models import JudgmentTextVersion, Paragraph
from orderorder.ingest.pdf import TRAILER_START_PATTERNS, strip_signoff


@dataclass
class RepairResult:
    scanned: int
    trimmed: int
    removed: int
    characters: int

    def __str__(self) -> str:
        return (
            f"{self.trimmed} paragraphs trimmed and {self.removed} removed "
            f"({self.characters:,} characters of publisher's text) from {self.scanned} examined"
        )


def _trailer_start(body: str) -> int | None:
    starts = [match.start() for pattern in TRAILER_START_PATTERNS for match in [pattern.search(body)] if match]
    return min(starts) if starts else None


def strip_publisher_trailers(session: Session, *, dry_run: bool = False) -> RepairResult:
    """Remove the reporter's closing matter from paragraphs stored before `split_trailer` existed.

    The SCR volumes end a judgment with the editors' own matter — the disposition restated, the name
    of whoever wrote the headnote — running on from the court's last paragraph. Extraction now cuts it
    off; this cuts it out of what was stored earlier.

    It matters more than tidiness. A quote verified against the trailer would be reported as the
    court's words, and the engine's one promise is that a verified quote is the court's.

    A paragraph that is nothing but trailer is deleted. A paragraph that ends in one is trimmed, and
    its `char_end` is pulled back so the offsets still name what the body now holds.
    """
    result = RepairResult(0, 0, 0, 0)
    doomed: list[str] = []

    # Only paragraphs carrying a marker can be affected, and there are about two thousand of them in a
    # corpus of four hundred thousand.
    candidates = session.scalars(
        select(Paragraph).where(
            Paragraph.body.like("%Headnotes prepared by%") | Paragraph.body.like("%Result of the case%")
        )
    ).all()

    for paragraph in candidates:
        result.scanned += 1
        cut = _trailer_start(paragraph.body)
        if cut is None:
            continue
        kept = paragraph.body[:cut].rstrip()
        result.characters += len(paragraph.body) - len(kept)
        if kept:
            result.trimmed += 1
            if not dry_run:
                # The span covers the source lines, printed label and all, so it shrinks by what was
                # cut rather than being recomputed from the body's length.
                paragraph.char_end -= len(paragraph.body) - len(kept)
                paragraph.body = kept
        else:
            result.removed += 1
            doomed.append(paragraph.id)

    if doomed and not dry_run:
        session.execute(delete(Paragraph).where(Paragraph.id.in_(doomed)))
    if not dry_run:
        session.commit()
    return result


def strip_signoffs(session: Session, *, dry_run: bool = False) -> RepairResult:
    """Remove the volume's sign-off from the last paragraph of judgments stored before it was caught.

    Only the last paragraph of each text version can carry it, since it is printed at the foot of the
    last page — so this reads one paragraph per judgment rather than four hundred thousand.
    """
    result = RepairResult(0, 0, 0, 0)
    doomed: list[str] = []

    version_ids = list(session.scalars(select(JudgmentTextVersion.id)).all())
    for version_id in version_ids:
        last = session.scalars(
            select(Paragraph)
            .where(Paragraph.text_version_id == version_id)
            .order_by(Paragraph.seq.desc())
            .limit(1)
        ).first()
        if last is None:
            continue
        result.scanned += 1
        kept, signoff = strip_signoff(last.body)
        if not signoff:
            continue
        result.characters += len(last.body) - len(kept)
        if kept.strip():
            result.trimmed += 1
            if not dry_run:
                last.char_end -= len(last.body) - len(kept)
                last.body = kept
        else:
            result.removed += 1
            doomed.append(last.id)

    if doomed and not dry_run:
        session.execute(delete(Paragraph).where(Paragraph.id.in_(doomed)))
    if not dry_run:
        session.commit()
    return result
