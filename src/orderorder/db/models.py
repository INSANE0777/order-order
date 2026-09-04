"""Tables for the data spine.

Mirrors ARCHITECTURE.md section 7. Vectors and full-text columns are Postgres-only and arrive with the
embedding phase as separate tables, so everything here runs unchanged on SQLite for tests and for
laptop development before Docker is set up.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Judgment(Base):
    """One decision of one court. Several text versions and citation aliases may point at it."""

    __tablename__ = "judgment"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    canonical_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    court: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    decided_on: Mapped[date | None] = mapped_column(Date, index=True)
    neutral_citation: Mapped[str | None] = mapped_column(String(64), index=True)
    bench_strength: Mapped[int | None] = mapped_column(Integer)
    judges: Mapped[list | None] = mapped_column(JSON)
    language: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str | None] = mapped_column(String(128), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    aliases: Mapped[list[CitationAlias]] = relationship(
        back_populates="judgment", cascade="all, delete-orphan"
    )
    versions: Mapped[list[JudgmentTextVersion]] = relationship(
        back_populates="judgment", cascade="all, delete-orphan"
    )
    digest: Mapped[JudgmentDigest | None] = relationship(back_populates="judgment", uselist=False)


class CitationAlias(Base):
    """Every citation string under which a judgment is known. `normalized` is the resolver's exact-match key."""

    __tablename__ = "citation_alias"
    __table_args__ = (UniqueConstraint("normalized", name="uq_citation_alias_normalized"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    judgment_id: Mapped[str] = mapped_column(ForeignKey("judgment.id", ondelete="CASCADE"), index=True)
    reporter: Mapped[str] = mapped_column(String(24), index=True)
    citation_string: Mapped[str] = mapped_column(String(160))
    normalized: Mapped[str] = mapped_column(String(160), index=True)
    source: Mapped[str] = mapped_column(String(32), default="metadata")

    judgment: Mapped[Judgment] = relationship(back_populates="aliases")


class JudgmentTextVersion(Base):
    """A specific text of a judgment (official PDF, AWS Open Data copy, Indian Kanoon copy). Pinpoints name it."""

    __tablename__ = "judgment_text_version"
    __table_args__ = (UniqueConstraint("judgment_id", "version_key", name="uq_text_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    judgment_id: Mapped[str] = mapped_column(ForeignKey("judgment.id", ondelete="CASCADE"), index=True)
    version_key: Mapped[str] = mapped_column(String(96))
    source_url: Mapped[str | None] = mapped_column(Text)
    ocr_derived: Mapped[bool] = mapped_column(Boolean, default=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    char_count: Mapped[int | None] = mapped_column(Integer)
    preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    judgment: Mapped[Judgment] = relationship(back_populates="versions")
    paragraphs: Mapped[list[Paragraph]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="Paragraph.seq"
    )
    opinions: Mapped[list[Opinion]] = relationship(back_populates="version", cascade="all, delete-orphan")


class Opinion(Base):
    """Majority, concurring or dissenting opinion within one text version, by paragraph range."""

    __tablename__ = "opinion"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    text_version_id: Mapped[str] = mapped_column(
        ForeignKey("judgment_text_version.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # majority | concurring | dissenting | headnote
    author: Mapped[str | None] = mapped_column(String(160))
    seq_start: Mapped[int] = mapped_column(Integer)
    seq_end: Mapped[int] = mapped_column(Integer)

    version: Mapped[JudgmentTextVersion] = relationship(back_populates="opinions")


class Paragraph(Base):
    """The unit of retrieval and of pinpointing. `seq` is stable within a version; `printed_label` is what the text shows."""

    __tablename__ = "paragraph"
    __table_args__ = (
        UniqueConstraint("text_version_id", "seq", name="uq_paragraph_seq"),
        Index("ix_paragraph_version_label", "text_version_id", "printed_label"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    text_version_id: Mapped[str] = mapped_column(
        ForeignKey("judgment_text_version.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    printed_label: Mapped[str | None] = mapped_column(String(16))
    opinion_id: Mapped[str | None] = mapped_column(ForeignKey("opinion.id", ondelete="SET NULL"))
    role: Mapped[str | None] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)

    version: Mapped[JudgmentTextVersion] = relationship(back_populates="paragraphs")


class ParagraphAlias(Base):
    """Maps a printed paragraph label in one text version to the label in another (SCC vs official numbering)."""

    __tablename__ = "paragraph_alias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_version_id: Mapped[str] = mapped_column(ForeignKey("judgment_text_version.id", ondelete="CASCADE"))
    from_label: Mapped[str] = mapped_column(String(16))
    to_version_id: Mapped[str] = mapped_column(ForeignKey("judgment_text_version.id", ondelete="CASCADE"))
    to_label: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(32), default="alignment")


class CitationEdge(Base):
    """Citing judgment -> cited judgment with the treatment the citing court gave it. The citator."""

    __tablename__ = "citation_edge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    citing_id: Mapped[str] = mapped_column(ForeignKey("judgment.id", ondelete="CASCADE"), index=True)
    cited_id: Mapped[str | None] = mapped_column(ForeignKey("judgment.id", ondelete="SET NULL"), index=True)
    cited_alias: Mapped[str | None] = mapped_column(String(160))
    treatment: Mapped[str | None] = mapped_column(String(32))
    paragraph_id: Mapped[str | None] = mapped_column(ForeignKey("paragraph.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(32), default="extraction")


class JudgmentDigest(Base):
    """Computed once per judgment and cached forever; keyed by prompt version so it can be rebuilt deliberately."""

    __tablename__ = "judgment_digest"

    judgment_id: Mapped[str] = mapped_column(ForeignKey("judgment.id", ondelete="CASCADE"), primary_key=True)
    text_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("judgment_text_version.id", ondelete="SET NULL")
    )
    digest: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(96))
    prompt_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    judgment: Mapped[Judgment] = relationship(back_populates="digest")


class Brief(Base):
    """An uploaded or pasted brief, memorial or submission."""

    __tablename__ = "brief"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    matter_id: Mapped[str | None] = mapped_column(String(36), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    facts: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    citations: Mapped[list[BriefCitation]] = relationship(
        back_populates="brief", cascade="all, delete-orphan"
    )


class BriefCitation(Base):
    """One citation found in a brief, with the proposition it supports and how it resolved."""

    __tablename__ = "brief_citation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    brief_id: Mapped[str] = mapped_column(ForeignKey("brief.id", ondelete="CASCADE"), index=True)
    raw: Mapped[str] = mapped_column(String(200))
    normalized: Mapped[str | None] = mapped_column(String(160), index=True)
    span_start: Mapped[int] = mapped_column(Integer)
    span_end: Mapped[int] = mapped_column(Integer)
    claimed_pinpoint: Mapped[str | None] = mapped_column(String(32))
    proposition: Mapped[str | None] = mapped_column(Text)
    judgment_id: Mapped[str | None] = mapped_column(
        ForeignKey("judgment.id", ondelete="SET NULL"), index=True
    )
    resolution: Mapped[str] = mapped_column(String(16), default="pending")
    resolution_score: Mapped[float | None] = mapped_column(Float)

    brief: Mapped[Brief] = relationship(back_populates="citations")
    verdicts: Mapped[list[Verdict]] = relationship(back_populates="citation", cascade="all, delete-orphan")


class Verdict(Base):
    """The engine's output for one claim. Scalar columns are denormalised from `evidence` for the board."""

    __tablename__ = "verdict"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    brief_citation_id: Mapped[str] = mapped_column(
        ForeignKey("brief_citation.id", ondelete="CASCADE"), index=True
    )
    existence: Mapped[str] = mapped_column(String(16))
    location_status: Mapped[str | None] = mapped_column(String(16))
    support: Mapped[str | None] = mapped_column(String(16))
    voice: Mapped[str | None] = mapped_column(String(24))
    weight: Mapped[str | None] = mapped_column(String(16))
    treatment: Mapped[str | None] = mapped_column(String(32))
    applicability: Mapped[str | None] = mapped_column(String(16))
    grade: Mapped[str | None] = mapped_column(String(2))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[dict] = mapped_column(JSON)
    model_version: Mapped[str | None] = mapped_column(String(96))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    citation: Mapped[BriefCitation] = relationship(back_populates="verdicts")


class Job(Base):
    """Background work with progress, so the web app can stream it and a restart can resume it."""

    __tablename__ = "job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
