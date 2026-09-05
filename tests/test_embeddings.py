"""Paragraph vectors, and the seam they fuse through.

The measured verdict on this is negative — over 391,356 paragraphs a CPU-feasible encoder makes
retrieval worse, and `engine.search` has the numbers and keeps it off. What is tested here is that the
machinery is correct, so that the experiment can be repeated the moment a stronger encoder is
available and the answer will be about the encoder rather than about a bug.

Nothing here downloads a model. A stub encoder stands in, because what these tests are about is the
store, the selection and the ranking, none of which depend on which model wrote the vectors.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from orderorder.db.models import Judgment
from orderorder.engine import embeddings
from orderorder.engine.embeddings import VectorStore, build, paragraphs_to_embed, search
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

JUDGMENT = """1. Leave granted.

2. A misrepresentation of a material fact vitiates the consent of the contracting party only where
it induced the contract, and the burden of proving that inducement lies upon the party alleging it.

3. The doctrine of frustration has no application where the parties have expressly allocated the
risk of the supervening event between themselves in the contract that they made.

4. A notice under Section 106 of the Transfer of Property Act is mandatory before a suit for
eviction is instituted, and its absence is fatal to the suit however strong the merits may be.

5. In view of the above the appeals are dismissed with no order as to costs whatsoever.
"""


class StubEncoder:
    """Vectors from a bag of words. Enough structure that similar text is nearer, and no download."""

    DIMENSION = 64

    def encode(self, texts):
        out = np.zeros((len(texts), self.DIMENSION), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in text.lower().split():
                out[row, hash(word) % self.DIMENSION] += 1.0
        return out


@pytest.fixture
def encoder(monkeypatch):
    monkeypatch.setattr(embeddings, "_model_cache", {"stub": StubEncoder()})
    monkeypatch.setattr(embeddings, "STATIC_PREFIX", "stub")
    return "stub"


@pytest.fixture
def corpus(session):
    judgment = Judgment(
        canonical_key="TEST:1",
        court="Supreme Court of India",
        title="ALPHA versus BETA",
        source="aws_open_data",
        source_id="TEST:1",
        bench_strength=2,
        decided_on=dt.date(2019, 6, 1),
    )
    session.add(judgment)
    session.flush()
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path="x", page_count=2, headnote="", judgment=JUDGMENT),
    )
    session.commit()
    return session


# --- what gets a vector -----------------------------------------------------------------------------


def test_a_paragraph_too_short_to_carry_a_proposition_is_skipped(corpus) -> None:
    """"Leave granted." has no meaning to match on, and a vector for it is noise in the ranking."""
    bodies = [body for _id, body in paragraphs_to_embed(corpus)]
    assert not any(body.startswith("Leave granted") for body in bodies)
    assert any("vitiates the consent" in body for body in bodies)


def test_vectors_come_back_unit_length(encoder) -> None:
    """The rest of the module treats a dot product as the cosine, which is only true of unit vectors."""
    vectors = embeddings.encode(["one text", "another text entirely"], model_name=encoder)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


# --- the store --------------------------------------------------------------------------------------


def test_the_store_records_which_model_wrote_it(corpus, encoder, tmp_path) -> None:
    """An upgrade is a rebuild, and a store that does not say what made it cannot be rebuilt safely."""
    store = VectorStore(tmp_path / "vectors")
    written = build(corpus, store=store, model_name=encoder)
    assert written > 0
    index = store.read_index()
    assert index["model"] == encoder
    assert index["dimension"] == StubEncoder.DIMENSION
    assert index["count"] == written
    assert len(index["paragraph_ids"]) == written


def test_a_store_that_was_never_built_finds_nothing_rather_than_failing(tmp_path) -> None:
    assert search("anything at all", store=VectorStore(tmp_path / "nothing")) == []


def test_vectors_are_kept_as_float16(corpus, encoder, tmp_path) -> None:
    """Half the file, and the ranking only cares about the order of the scores."""
    store = VectorStore(tmp_path / "vectors")
    build(corpus, store=store, model_name=encoder)
    matrix, _ids, _index = store.open()
    assert matrix.dtype == np.float16


# --- the ranking ------------------------------------------------------------------------------------


def test_the_nearest_paragraph_to_a_proposition_is_the_one_it_came_from(corpus, encoder, tmp_path) -> None:
    store = VectorStore(tmp_path / "vectors")
    build(corpus, store=store, model_name=encoder)
    nearest = search(
        "a notice under Section 106 of the Transfer of Property Act is mandatory before a suit",
        store=store,
        top=3,
    )
    assert nearest
    best_id = nearest[0][0]
    body = {pid: text for pid, text in paragraphs_to_embed(corpus)}[best_id]
    assert "Section 106" in body


def test_the_ranking_comes_back_best_first(corpus, encoder, tmp_path) -> None:
    store = VectorStore(tmp_path / "vectors")
    build(corpus, store=store, model_name=encoder)
    scores = [score for _id, score in search("frustration supervening event risk", store=store, top=4)]
    assert scores == sorted(scores, reverse=True)


def test_asking_for_more_than_the_store_holds_is_safe(corpus, encoder, tmp_path) -> None:
    store = VectorStore(tmp_path / "vectors")
    written = build(corpus, store=store, model_name=encoder)
    assert len(search("anything", store=store, top=1000)) == written
