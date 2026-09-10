"""Chroma as the alternative vector home: same vectors, same answers as the memmap store.

What these tests pin down is that the import is faithful and idempotent -- only missing rows are
added, a re-run changes nothing -- and that what Chroma returns as the nearest paragraph is what
brute-force cosine says it should be. The distances come back as cosine distance, converted to
similarity on the way out, matching the memmap path's convention.
"""

from __future__ import annotations

import numpy as np
import pytest

from orderorder.engine import chroma_store, embeddings


@pytest.fixture
def tiny_store(tmp_path):
    """Six unit vectors in four dimensions, and the store they belong to."""
    store = embeddings.VectorStore(directory=tmp_path / "vectors")
    vectors = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
            [-1.0, 0.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    ids = ["p1", "p2", "p3", "p4", "p5", "p6"]
    store.write(vectors, ids, "test-model")
    return store


@pytest.fixture
def chroma_home(tmp_path, monkeypatch, tiny_store):
    """Point the module's Chroma directory and encoder at the test's own paths."""
    monkeypatch.setattr(chroma_store, "chroma_dir", lambda: tmp_path / "chroma")
    monkeypatch.setattr(chroma_store, "default_store", lambda: tiny_store)
    return tmp_path / "chroma"


def test_the_import_copies_every_row_exactly_once(chroma_home, tiny_store) -> None:
    added = chroma_store.import_from_store(tiny_store)
    assert added == 6
    assert chroma_store.count() == 6
    # A second run adds nothing: the import is idempotent, like mark_roles.
    assert chroma_store.import_from_store(tiny_store) == 0
    assert chroma_store.count() == 6


def test_chroma_answers_what_brute_force_answers(chroma_home, monkeypatch, tiny_store) -> None:
    """Query [1, 0, 0, 0]: p1 is a perfect match, p6 is the opposite pole."""
    monkeypatch.setattr(
        chroma_store, "encode", lambda texts, model_name=None: np.array([[1.0, 0.0, 0.0, 0.0]])
    )
    chroma_store.import_from_store(tiny_store)

    results = chroma_store.search("anything", top=3)
    assert results[0][0] == "p1"
    assert results[0][1] == pytest.approx(1.0, abs=1e-5)
    assert results[1][0] == "p2"  # 0.9 along the same axis
    assert results[-1][1] < results[0][1]
    # Distances are similarities now, so the ranking is descending.
    similarities = [s for _pid, s in results]
    assert similarities == sorted(similarities, reverse=True)


def test_max_batch_respects_chromas_record_cap(chroma_home, tiny_store) -> None:
    """65000 / 4 dimensions = 16250; the cap scales with the vector size."""
    assert chroma_store.max_batch() == 16250
