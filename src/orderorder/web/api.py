"""The engine behind a browser.

`docs/PRD.md` A14: a verdict board, an annotated brief, a judgment viewer with the paragraph
highlighted. All three exist as text already; what a page adds is that they can be read *together*.
An advocate revising a memorial wants to click a flag, see the paragraph the engine actually read, and
see the sentence highlighted inside it — three things that are three commands and a lot of scrolling
at a terminal.

**No Node.** The architecture names Next.js, and this serves one static HTML file instead. The reason
is not laziness about the framework: the engine's output is a list of verdicts and a document to mark
up, which is a page rather than an application, and a build toolchain would put an npm install and a
bundler between `uv run orderorder serve` and a working demo — on a machine whose system drive has no
room for one. If the drafting workspace grows into something with real client state, that is the point
to reconsider, and nothing here would have to be thrown away: the API is the same either way.

Every route is read-only against the knowledge base. Nothing this serves can change a judgment.

The app is handed the way it opens a session rather than reaching for the global one. That is what
lets a test point it at a database of its own with certainty — the module-level caches behind
`get_session` can be left stale by anything that reloads the config module, and a test that
silently talks to the real nine-thousand-judgment corpus is worse than one that fails.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from orderorder import __version__
from orderorder.db.models import Judgment, JudgmentTextVersion
from orderorder.db.session import get_session
from orderorder.drafting.assemble import assemble
from orderorder.drafting.attack import attack_draft
from orderorder.drafting.plan import PlanError, parse_plan
from orderorder.drafting.render import to_markdown
from orderorder.drafting.word import write_docx
from orderorder.engine import authority as authority_gate
from orderorder.engine import search
from orderorder.engine.graph import verify_text
from orderorder.engine.memo import render_memo, write_memo
from orderorder.engine.providers import build_structured
from orderorder.engine.report import annotate_brief, verification_report
from orderorder.engine.schemas import (
    ApplicabilityAssessment,
    ScopeAssessment,
    VoiceAssessment,
    WeightAssessment,
)
from orderorder.ingest.brief import read_brief
from orderorder.ingest.store import load_paragraphs
from orderorder.web.auth import TOKEN_ENV, token_required
from orderorder.web.jobs import (
    DraftJob,
    Job,
    JobStore,
    Watched,
    as_json,
    binding_json,
    watch,
    watch_draft,
)

STATIC = Path(__file__).parent / "static"

# How long a case plan may be. A plan is issues and sentences, not a bundle; past this something
# other than a plan has been pasted in.
MAX_PLAN_CHARS = 60_000

# How long a brief may be. A memorial is tens of kilobytes; anything past this is a book, and checking
# it would tie the single worker up for an hour with no way to say so.
MAX_BRIEF_CHARS = 400_000
# And how large a file. A memorial is under a megabyte; a bundle of annexures is not a brief.
MAX_UPLOAD_BYTES = 25_000_000


class DraftRequest(BaseModel):
    plan: str = Field(description="A case plan. See `drafting/plan.py` for the format.")
    use_model: bool = Field(
        default=True,
        description="Run the checks that need a language model. Without one nothing can be bound.",
    )


class VerifyRequest(BaseModel):
    text: str = Field(description="The brief, memorial or passage to check.")
    facts: str = Field(default="", description="The facts of the present matter, if there are any.")
    use_model: bool = Field(
        default=True,
        description="Run the checks that need a language model. Off runs the eight that do not.",
    )


def create_app(
    *, store: JobStore | None = None, session_factory=get_session, token: str | None = None
) -> FastAPI:
    app = FastAPI(title="OrderOrder", version=__version__, docs_url="/api/docs")

    # One place, checked before anything else runs. A token configured per-route is a token somebody
    # forgets on the route added next week, and the route added next week is the upload endpoint.
    @app.middleware("http")
    async def _require_token(request, call_next):
        from fastapi.responses import JSONResponse
        from starlette.exceptions import HTTPException as StarletteHTTPException

        try:
            token_required(request, token)
        except StarletteHTTPException as refused:
            return JSONResponse(
                {"detail": refused.detail}, status_code=refused.status_code, headers=refused.headers
            )
        return await call_next(request)
    # `is not None`, not `or`: a JobStore defines __len__, so an empty one is falsy and `or` would
    # quietly hand back a different store than the caller passed in.
    jobs = store if store is not None else JobStore()
    open_session = session_factory

    @app.get("/api/health")
    def health() -> dict:
        """What the corpus holds and whether a model can be reached, for the page's status line."""
        with open_session() as session:
            judgments = session.scalar(select(Judgment.id).limit(1))
            held = session.query(JudgmentTextVersion).count()
        return {
            "version": __version__,
            "corpus_ready": judgments is not None,
            "judgments_with_text": held,
            "model_configured": build_structured(ScopeAssessment) is not None,
        }

    @app.post("/api/verify")
    def start_verification(request: VerifyRequest) -> dict:
        """Take a brief and start checking it. Returns at once with a job to watch."""
        text = request.text.strip()
        if not text:
            raise HTTPException(400, "there is nothing to check")
        if len(text) > MAX_BRIEF_CHARS:
            raise HTTPException(413, f"a brief may be up to {MAX_BRIEF_CHARS:,} characters")

        job = jobs.create(text, source="pasted text")
        job.model_configured = request.use_model and build_structured(ScopeAssessment) is not None
        threading.Thread(target=_run, args=(job, request, open_session), daemon=True).start()
        return {"job": job.id, "model_configured": job.model_configured}

    @app.post("/api/upload")
    async def upload(file: UploadFile) -> dict:
        """Read a brief out of a PDF or DOCX and hand back the text, without checking anything yet.

        The text is shown before it is checked, on purpose. A verdict on a document the reader has not
        seen is a verdict neither of you can point at, and a PDF that came out mangled should be
        obvious in a second rather than discovered through nine inexplicable phantom citations.
        """
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"a file may be up to {MAX_UPLOAD_BYTES // 1_000_000} MB")
        try:
            brief = read_brief(data, file.filename or "")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - a broken file must not read as an empty brief
            raise HTTPException(400, f"that file could not be read: {type(exc).__name__}") from exc

        if not brief.text.strip():
            raise HTTPException(
                422,
                brief.note
                or "no text came out of that file; if it is a scan it needs OCR before it can be checked",
            )
        return {
            "text": brief.text,
            "kind": brief.kind,
            "pages": brief.pages,
            "note": brief.note,
            "filename": file.filename,
        }

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str) -> dict:
        job = _find(jobs, job_id)
        return {
            "job": job.id,
            "done": job.done,
            "total": job.total,
            "finished": job.finished,
            "error": job.error,
            "model_configured": job.model_configured,
            "verdicts": [as_json(v) for v in job.verdicts],
        }

    @app.get("/api/jobs/{job_id}/events")
    def stream_job(job_id: str) -> StreamingResponse:
        """Server-sent events: one per verdict as it lands, then done.

        The board fills in the order the engine works, so a phantom citation — settled against the
        alias table in milliseconds — is on screen while the ones that need a model are still running.
        """
        job = _find(jobs, job_id)

        def events() -> Iterator[str]:
            for name, payload in watch(job):
                yield f"event: {name}\ndata: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/annotated", response_class=PlainTextResponse)
    def annotated(job_id: str) -> str:
        job = _find(jobs, job_id)
        return annotate_brief(job.text, job.verdicts)

    @app.get("/api/jobs/{job_id}/report", response_class=PlainTextResponse)
    def report(job_id: str) -> str:
        job = _find(jobs, job_id)
        return verification_report(job.verdicts, source=job.source)

    @app.get("/api/jobs/{job_id}/memo/{index}", response_class=PlainTextResponse)
    def memo(job_id: str, index: int) -> str:
        job = _find(jobs, job_id)
        if not 0 <= index < len(job.verdicts):
            raise HTTPException(404, "no such citation in this job")
        return "\n".join(render_memo(write_memo(job.verdicts[index])))

    @app.post("/api/plan")
    def check_plan(request: DraftRequest) -> dict:
        """Read a plan and hand back what it says, without binding anything.

        The page shows the parsed issues and propositions before it runs, for the same reason the
        brief is shown before it is checked: an advocate should see what the tool thinks they wrote
        while a typo is still a typo, rather than after four minutes of model calls.
        """
        try:
            plan = parse_plan(request.plan)
        except PlanError as error:
            raise HTTPException(400, str(error)) from error
        return {
            "court": plan.court,
            "cause": plan.cause,
            "parties": plan.parties,
            "appearing_for": plan.appearing_for,
            "dates": plan.dates,
            "issues": [{"title": i.title, "propositions": i.propositions} for i in plan.issues],
            "prayer": plan.prayer,
            "propositions": len(plan.propositions),
        }

    @app.post("/api/draft")
    def start_draft(request: DraftRequest) -> dict:
        """Take a case plan and start binding it. Returns at once with a job to watch."""
        if len(request.plan) > MAX_PLAN_CHARS:
            raise HTTPException(413, f"a plan may be up to {MAX_PLAN_CHARS:,} characters")
        try:
            plan = parse_plan(request.plan)
        except PlanError as error:
            raise HTTPException(400, str(error)) from error

        job = jobs.create_draft(plan, source="pasted plan")
        job.total = len(plan.propositions)
        job.model_configured = request.use_model and build_structured(ScopeAssessment) is not None
        threading.Thread(target=_draft, args=(job, open_session), daemon=True).start()
        return {"job": job.id, "model_configured": job.model_configured, "total": job.total}

    @app.get("/api/draft/{job_id}")
    def read_draft(job_id: str) -> dict:
        job = _find_draft(jobs, job_id)
        return {
            "job": job.id,
            "done": job.done,
            "total": job.total,
            "finished": job.finished,
            "error": job.error,
            "model_configured": job.model_configured,
            "bindings": [binding_json(p, job.bindings[p]) for p in job.order],
            "attacks": [
                {"kind": a.kind, "says": a.says, "fix": a.fix, "citation": a.citation}
                for a in job.attacks
            ],
        }

    @app.get("/api/draft/{job_id}/events")
    def stream_draft(job_id: str) -> StreamingResponse:
        job = _find_draft(jobs, job_id)

        def events() -> Iterator[str]:
            for name, payload in watch_draft(job):
                yield f"event: {name}\ndata: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/draft/{job_id}/document", response_class=PlainTextResponse)
    def draft_document(job_id: str) -> str:
        job = _find_draft(jobs, job_id)
        if job.document is None:
            raise HTTPException(409, "the draft is still being assembled")
        return job.document

    @app.get("/api/draft/{job_id}/document.docx")
    def draft_docx(job_id: str) -> FileResponse:
        """The submission as a Word file, written to a temporary path and handed straight back."""
        job = _find_draft(jobs, job_id)
        if job.document is None:
            raise HTTPException(409, "the draft is still being assembled")
        draft = assemble(job.plan, job.bindings)
        path = Path(tempfile.gettempdir()) / f"orderorder-{job.id}.docx"
        write_docx(draft, path, job.attacks)
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="written-submissions.docx",
        )

    @app.get("/api/judgment/{key}")
    def judgment(key: str, highlight: str | None = None) -> dict:
        """A judgment's paragraphs, so the page can show the one the verdict rests on.

        `highlight` is the verified quote. It is found here rather than in the browser because the same
        normalisation that verified it has to find it: matching raw text in JavaScript would fail on
        exactly the curly quotes and soft hyphens the verifier exists to survive, and would then show
        nothing highlighted on a citation that is perfectly sound.

        The paragraph comes back already cut into the part before the quote, the quote, and the part
        after, rather than as a body and a pair of offsets. Python counts characters and JavaScript
        counts UTF-16 units, so the two agree only while nothing in the corpus lies outside the basic
        plane — true of these 409,499 paragraphs today and enforced by nothing. Three strings cannot
        drift.
        """
        from orderorder.engine.quotes import find_quote

        with open_session() as session:
            record = session.scalars(select(Judgment).where(Judgment.canonical_key == key)).first()
            if record is None:
                raise HTTPException(404, f"no judgment with key {key}")
            paragraphs = load_paragraphs(session, record.id)
            citation = _preferred_citation(session, record.id)

        out = []
        for paragraph in paragraphs:
            found = find_quote(highlight, paragraph.body) if highlight else None
            body, quoted, rest = paragraph.body, "", ""
            if found is not None and found.found:
                body = paragraph.body[: found.char_start]
                quoted = paragraph.body[found.char_start : found.char_end]
                rest = paragraph.body[found.char_end :]
            out.append(
                {
                    "seq": paragraph.seq,
                    "label": paragraph.printed_label,
                    "body": body,
                    "quoted": quoted,
                    "rest": rest,
                    "opinion": paragraph.opinion_kind,
                    "author": paragraph.opinion_author,
                }
            )
        return {
            "key": record.canonical_key,
            "title": record.title,
            "court": record.court,
            "decided_on": record.decided_on.isoformat() if record.decided_on else None,
            "bench_strength": record.bench_strength,
            "citation": citation,
            "paragraphs": out,
        }

    @app.get("/api/search")
    def find(q: str, top: int = 5) -> dict:
        """The other direction: a proposition in, judgments and the line out."""
        if not q.strip():
            raise HTTPException(400, "there is nothing to search for")
        with open_session() as session:
            if not search.index_exists(session):
                raise HTTPException(409, "the full-text index has not been built; run `orderorder index`")
            found = search.find_authorities(session, q, top=top)
            return {
                "query": q,
                "authorities": [
                    {
                        "key": a.canonical_key,
                        "title": a.title,
                        "citation": a.citation,
                        "pinpoint": a.pinpoint,
                        "paragraph": a.paragraph_label,
                        "decided_on": a.decided_on,
                        "bench_strength": a.bench_strength,
                        "score": a.score,
                        "line": a.line,
                        "voice": a.voice.voice if a.voice else None,
                        "doubtful": bool(a.treatment and a.treatment.is_doubtful),
                        "treatment_note": a.treatment.note if a.treatment else None,
                    }
                    for a in found
                ],
            }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app


def _find(jobs: JobStore, job_id: str) -> Job:
    return _of_kind(jobs, job_id, Job)


def _find_draft(jobs: JobStore, job_id: str) -> DraftJob:
    return _of_kind(jobs, job_id, DraftJob)


def _of_kind(jobs: JobStore, job_id: str, kind: type) -> Watched:
    """One store holds both sorts of job, so the id has to name the right one."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "no such job; it may have been dropped when the server restarted")
    if not isinstance(job, kind):
        raise HTTPException(404, "that job is not of this kind")
    return job


def _draft(job: DraftJob, open_session) -> None:
    """Bind one plan, on its own thread, appending bindings as they finish.

    The document is assembled once, at the end. A submission half-built is not a document anybody
    should be shown, and the page has the bindings as they land in any case.
    """
    try:
        model = build_structured(ScopeAssessment) if job.model_configured else None
        with open_session() as session:
            if not search.index_exists(session):
                search.build_index(session)
            for proposition in job.plan.propositions:
                job.add(proposition, authority_gate.bind_proposition(session, proposition, model))
            draft = assemble(job.plan, job.bindings)
            job.attacks = attack_draft(session, draft)
            job.document = to_markdown(draft, job.attacks)
        job.finish()
    except Exception as exc:  # noqa: BLE001 - the page needs to be told, whatever went wrong
        job.finish(error=f"{type(exc).__name__}: {exc}")


def _preferred_citation(session, judgment_id: str) -> str | None:
    from orderorder.db.models import CitationAlias

    alias = session.scalars(
        select(CitationAlias)
        .where(CitationAlias.judgment_id == judgment_id)
        .order_by(CitationAlias.reporter, CitationAlias.citation_string)
    ).first()
    return alias.citation_string if alias else None


def _run(job: Job, request: VerifyRequest, open_session) -> None:
    """Check one brief, on its own thread, appending verdicts as they finish."""
    try:
        use = job.model_configured
        with open_session() as session:
            verify_text(
                session,
                job.text,
                build_structured(ScopeAssessment) if use else None,
                voice_model=build_structured(VoiceAssessment) if use else None,
                weight_model=build_structured(WeightAssessment) if use else None,
                facts_model=(
                    build_structured(ApplicabilityAssessment) if use and request.facts.strip() else None
                ),
                matter_facts=request.facts,
                on_found=lambda count: setattr(job, "total", count),
                on_verdict=job.add,
            )
        job.finish()
    except Exception as exc:  # noqa: BLE001 - the page needs to be told, whatever went wrong
        job.finish(error=f"{type(exc).__name__}: {exc}")


# The module-level application uvicorn imports by name, so `--reload` can re-import it. The token
# comes from the environment here because uvicorn constructs this one itself.
app = create_app(token=os.environ.get(TOKEN_ENV) or None)
