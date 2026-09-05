"""Persist an extracted judgment: its text version, its opinions and its paragraphs.

A judgment can have several text versions (the official PDF, the open-data copy, an Indian Kanoon copy)
and a pinpoint means nothing without saying which one it was resolved against. Every version stored here
records its source and a SHA-256 of the text, so a verdict can name the exact text it read.

The editorial headnote is stored as its own opinion of kind "headnote". It is never part of the
judgment text that pinpoints resolve against, because it is the publisher's words rather than the
court's, but it is kept because a brief that quotes it is making exactly the mistake worth reporting.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from orderorder.db.models import Judgment, JudgmentTextVersion, Opinion, Paragraph
from orderorder.ingest.pdf import ExtractedJudgment, find_separate_opinions
from orderorder.ingest.segment import SegParagraph, quoted_within, segment


@dataclass
class StoreResult:
    text_version_id: str
    paragraphs: int
    opinions: int
    replaced: bool
    version_key: str
    bench_corrected: bool = False


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_extracted(
    session: Session,
    judgment: Judgment,
    extracted: ExtractedJudgment,
    *,
    version_key: str = "scr_pdf",
    source_url: str | None = None,
    preferred: bool = True,
    replace: bool = True,
) -> StoreResult:
    """Write one extracted judgment into the database, replacing any earlier copy of the same version."""
    existing = session.scalars(
        select(JudgmentTextVersion).where(
            JudgmentTextVersion.judgment_id == judgment.id,
            JudgmentTextVersion.version_key == version_key,
        )
    ).first()
    replaced = False
    if existing is not None:
        if not replace:
            return StoreResult(
                existing.id, len(existing.paragraphs), len(existing.opinions), False, version_key
            )
        session.execute(delete(Paragraph).where(Paragraph.text_version_id == existing.id))
        session.execute(delete(Opinion).where(Opinion.text_version_id == existing.id))
        session.delete(existing)
        session.flush()
        replaced = True

    # The coram printed on the judgment is authoritative for bench strength; the open-data metadata
    # names only the presiding judge, so a two-judge bench arrives recorded as one. Bench strength
    # decides which precedents bind which, so correct it whenever the PDF is more complete.
    bench_corrected = False
    if extracted.coram:
        if len(extracted.coram) > (judgment.bench_strength or 0):
            judgment.bench_strength = len(extracted.coram)
            bench_corrected = True
        # Refresh the names unconditionally: the coram is the better source even when the count agrees.
        judgment.judges = extracted.coram

    body = extracted.judgment
    version = JudgmentTextVersion(
        judgment_id=judgment.id,
        version_key=version_key,
        source_url=source_url,
        ocr_derived=False,
        sha256=text_sha256(body),
        char_count=len(body),
        preferred=preferred,
    )
    session.add(version)
    session.flush()

    paragraphs: list[SegParagraph] = segment(body)

    # The court's own opinion spans the judgment unless a dissent or concurrence announces itself.
    # Paragraphs the numbering says are quoted are excluded from that search: a block quotation runs
    # over several paragraphs, so the quotation marks are nowhere near the cue, and a dissent quoted
    # from an earlier judgment would be recorded as this court dividing.
    quoted = quoted_within(paragraphs)
    breaks = find_separate_opinions(
        body, skip=[(p.char_start, p.char_end) for p in paragraphs if p.seq in quoted]
    )
    opinions: list[Opinion] = []
    majority = Opinion(
        text_version_id=version.id,
        kind="majority",
        author=extracted.author,
        seq_start=paragraphs[0].seq if paragraphs else 0,
        seq_end=paragraphs[-1].seq if paragraphs else 0,
    )
    session.add(majority)
    opinions.append(majority)

    for offset, kind, judge in breaks:
        following = [p for p in paragraphs if p.char_start >= offset]
        if not following:
            continue
        separate = Opinion(
            text_version_id=version.id,
            kind="dissenting" if kind == "dissenting" else "concurring",
            author=judge,
            seq_start=following[0].seq,
            seq_end=paragraphs[-1].seq,
        )
        session.add(separate)
        opinions.append(separate)
        majority.seq_end = following[0].seq - 1

    if extracted.headnote.strip():
        headnote = Opinion(
            text_version_id=version.id,
            kind="headnote",
            author=None,
            seq_start=0,
            seq_end=0,
        )
        session.add(headnote)
        opinions.append(headnote)
    session.flush()

    def opinion_for(seq: int) -> str | None:
        for opinion in opinions:
            if opinion.kind != "headnote" and opinion.seq_start <= seq <= opinion.seq_end:
                return opinion.id
        return majority.id

    for paragraph in paragraphs:
        session.add(
            Paragraph(
                text_version_id=version.id,
                seq=paragraph.seq,
                printed_label=paragraph.printed_label,
                opinion_id=opinion_for(paragraph.seq),
                role=None,
                body=paragraph.body,
                char_start=paragraph.char_start,
                char_end=paragraph.char_end,
            )
        )
    session.flush()
    return StoreResult(
        version.id,
        len(paragraphs),
        len({o.id for o in opinions}),
        replaced,
        version_key,
        bench_corrected,
    )


def load_paragraphs(
    session: Session, judgment_id: str, *, version_key: str | None = None
) -> list[SegParagraph]:
    """Read a judgment's paragraphs back as segmentation objects, so the locator works the same either way."""
    query = select(JudgmentTextVersion).where(JudgmentTextVersion.judgment_id == judgment_id)
    if version_key:
        query = query.where(JudgmentTextVersion.version_key == version_key)
    else:
        query = query.order_by(JudgmentTextVersion.preferred.desc())
    version = session.scalars(query).first()
    if version is None:
        return []
    rows = session.scalars(
        select(Paragraph).where(Paragraph.text_version_id == version.id).order_by(Paragraph.seq)
    ).all()
    opinions = {
        o.id: o
        for o in session.scalars(select(Opinion).where(Opinion.text_version_id == version.id)).all()
    }
    out: list[SegParagraph] = []
    for row in rows:
        opinion = opinions.get(row.opinion_id) if row.opinion_id else None
        out.append(
            SegParagraph(
                row.seq,
                row.printed_label,
                row.body,
                row.char_start,
                row.char_end,
                opinion_kind=opinion.kind if opinion else None,
                opinion_author=opinion.author if opinion else None,
                role=row.role,
            )
        )
    return out
