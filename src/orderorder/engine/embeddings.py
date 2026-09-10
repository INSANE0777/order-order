"""The dense half of retrieval: matching what a proposition means, not what it says.

The lexical half finds a line it has been given word for word — 91% of the time it puts the right
judgment first. Given the same proposition in an advocate's own words it manages 33%, because BM25 and
proximity match *words*, and a paraphrase shares none. That gap is measured, in
`docs/ARCHITECTURE.md` section 11.4, and nothing on the lexical side moves it.

So: every paragraph gets a vector, a query gets a vector, and the paragraphs nearest the query join
the lexical rankings through the same reciprocal rank fusion. Fusion rather than replacement, because
the two fail in opposite directions. A quoted line is found exactly by the lexical half and only
approximately by this one; a paraphrase is the reverse. Neither is the retriever.

**The model.** `docs/TECH_STACK.md` specifies BGE-M3, embedded in bulk on a borrowed GPU. Measured on
the machine this is developed on — eight CPU cores, no GPU — a small sentence transformer manages 13
paragraphs a second, which is 8.3 hours for this corpus and not something anyone will re-run when it
grows. A *static* model does 1,800 a second, and the whole corpus in under four minutes, because it
has no transformer to run forward: the token vectors are a lookup table and the sentence vector is
their pooled average.

That trade is deliberate and it is the smaller model that goes in first. The question the numbers
actually pose is whether *any* dense retrieval closes the paraphrase gap, and a model that answers it
in four minutes answers it today; if the answer is yes, the case for spending eight hours or a GPU
session on a stronger one is made rather than assumed. Both backends are here and the store records
which one wrote it, so the upgrade is a rebuild rather than a rewrite. The dimension is read from the
model rather than assumed.

**The store.** A memory-mapped float16 matrix beside the database, and a list of paragraph ids in the
same order. Not pgvector, because the corpus is in SQLite; not a vector database, because 409,499
rows is a 300 MB matrix and a matrix multiply, and adding a service to do that would be adding a
service. Float16 halves the file and costs nothing measurable in ranking, since only the order of the
scores matters. It is memory-mapped and read in blocks so that searching does not require the whole
matrix resident, because holding all of it at once is enough to get the process killed on a machine
with no memory to spare.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.config import get_settings
from orderorder.db.models import JudgmentTextVersion, Opinion, Paragraph

# A static model: no transformer forward pass, so the whole corpus embeds in minutes on a CPU.
DEFAULT_MODEL = "minishlab/potion-base-8M"
# The stronger option, for a machine with a GPU or an overnight window. Same interface, same store.
TRANSFORMER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Which backend loads a name. Static models are distributed under this account; anything else is a
# sentence transformer.
STATIC_PREFIX = "minishlab/"
# How many paragraphs go to the model at once. Large enough to keep eight cores busy, small enough
# that a batch of long paragraphs does not become the reason the machine runs out of memory.
BATCH = 2048
# How many rows are read from the matrix at a time when scoring a query.
BLOCK = 32_768
# A paragraph shorter than this carries no proposition — "Leave granted." — and a vector for it only
# adds noise to the ranking.
MIN_CHARS = 60


@dataclass
class VectorStore:
    """Paragraph vectors on disk, and which paragraphs they belong to."""

    directory: Path

    @property
    def vectors_path(self) -> Path:
        return self.directory / "paragraphs.f16.npy"

    @property
    def index_path(self) -> Path:
        return self.directory / "paragraphs.index.json"

    @property
    def exists(self) -> bool:
        return self.vectors_path.exists() and self.index_path.exists()

    def read_index(self) -> dict:
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def open(self) -> tuple[np.memmap, list[str], dict]:
        """The matrix, the paragraph ids in its row order, and what wrote it."""
        index = self.read_index()
        matrix = np.load(self.vectors_path, mmap_mode="r")
        return matrix, index["paragraph_ids"], index

    def write(self, vectors: np.ndarray, paragraph_ids: list[str], model: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        np.save(self.vectors_path, vectors.astype(np.float16))
        self.write_index(paragraph_ids, model, int(vectors.shape[1]))

    def write_index(self, paragraph_ids: list[str], model: str, dimension: int) -> None:
        """The index alone -- for the API path, which fills a preallocated matrix as it streams."""
        self.index_path.write_text(
            json.dumps(
                {
                    "model": model,
                    "dimension": dimension,
                    "count": len(paragraph_ids),
                    "paragraph_ids": paragraph_ids,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def finalize(self, paragraph_ids: list[str], model: str) -> None:
        """Name the matrix: which model wrote it, and which paragraphs sit in which row."""
        matrix = np.load(self.vectors_path, mmap_mode="r")
        self.write_index(paragraph_ids, model, int(matrix.shape[1]))


def default_store() -> VectorStore:
    return VectorStore(get_settings().data_dir / "vectors")


_model_cache: dict[str, object] = {}


def load_model(name: str = DEFAULT_MODEL):
    """The encoder, loaded once per process. Downloads on first use, then reads from the local cache."""
    if name not in _model_cache:
        if name.startswith(STATIC_PREFIX):
            from model2vec import StaticModel

            _model_cache[name] = StaticModel.from_pretrained(name)
        else:
            from sentence_transformers import SentenceTransformer

            _model_cache[name] = SentenceTransformer(name)
    return _model_cache[name]


def encode(texts: list[str], *, model_name: str = DEFAULT_MODEL, batch: int = BATCH) -> np.ndarray:
    """Unit-length vectors for a list of texts, so cosine similarity is a dot product."""
    model = load_model(model_name)
    if model_name.startswith(STATIC_PREFIX):
        vectors = np.asarray(model.encode(texts), dtype=np.float32)
        # A static model returns unnormalised vectors; the rest of this module assumes unit length so
        # that a dot product is the cosine.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1.0, norms)
    return np.asarray(
        model.encode(
            texts,
            batch_size=batch,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ),
        dtype=np.float32,
    )


def paragraphs_to_embed(session: Session) -> list[tuple[str, str]]:
    """(paragraph id, text) for everything worth embedding, in a stable order.

    The same two exclusions the full-text index makes, for the same reasons: only the preferred text
    version of a judgment, so one holding does not come back twice under two numberings, and never the
    publisher's headnote, which is not the court's words and should never be offered as authority.
    """
    rows = session.execute(
        select(Paragraph.id, Paragraph.body)
        .join(JudgmentTextVersion, JudgmentTextVersion.id == Paragraph.text_version_id)
        .outerjoin(Opinion, Opinion.id == Paragraph.opinion_id)
        .where(JudgmentTextVersion.preferred.is_(True))
        .where((Opinion.kind.is_(None)) | (Opinion.kind != "headnote"))
        .order_by(Paragraph.text_version_id, Paragraph.seq)
    ).all()
    return [(pid, body) for pid, body in rows if len(body) >= MIN_CHARS]


def build(
    session: Session,
    *,
    store: VectorStore | None = None,
    model_name: str = DEFAULT_MODEL,
    limit: int | None = None,
    on_progress=None,
) -> int:
    """Embed the corpus and write the store. Returns how many paragraphs were embedded."""
    store = store or default_store()
    rows = paragraphs_to_embed(session)
    if limit:
        rows = rows[:limit]
    if not rows:
        return 0

    ids = [pid for pid, _ in rows]
    texts = [body for _, body in rows]
    chunks: list[np.ndarray] = []
    for start in range(0, len(texts), BATCH):
        chunks.append(encode(texts[start : start + BATCH], model_name=model_name))
        if on_progress is not None:
            on_progress(min(start + BATCH, len(texts)), len(texts))
    store.write(np.vstack(chunks), ids, model_name)
    return len(ids)


def search(
    query: str, *, store: VectorStore | None = None, top: int = 120
) -> list[tuple[str, float]]:
    """The paragraphs nearest a query, best first, as (paragraph id, cosine similarity).

    Scored in blocks against the memory-mapped matrix rather than loading it whole: the ranking is
    identical and the peak memory is one block, which is what makes this safe to run beside a model.
    """
    store = store or default_store()
    if not store.exists:
        return []
    matrix, ids, index = store.open()
    vector = encode_for_index([query], index.get("model", DEFAULT_MODEL))[0]

    scores = np.empty(matrix.shape[0], dtype=np.float32)
    for start in range(0, matrix.shape[0], BLOCK):
        block = np.asarray(matrix[start : start + BLOCK], dtype=np.float32)
        scores[start : start + block.shape[0]] = block @ vector

    take = min(top, scores.shape[0])
    best = np.argpartition(-scores, take - 1)[:take]
    best = best[np.argsort(-scores[best])]
    return [(ids[i], float(scores[i])) for i in best]


# --- The hosted half: any OpenAI-compatible /v1/embeddings endpoint -------------------------------
# Bitdeer's BAAI/bge-m3 at $0.01/M tokens, a self-hosted Qwen3-Embedding, or the TEI box the
# production profile calls for all speak the same protocol, and the configuration is the same three
# settings whichever of them answers. The whole corpus measured 1.05 billion characters -- about
# 263-300M tokens, so $3 at bge-m3's price -- which is why the 8.3-hour CPU run this replaces was
# never worth starting.

API_BATCH = 64
# llama-server serves embeddings through n_slots (4 at ctx 8192); more concurrent POSTs than
# slots just queue at the server while holding their own buffers.
API_CONCURRENCY = 4
API_TIMEOUT = 120.0
# Batches are cut by character budget, not by count: 64 analysis paragraphs run ~45,000 tokens,
# and a request whose total exceeds what the slots can grind inside the client timeout dies
# exactly the way the first full run did. ~80,000 characters is ~20,000 tokens, which the four
# slots process in about ten seconds at the measured ~500 tokens/s/slot.
MAX_BATCH_CHARS = 80_000
# Above this many characters a paragraph cannot fit the endpoint's context anyway (100k chars ≈
# 25k tokens against a 32k server context), and asking for it hangs the server for minutes. The
# corpus's longest such block is 197,166 characters; there are ~37 over the line.
MAX_EMBED_CHARS = 100_000


def api_configured() -> bool:
    settings = get_settings()
    return bool(settings.embeddings_base_url and settings.embeddings_model)


class ContextOverflow(Exception):
    """The endpoint refused a batch because its tokens do not fit the context. Deterministic --
    retrying the same batch reproduces it, so the caller must split it or skip it."""

    def __init__(self, texts: list[str]):
        super().__init__(f"context overflow on a batch of {len(texts)} texts")
        self.texts = texts


class DailyCapReached(RuntimeError):
    """The endpoint says today's free quota is spent. Deterministic for the rest of the day --
    the build checkpoints its watermark and stops, and tomorrow's run resumes from there."""


def _api_encode_batch(
    client: httpx.Client, base_url: str, api_key: str, model: str, texts: list[str]
) -> np.ndarray:
    """One POST, one batch. Transient failures retry with backoff; a per-minute rate window is
    rode out with a full-window sleep, because a free endpoint's 20 requests/minute is not an
    error, it is the speed of that road. A 402/401 fails loudly, and a daily-cap refusal raises
    DailyCapReached -- deterministic until tomorrow, so the caller stops instead of hammering."""
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "input": texts},
            )
            if response.status_code in (401, 402):
                raise RuntimeError(
                    f"the embedding endpoint refused the request ({response.status_code}): "
                    f"{response.json().get('error', {}).get('message', 'unauthorized')}"
                )
            if response.status_code == 429:
                message = str(response.json())
                if "per-day" in message or "daily" in message.lower():
                    raise DailyCapReached(
                        "the endpoint's daily free quota is spent; the watermark is saved -- "
                        "resume tomorrow"
                    )
                last_error = httpx.HTTPStatusError(
                    message, request=response.request, response=response
                )
                time.sleep(65)
                continue
            if response.status_code == 500:
                message = str(response.json())
                if "context" in message.lower():
                    raise ContextOverflow(texts)
            response.raise_for_status()
            vectors = np.asarray(
                [item["embedding"] for item in response.json()["data"]], dtype=np.float32
            )
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            return vectors / np.where(norms == 0, 1.0, norms)
        except (RuntimeError, ContextOverflow, DailyCapReached):
            raise
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            last_error = error
            time.sleep(2**attempt)
    raise RuntimeError(f"the embedding endpoint stayed unreachable: {last_error}")


def encode_api(texts: list[str], *, model: str | None = None) -> np.ndarray:
    """Unit-length vectors for a small number of texts -- a query, a probe -- via the endpoint."""
    settings = get_settings()
    if not api_configured():
        raise RuntimeError(
            "no embedding endpoint configured: set EMBEDDINGS_BASE_URL, "
            "EMBEDDINGS_API_KEY and (to override BAAI/bge-m3) EMBEDDINGS_MODEL"
        )
    model = model or settings.embeddings_model
    parts: list[np.ndarray] = []
    with httpx.Client(timeout=API_TIMEOUT) as client:
        for start in range(0, len(texts), API_BATCH):
            parts.append(
                _api_encode_batch(
                    client,
                    settings.embeddings_base_url,
                    settings.embeddings_api_key,
                    model,
                    texts[start : start + API_BATCH],
                )
            )
    return np.vstack(parts) if len(parts) > 1 else parts[0]


def encode_for_index(texts: list[str], index_model: str) -> np.ndarray:
    """Encode by whatever encoded the index: the endpoint if it was the endpoint, else local.

    A corpus embedded through the API must not have its queries answered by a different encoder --
    the vectors would still be unit-length and the ranking silently wrong.
    """
    settings = get_settings()
    if api_configured() and index_model == settings.embeddings_model:
        return encode_api(texts, model=index_model)
    return encode(texts, model_name=index_model)


def build_api(
    session: Session,
    *,
    store: VectorStore | None = None,
    on_progress=None,
    resume: bool = True,
    limit: int | None = None,
    roles: list[str] | None = None,
) -> int:
    """Embed the corpus through the configured endpoint, writing into the store as it goes.

    Rows land in a preallocated float16 matrix one batch at a time -- the whole matrix is never
    resident, and a run that dies at 400,000 rows resumes from the watermark in the progress file
    instead of paying for those rows again. The model name is written into the index, so a query
    is encoded by whatever encoded the corpus, whichever endpoint that was. `limit` truncates the
    run to the first N paragraphs -- a trial, which belongs in its own store directory, not over
    the one a full run produced. `roles` embeds only paragraphs carrying one of the given
    rhetorical roles: the holding-bearing 11% of the corpus is what 'find the law' searches, and
    on a slow encoder it is the difference between a month and an evening.
    """
    store = store or default_store()
    settings = get_settings()
    if not api_configured():
        raise RuntimeError(
            "no embedding endpoint configured: set EMBEDDINGS_BASE_URL, "
            "EMBEDDINGS_API_KEY and (to override BAAI/bge-m3) EMBEDDINGS_MODEL"
        )
    model = settings.embeddings_model
    base_url = settings.embeddings_base_url
    api_key = settings.embeddings_api_key

    rows = paragraphs_to_embed(session)
    if roles:
        # Role-filtered rows must keep their paragraph ids aligned with the matrix, so the filter
        # happens here and not in SQL after the fact.
        from sqlalchemy import text as sql_text

        role_by_id = dict(
            session.execute(
                sql_text("SELECT id, role FROM paragraph"),
            ).all()
        )
        wanted = set(roles)
        rows = [(pid, body) for pid, body in rows if role_by_id.get(pid) in wanted]
    if limit:
        rows = rows[:limit]

    # A paragraph longer than the endpoint's context cannot ever be embedded -- asking for it does
    # not fail fast, it grinds the server for minutes and times the client out, and the retry sends
    # the same monster back. 100,000 characters is ~25k tokens, comfortably inside a 32k context;
    # the few longer ones (merged garbage blocks, the longest being 197k characters) are recorded
    # as skips and stay zero, exactly like the context-overflow refusals below.
    over_limit = [(pid, len(body)) for pid, body in rows if len(body) > MAX_EMBED_CHARS]
    if over_limit:
        over_ids = {pid for pid, _len in over_limit}
        rows = [(pid, body) for pid, body in rows if pid not in over_ids]
    ids = [pid for pid, _body in rows]
    progress_path = store.directory / "embed.progress.json"
    done_at = 0
    if resume and progress_path.exists() and store.vectors_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("model") == model and progress.get("count") == len(ids):
            done_at = int(progress.get("done", 0))
        else:
            progress_path.unlink()

    if done_at >= len(ids) and progress_path.exists():
        # Everything was fetched on an earlier run; only the index write is missing.
        store.finalize(ids, model)
        progress_path.unlink(missing_ok=True)
        return len(ids)

    store.directory.mkdir(parents=True, exist_ok=True)
    skipped: list[str] = [pid for pid, _len in over_limit]

    # The dimension is only knowable from the endpoint's first answer; probe with one text, then
    # preallocate. open_memmap zero-fills, which is exactly what a skipped row should be: a zero
    # vector ranks against nothing, and the id is recorded beside the store.
    probe = _api_encode_batch(
        httpx.Client(timeout=API_TIMEOUT), base_url, api_key, model, ["dimension probe"]
    )
    matrix = np.lib.format.open_memmap(
        store.vectors_path, mode="w+", dtype=np.float16, shape=(len(ids), probe.shape[1])
    )

    # Batches cut by character budget: a run of short paragraphs packs 64; a run of analysis
    # blocks packs three. Every request stays inside what the slots can finish well before the
    # client timeout, which is what the first full run learned the hard way.
    batches: list[tuple[int, int]] = []
    start = done_at
    while start < len(ids):
        chars = 0
        end = start
        while end < len(ids) and (end == start or chars < MAX_BATCH_CHARS):
            chars += len(rows[end][1])
            end += 1
        batches.append((start, end))
        start = end

    def embed_range(client: httpx.Client, start: int, n: int) -> int:
        """Embed rows [start, start+n) straight into the matrix; returns how many were skipped.

        On a context overflow the batch splits in half, recursively -- row order and row alignment
        survive, because every sub-range writes exactly the rows it owns. A single text that still
        overflows is junk by any reading (a 49k-token merged block), stays zero, and is recorded.
        """
        batch = rows[start : start + n]
        try:
            vectors = _api_encode_batch(
                client, base_url, api_key, model, [body for _pid, body in batch]
            )
        except ContextOverflow:
            if n == 1:
                skipped.append(batch[0][0])
                return 1
            half = n // 2
            skips = embed_range(client, start, half)
            skips += embed_range(client, start + half, n - half)
            return skips
        matrix[start : start + n] = vectors.astype(np.float16)
        return 0

    with httpx.Client(timeout=API_TIMEOUT) as client:
        todo = [(s0, s1) for s0, s1 in batches if s0 >= done_at]

        def worker(bounds: tuple[int, int]) -> int:
            # Absolute end row: the watermark must mean the same thing across resumes.
            start_row, end_row = bounds
            embed_range(client, start_row, end_row - start_row)
            return end_row

        # Checkpoint every 25 completed batches by COUNT, not by row arithmetic: batch sizes are
        # character-budgeted and uneven, and a modulo-on-rows condition can step over its own
        # window forever, which silently disables the watermark -- discovered the hard way.
        cap_error = None
        completed = 0
        with ThreadPoolExecutor(max_workers=API_CONCURRENCY) as pool:
            try:
                for position, end_row in enumerate(pool.map(worker, todo)):
                    written = end_row
                    completed += 1
                    if on_progress is not None:
                        on_progress(written, len(ids))
                    if completed % 25 == 0 or written == len(ids):
                        matrix.flush()
                        progress_path.write_text(
                            json.dumps({"model": model, "count": len(ids), "done": written}),
                            encoding="utf-8",
                        )
                        done_at = written
            except DailyCapReached as error:
                # The day's free quota is spent: save the watermark, stop cleanly. The in-order
                # iteration guarantees every range before the failure is already written.
                matrix.flush()
                progress_path.write_text(
                    json.dumps({"model": model, "count": len(ids), "done": written}),
                    encoding="utf-8",
                )
                cap_error = error
    if cap_error is not None:
        raise RuntimeError(f"paused at row {written:,}: {cap_error}")

    matrix.flush()
    store.finalize(ids, model)
    if skipped:
        (store.directory / "skipped.json").write_text(
            json.dumps({"model": model, "count": len(skipped), "paragraph_ids": skipped}),
            encoding="utf-8",
        )
    progress_path.unlink(missing_ok=True)
    return len(ids)
