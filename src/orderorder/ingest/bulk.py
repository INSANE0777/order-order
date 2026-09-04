"""Ingest judgment text for the whole corpus, not one judgment at a time.

Authority search needs paragraphs for every judgment, not just the ones a brief happened to cite. That
is a few thousand PDFs to fetch and parse, so the work is arranged around three facts:

  * **The slow part is not the database.** Fetching a PDF and extracting its text is network and CPU;
    writing the paragraphs is milliseconds. So fetching and parsing run in a **process** pool and the
    writes stay on the calling process, which also keeps one SQLAlchemy session on one thread where it
    belongs. Processes rather than threads because pypdfium2 keeps global state and is not thread-safe:
    parsing several judgments at once in one process makes pages fail to load and leaves the library
    asserting on its own object tree at shutdown. Separate processes have separate state, and they use
    the other cores for the parsing, which is the CPU-bound half.
  * **It has to be resumable.** A judgment that already has this text version is skipped, so a run
    that dies at three thousand judgments resumes rather than restarts, and PDFs already on disk are
    not fetched again.
  * **Some judgments will fail.** A missing PDF or an unparseable one must not stop the run; each
    failure is recorded with its reason and reported at the end, so a retry can target them.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.db.models import Judgment, JudgmentTextVersion
from orderorder.ingest import pdf as pdf_mod
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

DEFAULT_WORKERS = 8


@dataclass
class Outcome:
    """What happened to one judgment."""

    canonical_key: str
    status: str  # stored | no_pdf | no_text | error
    paragraphs: int = 0
    pages: int = 0
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "stored"


@dataclass
class BulkResult:
    outcomes: list[Outcome] = field(default_factory=list)
    skipped: int = 0

    @property
    def stored(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.ok]

    @property
    def failed(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.ok]

    @property
    def paragraphs(self) -> int:
        return sum(o.paragraphs for o in self.outcomes)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
        if self.skipped:
            counts["already_had_text"] = self.skipped
        return counts


def judgments_needing_text(
    session: Session,
    *,
    version_key: str = "scr_pdf",
    years: list[int] | None = None,
    limit: int | None = None,
) -> list[Judgment]:
    """Judgments with a source path but no text of this version yet. The resume list."""
    have = select(JudgmentTextVersion.judgment_id).where(JudgmentTextVersion.version_key == version_key)
    query = (
        select(Judgment)
        .where(Judgment.source_id.is_not(None), Judgment.id.not_in(have))
        .order_by(Judgment.decided_on.desc())
    )
    rows = list(session.scalars(query).all())
    if years:
        wanted = {str(y) for y in years}
        rows = [j for j in rows if _year_of(j) in wanted]
    return rows[:limit] if limit else rows


def _year_of(judgment: Judgment) -> str | None:
    year = (judgment.extra or {}).get("year")
    if year:
        return str(year)
    return str(judgment.decided_on.year) if judgment.decided_on else None


def _fetch_and_parse(
    canonical_key: str, source_id: str, year: str | None, corpus_dir: Path
) -> tuple[str, ExtractedJudgment | None, str | None]:
    """Network and CPU only: no database, so this is safe to run in a worker process.

    Everything crossing the process boundary is picklable: strings, a Path, and an ExtractedJudgment
    of plain fields.
    """
    if not year:
        return canonical_key, None, "no year on the judgment, cannot locate its PDF"
    try:
        path = pdf_mod.fetch_pdf(source_id, year, corpus_dir)
        return canonical_key, pdf_mod.extract(path, source_id), None
    except Exception as exc:  # noqa: BLE001 - one bad judgment must not end the run
        return canonical_key, None, f"{type(exc).__name__}: {exc}"


def ingest_text_bulk(
    session: Session,
    judgments: list[Judgment],
    corpus_dir: Path,
    *,
    version_key: str = "scr_pdf",
    workers: int = DEFAULT_WORKERS,
    on_result: Callable[[Outcome, int, int], None] | None = None,
) -> BulkResult:
    """Fetch, parse and store text for each judgment. Returns what happened to every one of them."""
    result = BulkResult()
    total = len(judgments)
    if not total:
        return result

    by_key = {j.canonical_key: j for j in judgments}
    # More processes than cores buys nothing once parsing saturates them, and each one costs a Python
    # interpreter's memory.
    pool_size = max(1, min(workers, (os.cpu_count() or 4)))
    with ProcessPoolExecutor(max_workers=pool_size) as pool:
        futures = [
            pool.submit(_fetch_and_parse, j.canonical_key, j.source_id or "", _year_of(j), corpus_dir)
            for j in judgments
        ]
        for done, future in enumerate(as_completed(futures), start=1):
            canonical_key, extracted, error = future.result()
            judgment = by_key[canonical_key]

            if error is not None:
                outcome = Outcome(canonical_key, "no_pdf", detail=error)
            elif extracted is None or not extracted.has_judgment:
                outcome = Outcome(
                    canonical_key,
                    "no_text",
                    pages=extracted.page_count if extracted else 0,
                    detail="no judgment text found after cleaning",
                )
            else:
                try:
                    stored = store_extracted(
                        session,
                        judgment,
                        extracted,
                        version_key=version_key,
                        source_url=pdf_mod.pdf_url(judgment.source_id or "", _year_of(judgment) or ""),
                    )
                    session.commit()
                    outcome = Outcome(
                        canonical_key, "stored", paragraphs=stored.paragraphs, pages=extracted.page_count
                    )
                except Exception as exc:  # noqa: BLE001 - a bad write must not end the run either
                    session.rollback()
                    outcome = Outcome(canonical_key, "error", detail=f"{type(exc).__name__}: {exc}")

            result.outcomes.append(outcome)
            if on_result is not None:
                on_result(outcome, done, total)
    return result


def write_failures(result: BulkResult, path: Path) -> int:
    """Record failures so a retry can name them. Returns how many were written."""
    failures = result.failed
    if not failures:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for outcome in failures:
            handle.write(f"{outcome.canonical_key}\t{outcome.status}\t{outcome.detail or ''}\n")
    return len(failures)


def read_failures(path: Path) -> Iterator[str]:
    """Canonical keys from a failures file, for a targeted retry."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("\t", 1)[0].strip()
        if key:
            yield key
