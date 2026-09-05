"""Repairs to text already in the database, for when extraction is corrected after the fact.

Re-extracting the corpus means re-parsing nine thousand PDFs, which takes hours and is wasted work
when the fix touches text the database already holds. These repairs read the stored paragraphs, apply
the corrected rule, and write back — seconds instead of hours — and they are written so that running
one twice changes nothing the second time.

Each one names the extraction fix it stands in for, so that a fresh corpus built from the PDFs and a
repaired one agree.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from orderorder.db.models import JudgmentTextVersion, Opinion, Paragraph
from orderorder.ingest.pdf import TRAILER_START_PATTERNS, find_separate_opinions, strip_signoff
from orderorder.ingest.segment import SegParagraph, quoted_within


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


@dataclass
class OpinionResult:
    scanned: int
    found: int
    kinds: Counter

    def __str__(self) -> str:
        detail = ", ".join(f"{count} {kind}" for kind, count in sorted(self.kinds.items()))
        return f"{self.found} separate opinions in {self.scanned} judgments ({detail or 'none'})"


def mark_separate_opinions(session: Session, *, dry_run: bool = False) -> OpinionResult:
    """Find the dissents and concurrences that only announce themselves in a sentence.

    Extraction now reads a judge writing "I regret my inability to agree" as the start of a separate
    opinion; before, only a printed "(dissenting)" counted, and across 9,424 judgments that appears
    five times. This applies the corrected rule to text already stored, so failure mode 6 works on the
    corpus without re-reading every PDF.

    A judgment that already has a separate opinion is left alone: the printed form is the better
    evidence, and re-running this must not add a second opinion beside one already recorded.
    """
    result = OpinionResult(0, 0, Counter())

    version_ids = list(session.scalars(select(JudgmentTextVersion.id)).all())
    for version_id in version_ids:
        result.scanned += 1
        opinions = session.scalars(select(Opinion).where(Opinion.text_version_id == version_id)).all()
        majority = next((o for o in opinions if o.kind == "majority"), None)
        if majority is None or any(o.kind in {"dissenting", "concurring"} for o in opinions):
            continue

        paragraphs = session.scalars(
            select(Paragraph).where(Paragraph.text_version_id == version_id).order_by(Paragraph.seq)
        ).all()
        if not paragraphs:
            continue

        # The paragraph offsets belong to a text this store does not keep, so the search runs over the
        # paragraphs joined back together and the cue is located by which paragraph it fell in. The
        # blank line between them is not cosmetic: it is how the quotation guard finds the paragraph a
        # cue sits in, and joining with a single newline left it counting quote marks from the first
        # word of the judgment.
        starts: list[int] = []
        text_parts: list[str] = []
        cursor = 0
        quoted_spans: list[tuple[int, int]] = []
        quoted = quoted_within(
            [
                SegParagraph(p.seq, p.printed_label, p.body, p.char_start, p.char_end)
                for p in paragraphs
            ]
        )
        for paragraph in paragraphs:
            starts.append(cursor)
            text_parts.append(paragraph.body)
            if paragraph.seq in quoted:
                quoted_spans.append((cursor, cursor + len(paragraph.body)))
            cursor += len(paragraph.body) + 2
        text = "\n\n".join(text_parts)

        separate = find_separate_opinions(text, skip=quoted_spans)
        if not separate:
            continue
        offset, kind, judge = separate[0]
        position = bisect_right(starts, offset) - 1
        first = paragraphs[max(position, 0)]
        # A cue in the opening paragraphs is the sole author writing about the judgment below, not a
        # second opinion; a separate opinion comes after the one it differs from.
        if first.seq <= majority.seq_start:
            continue

        result.found += 1
        result.kinds[kind] += 1
        if dry_run:
            continue

        opinion = Opinion(
            text_version_id=version_id,
            kind=kind,
            author=judge or None,
            seq_start=first.seq,
            seq_end=majority.seq_end,
        )
        session.add(opinion)
        session.flush()
        for paragraph in paragraphs:
            if paragraph.seq >= first.seq:
                paragraph.opinion_id = opinion.id
        majority.seq_end = first.seq - 1

    if not dry_run:
        session.commit()
    return result
