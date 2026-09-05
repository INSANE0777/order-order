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
matrix resident, because holding all of it at once is enough to get the process killed on a machine with no memory to spare.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

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
        self.index_path.write_text(
            json.dumps(
                {
                    "model": model,
                    "dimension": int(vectors.shape[1]),
                    "count": int(vectors.shape[0]),
                    "paragraph_ids": paragraph_ids,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


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
    vector = encode([query], model_name=index.get("model", DEFAULT_MODEL))[0]

    scores = np.empty(matrix.shape[0], dtype=np.float32)
    for start in range(0, matrix.shape[0], BLOCK):
        block = np.asarray(matrix[start : start + BLOCK], dtype=np.float32)
        scores[start : start + block.shape[0]] = block @ vector

    take = min(top, scores.shape[0])
    best = np.argpartition(-scores, take - 1)[:take]
    best = best[np.argsort(-scores[best])]
    return [(ids[i], float(scores[i])) for i in best]
