"""Chroma as an alternative home for the paragraph vectors.

The memmap store in embeddings.py is the measured answer for ranking -- 668k float16 rows are a
matrix multiply, not a query engine -- but a vector database earns its keep when something outside
this process wants to query the corpus: a dashboard, another service, an export. Chroma embeds in
this process (no server), persists to its own directory, and answers metadata-filtered queries the
memmap cannot.

The vectors are the same ones the memmap store holds -- this is an import, not a re-embedding, so
the two backends always agree with each other and with the paragraph table. Queries return the same
(paragraph id, cosine similarity) pairs; only the engine between them differs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from orderorder.config import get_settings
from orderorder.engine.embeddings import VectorStore, default_store, encode

COLLECTION = "paragraphs"


def max_batch(store: VectorStore | None = None) -> int:
    """Chroma caps each add by (max_batch_size = max(1, 65000 / record dim)); stay under it.

    Takes the store whose vectors are about to be added, because the cap is a function of *their*
    dimension. Reading it off the default store while importing another one would compute a cap for
    the wrong matrix.
    """
    return max(1, 65000 // _dimension(store))


def _dimension(store: VectorStore | None = None) -> int:
    store = store or default_store()
    index = store.read_index()
    return int(index["dimension"])


def chroma_dir() -> Path:
    return get_settings().data_dir / "chroma"


def client():
    """A Chroma client with telemetry off; the corpus stays on this machine and says so."""
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    return chromadb.PersistentClient(
        path=str(chroma_dir()), settings=ChromaSettings(anonymized_telemetry=False)
    )


def collection(client_=None):
    client_ = client_ or client()
    return client_.get_or_create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine"}
    )


def count() -> int:
    return collection().count()


def import_from_store(
    store: VectorStore | None = None,
    batch: int | None = None,
    *,
    progress: Callable[[int], None] | None = None,
) -> int:
    """Copy the built vector matrix into Chroma. Re-runnable; only missing rows are added.

    `batch` defaults to `max_batch()` rather than to a constant. A fixed default is the wrong shape
    here: the cap is `65000 // dimension`, which is 253 at the 256-dimension encoder this corpus
    uses, so any constant large enough to look efficient is refused by Chroma on every real import
    while passing against a small fixture. `progress` is called with the running total after each
    batch, so a caller that wants to print does not have to reimplement the loop to do it.
    """
    store = store or default_store()
    if not store.exists:
        raise RuntimeError("no vector store to import; run `orderorder embed` first")
    matrix, paragraph_ids, _index = store.open()
    batch = batch or max_batch(store)
    # One client, not one per call: `collection()` builds a PersistentClient each time, and opening
    # two against the same directory to read the ids and then write them is asking the embedded
    # database to arbitrate between two handles for no reason.
    coll = collection()
    existing = set(coll.get(include=[])["ids"])
    added = 0
    for start in range(0, len(paragraph_ids), batch):
        ids = paragraph_ids[start : start + batch]
        todo = [(i, pid) for i, pid in enumerate(ids, start=start) if pid not in existing]
        if not todo:
            continue
        # Chroma stores float32; the memmap holds float16. Cast in slices so only one batch is
        # resident at a time.
        vectors = np.asarray(matrix[[i for i, _ in todo]], dtype=np.float32)
        coll.add(
            ids=[pid for _, pid in todo],
            embeddings=vectors,
        )
        added += len(todo)
        if progress is not None:
            progress(added)
    return added


def search(
    query: str, *, top: int = 120, model_name: str | None = None
) -> list[tuple[str, float]]:
    """The paragraphs nearest a query, best first, as (paragraph id, cosine similarity).

    The model name comes from the store's index so the query is always encoded by whatever encoded
    the corpus -- a mismatch would rank silently wrong and never announce itself.
    """
    store = default_store()
    model = model_name or (store.read_index()["model"] if store.exists else None)
    if model is None:
        raise RuntimeError("no vector store; cannot pick an encoder")
    vector = encode([query], model_name=model)[0]
    result = collection().query(
        query_embeddings=[vector.tolist()], n_results=top, include=["distances"]
    )
    # Chroma returns cosine *distance* (1 - similarity); the memmap path reports similarity.
    return [
        (pid, 1.0 - distance)
        for pid, distance in zip(result["ids"][0], result["distances"][0], strict=True)
    ]
