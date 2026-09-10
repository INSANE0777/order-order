"""The judgment digest, computed from what the corpus already stores.

The architecture's digest stage (docs/ARCHITECTURE.md §3.4) gives every judgment a cached summary
the checks can read without re-reading the judgment: the publisher's headnote, the paragraphs the
role labeller called holdings, the disposition. The weight check was designed to read exactly this
-- ratio versus obiter asks whether a passage is necessary to the outcome, and the headnote is the
editor's century-old answer to that same question.

This first version is aggregation, not generation: everything in the digest is text the corpus
already holds, selected and truncated by rule. A model-assisted digest can replace it later by
writing a new prompt_version -- the table is keyed for that rebuild.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.db.models import (
    Judgment,
    JudgmentDigest,
    JudgmentTextVersion,
    Opinion,
    Paragraph,
)

DIGEST_MODEL = "rule:headnote-aggregation"
PROMPT_VERSION = "v0-rule"
HEADNOTE_CHARS = 2000
HOLDING_SNIPPET_CHARS = 240
MAX_HOLDINGS = 5


@dataclass
class DigestResult:
    """Counts of what was digested, for the CLI line."""

    written: int = 0
    skipped_existing: int = 0
    no_text: int = 0
    per_role: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"{self.written:,} digests written ({self.skipped_existing:,} already present, "
            f"{self.no_text:,} without a preferred text version)"
        )


def _preferred_version_id(session: Session, judgment_id: str) -> str | None:
    return session.scalars(
        select(JudgmentTextVersion.id)
        .where(JudgmentTextVersion.judgment_id == judgment_id)
        .where(JudgmentTextVersion.preferred.is_(True))
    ).first()


def digest_one(session: Session, judgment: Judgment) -> tuple[dict, str | None] | None:
    """The digest dict for one judgment, from stored text alone. None if there is no text."""
    version_id = _preferred_version_id(session, judgment.id)
    if version_id is None:
        return None

    paras = session.execute(
        select(Paragraph, Opinion.kind)
        .outerjoin(Opinion, Opinion.id == Paragraph.opinion_id)
        .where(Paragraph.text_version_id == version_id)
        .order_by(Paragraph.seq)
    ).all()

    headnote_parts: list[str] = []
    holdings: list[dict] = []
    disposition = ""
    role_counts: dict[str, int] = {}
    for para, kind in paras:
        role = para.role or "none"
        role_counts[role] = role_counts.get(role, 0) + 1
        if kind == "headnote" and len(" ".join(headnote_parts)) < HEADNOTE_CHARS:
            headnote_parts.append(para.body)
        if role == "ratio" and len(holdings) < MAX_HOLDINGS:
            holdings.append(
                {
                    "label": para.printed_label,
                    "text": para.body[:HOLDING_SNIPPET_CHARS],
                }
            )
        if role == "disposition" and not disposition:
            disposition = para.body[:HOLDING_SNIPPET_CHARS]

    digest = {
        "headnote": " ".join(headnote_parts)[:HEADNOTE_CHARS],
        "holdings": holdings,
        "disposition": disposition,
        "role_counts": role_counts,
    }
    return digest, version_id


def build_digests(session: Session, *, dry_run: bool = False, refresh: bool = False) -> DigestResult:
    """Digest every judgment that has a preferred text version and lacks one already."""
    result = DigestResult()
    existing = {
        row
        for row in session.scalars(select(JudgmentDigest.judgment_id)).all()
    }
    if refresh and existing and not dry_run:
        # A rebuild replaces, not stacks: the old digests go before the new ones land.
        session.query(JudgmentDigest).delete()
        session.flush()
    judgment_ids = session.scalars(select(Judgment.id)).all()
    started = time.monotonic()

    for i, judgment_id in enumerate(judgment_ids):
        if judgment_id in existing and not refresh:
            result.skipped_existing += 1
            continue
        judgment = session.get(Judgment, judgment_id)
        outcome = digest_one(session, judgment)
        if outcome is None:
            result.no_text += 1
            continue
        digest, version_id = outcome
        if not dry_run:
            session.add(
                JudgmentDigest(
                    judgment_id=judgment.id,
                    text_version_id=version_id,
                    digest=digest,
                    model=DIGEST_MODEL,
                    prompt_version=PROMPT_VERSION,
                )
            )
        result.written += 1
        for role, count in digest["role_counts"].items():
            result.per_role[role] = result.per_role.get(role, 0) + count
        if not dry_run and result.written % 2000 == 0:
            session.commit()
        if result.written % 5000 == 0 and time.monotonic() - started > 45:
            # Yield so a human watching the log sees motion on a corpus this size.
            session.commit()

    if not dry_run:
        session.commit()
    return result
