"""Verification as a job, so a browser can watch it happen.

Checking a brief is not a request-response affair. With a model configured each citation takes seconds,
and a memorial carries thirty of them; a page that posts a brief and waits is a page that looks broken
for two minutes and then, if anything times out on the way, has nothing to show for it.

So a brief becomes a job. Verdicts are appended as each citation finishes and the page is told about
each one as it lands, which means the board fills in front of the reader in the order the engine
actually works — and a citation that resolves to nothing appears immediately, before the ones that
need a model have started.

The store is a dictionary. The architecture calls for a jobs table, and it will need one when there is
more than one process; there is one process, jobs are worth nothing once the tab is closed, and a
table here would be a schema migration in exchange for nothing.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from orderorder.engine.verdict import CitationVerdict

# How many finished jobs to keep. Enough that a reader can go back to the previous brief; not so many
# that a long session holds every judgment it has read in memory.
MAX_JOBS = 20


@dataclass
class Job:
    """One brief being checked, and the verdicts so far."""

    id: str
    text: str
    source: str
    total: int = 0
    verdicts: list[CitationVerdict] = field(default_factory=list)
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished: bool = False
    model_configured: bool = False
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def done(self) -> int:
        return len(self.verdicts)

    def add(self, verdict: CitationVerdict) -> None:
        self.verdicts.append(verdict)
        self._wake()

    def finish(self, error: str | None = None) -> None:
        self.error = error
        self.finished = True
        self._wake()

    def _wake(self) -> None:
        """Release anyone waiting, then re-arm for the next change."""
        self._event.set()
        self._event.clear()

    def wait(self, timeout: float) -> None:
        self._event.wait(timeout)


class JobStore:
    """The jobs this process is holding. Oldest are dropped once there are too many."""

    def __init__(self, limit: int = MAX_JOBS) -> None:
        self._jobs: dict[str, Job] = {}
        self._limit = limit
        self._lock = threading.Lock()

    def create(self, text: str, source: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], text=text, source=source)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > self._limit:
                self._jobs.pop(next(iter(self._jobs)))
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def __len__(self) -> int:
        return len(self._jobs)


def watch(job: Job, *, poll: float = 1.0) -> Iterator[tuple[str, dict]]:
    """Yield (event, payload) for a job until it finishes.

    A heartbeat goes out on every poll whether or not anything changed, because a proxy that sees no
    bytes for a minute closes the connection and the page would sit at a stale count for ever with no
    way to know it had been cut off.
    """
    sent = 0
    while True:
        while sent < len(job.verdicts):
            yield "verdict", {"index": sent, "verdict": as_json(job.verdicts[sent])}
            sent += 1
        if job.finished:
            yield "done", {"checked": job.done, "error": job.error}
            return
        yield "progress", {"done": job.done, "total": job.total}
        job.wait(poll)


def as_json(verdict: CitationVerdict) -> dict:
    """A verdict as the page needs it. Nothing here is computed; it is the verdict, flattened.

    The findings carry their mode number as well as their words, because the taxonomy is how a reader
    checks the engine against the document rather than taking its word for it.
    """
    scope = verdict.scope
    return {
        "citation": verdict.citation_raw,
        "proposition": verdict.proposition,
        "grade": verdict.grade,
        "existence": verdict.existence,
        "support": verdict.support,
        "case": verdict.judgment_title,
        "key": verdict.canonical_key,
        "paragraph": verdict.paragraph_label,
        "claimed_pinpoint": verdict.claimed_pinpoint,
        "quote": verdict.quote if verdict.quote_verified else None,
        "quote_verified": verdict.quote_verified,
        "span": list(verdict.span) if verdict.span else None,
        "needs_review": verdict.needs_review,
        "review_reason": verdict.review_reason,
        "narrowed": scope.narrowed_proposition if scope else None,
        "findings": [
            {"mode": f.mode, "label": f.label, "detail": f.detail} for f in verdict.findings
        ],
        "voice": None if verdict.voice is None else {
            "voice": verdict.voice.voice,
            "reason": verdict.voice.reason,
            "cue": verdict.voice.cue,
        },
        "treatment": None if verdict.treatment is None else {
            "status": verdict.treatment.status,
            "note": verdict.treatment.note,
            "doubtful": verdict.treatment.is_doubtful,
        },
    }
