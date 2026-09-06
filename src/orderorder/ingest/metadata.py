"""Import AWS Open Data parquet metadata into `judgment` and `citation_alias`.

This is the data spine: after it runs, the resolver can decide whether a cited case exists and which
judgment it is, without any text, any embeddings and any model. Columns in the source (verified against
the 2019 file):

    title, petitioner, respondent, description, judge, author_judge, citation, case_id, cnr,
    decision_date, disposal_nature, court, available_languages, raw_html, path, nc_display, year

`case_id` carries the neutral citation ("2019 INSC 770") and `citation` the official SCR citation
("[2019] 9 S.C.R. 593"). Both become aliases; the neutral citation is the canonical key when present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.citations.grammar import extract_citations
from orderorder.db.models import CitationAlias, Judgment

COURT = "Supreme Court of India"
SOURCE = "aws_open_data"

_JUDGE_SPLIT = re.compile(r"\s*,\s*|\s+AND\s+", re.IGNORECASE)
_HONORIFIC = re.compile(r"\b(?:HON'?BLE|MR\.?|MRS\.?|MS\.?|JUSTICE|SHRI|SMT\.?|DR\.?)\b\.?", re.IGNORECASE)


@dataclass
class ImportStats:
    rows: int = 0
    judgments_added: int = 0
    judgments_skipped: int = 0
    aliases_added: int = 0
    no_canonical_key: int = 0
    unparsed_citations: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "rows": self.rows,
            "judgments_added": self.judgments_added,
            "judgments_skipped": self.judgments_skipped,
            "aliases_added": self.aliases_added,
            "no_canonical_key": self.no_canonical_key,
            "unparsed_citations": self.unparsed_citations,
        }


# A cause title with nothing after the "versus". The open data carries eighteen of them and they are
# all the same shape: a suo motu or reference matter -- "IN RE : SECTION 6A OF THE CITIZENSHIP ACT
# 1955 versus" -- which has a subject and no respondent. Left alone it reaches the table of
# authorities in a draft as "... versus," which reads as a bug in the tool rather than in the data.
DANGLING_VERSUS = re.compile(r"(?i)\s+(?:versus|vs\.?|v\.)\s*$")


def tidy_title(title: str | None) -> str | None:
    """A cause title with no party dangling off the end of it."""
    if not title:
        return title
    return DANGLING_VERSUS.sub("", title).strip() or title


def parse_judges(raw: str | None) -> list[str]:
    """Split the judge field into names. Bench strength is the length of this list."""
    if not raw or not str(raw).strip():
        return []
    parts = [_HONORIFIC.sub("", p).strip(" .,") for p in _JUDGE_SPLIT.split(str(raw))]
    return [re.sub(r"\s+", " ", p) for p in parts if p and len(p) > 1]


def parse_decision_date(raw: str | None) -> date | None:
    """The source uses DD-MM-YYYY; a few rows are blank or malformed."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def canonical_key(case_id: str | None, path: str | None, year: str | int | None) -> str | None:
    """Neutral citation when present, else a stable key derived from the source path."""
    if case_id and str(case_id).strip():
        found = extract_citations(str(case_id))
        if found and found[0].reporter == "INSC":
            return found[0].normalized
    if path and str(path).strip():
        return f"SCP:{year}:{str(path).strip()}"
    return None


def _clean(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def row_to_judgment(row: pd.Series) -> tuple[Judgment, list[tuple[str, str, str]]] | None:
    """Build a Judgment and its (reporter, citation_string, normalized) aliases from one parquet row.

    Returns None when the row has no usable canonical key.
    """
    key = canonical_key(_clean(row.get("case_id")), _clean(row.get("path")), _clean(row.get("year")))
    if not key:
        return None

    judges = parse_judges(_clean(row.get("judge")))
    title = tidy_title(_clean(row.get("title")))
    if not title:
        petitioner = _clean(row.get("petitioner")) or "Unknown"
        respondent = _clean(row.get("respondent")) or "Unknown"
        title = f"{petitioner} versus {respondent}"

    neutral = None
    if case_id := _clean(row.get("case_id")):
        found = extract_citations(case_id)
        if found and found[0].reporter == "INSC":
            neutral = found[0].raw

    judgment = Judgment(
        canonical_key=key,
        court=COURT,
        title=title,
        decided_on=parse_decision_date(_clean(row.get("decision_date"))),
        neutral_citation=neutral,
        bench_strength=len(judges) or None,
        judges=judges or None,
        language="en",
        source=SOURCE,
        source_id=_clean(row.get("path")),
        source_url=None,
        extra={
            "cnr": _clean(row.get("cnr")),
            "disposal_nature": _clean(row.get("disposal_nature")),
            "available_languages": _clean(row.get("available_languages")),
            "nc_display": _clean(row.get("nc_display")),
            "petitioner": _clean(row.get("petitioner")),
            "respondent": _clean(row.get("respondent")),
            "year": _clean(row.get("year")),
        },
    )

    aliases: list[tuple[str, str, str]] = []
    for field in ("case_id", "citation"):
        text = _clean(row.get(field))
        if not text:
            continue
        for citation in extract_citations(text):
            aliases.append((citation.reporter, citation.raw, citation.normalized))
    return judgment, aliases


def import_parquet(session: Session, parquet_path: Path, *, limit: int | None = None) -> ImportStats:
    """Import one year of metadata. Idempotent: existing canonical keys and aliases are left alone."""
    frame = pd.read_parquet(parquet_path)
    if limit:
        frame = frame.head(limit)
    stats = ImportStats(rows=len(frame))

    existing_keys = set(session.scalars(select(Judgment.canonical_key)).all())
    existing_aliases = set(session.scalars(select(CitationAlias.normalized)).all())
    pending: dict[str, Judgment] = {}

    for _, row in frame.iterrows():
        built = row_to_judgment(row)
        if built is None:
            stats.no_canonical_key += 1
            continue
        judgment, aliases = built
        if not aliases:
            stats.unparsed_citations += 1

        if judgment.canonical_key in existing_keys or judgment.canonical_key in pending:
            stats.judgments_skipped += 1
            target = pending.get(judgment.canonical_key)
            if target is None:
                target = session.scalars(
                    select(Judgment).where(Judgment.canonical_key == judgment.canonical_key)
                ).first()
        else:
            session.add(judgment)
            pending[judgment.canonical_key] = judgment
            stats.judgments_added += 1
            target = judgment

        if target is None:
            continue
        for reporter, citation_string, normalized in aliases:
            if normalized in existing_aliases:
                continue
            existing_aliases.add(normalized)
            session.add(
                CitationAlias(
                    judgment=target,
                    reporter=reporter,
                    citation_string=citation_string,
                    normalized=normalized,
                    source=SOURCE,
                )
            )
            stats.aliases_added += 1

    session.flush()
    return stats
