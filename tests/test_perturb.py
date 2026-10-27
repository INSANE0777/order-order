"""The perturbation study: real citations broken in one known way, and what the engine made of them.

Every test here runs against an in-memory database or a stub. Nothing reaches the network, and
nothing needs the 3 GB corpus.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, CitationEdge, Judgment
from orderorder.engine.search import build_index
from orderorder.evaluation.perturb import sample_base_items, sentence_around, shared_run
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

CITED = """1. A misrepresentation vitiates consent only where it induced the contract, and the
burden of proving inducement lies on the party alleging it. The rule is not absolute.

2. The appeal is dismissed with no order as to costs.
"""

CITING = """1. We have considered the record and the submissions of learned counsel.

2. As held in ALPHA versus BETA, a misrepresentation vitiates consent only where it induced the
contract, and the burden of proving inducement lies on the party alleging it, as the trial court
correctly found. Nothing in the later decisions disturbs that position.

3. The appeal fails and is dismissed.
"""


def _judgment(session, key: str, title: str, text: str, *, year: int = 2019, bench: int = 2):
    judgment = Judgment(
        canonical_key=key,
        court="Supreme Court of India",
        title=title,
        source="aws_open_data",
        source_id=key,
        bench_strength=bench,
        decided_on=dt.date(year, 6, 1),
    )
    session.add(judgment)
    session.flush()
    session.add(
        CitationAlias(
            judgment_id=judgment.id,
            reporter="INSC",
            citation_string=f"{year} INSC 1",
            normalized=f"INSC:{key}",
        )
    )
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path=key, page_count=2, headnote="", judgment=text),
    )
    return judgment


@pytest.fixture
def corpus(session):
    cited = _judgment(session, "INSC:2015:1", "ALPHA versus BETA", CITED, year=2015)
    citing = _judgment(session, "INSC:2019:1", "GAMMA versus DELTA", CITING, year=2019)
    session.add(
        CitationEdge(
            citing_id=citing.id,
            cited_id=cited.id,
            cited_alias="2015 INSC 1",
            source="test",
        )
    )
    session.commit()
    build_index(session)
    return session, citing, cited


# --- the shared run --------------------------------------------------------------------------


def test_a_shared_run_is_found_and_offset() -> None:
    cited = (
        "The court held that a misrepresentation vitiates consent only where it induced the "
        "contract, and nothing else follows."
    )
    citing = (
        "As held earlier, a misrepresentation vitiates consent only where it induced the "
        "contract, and so the plea fails."
    )
    run, offset, words = shared_run(citing, cited)
    assert cited[offset : offset + len(run)] == run
    assert words >= 8
    assert "misrepresentation" in run


def test_a_short_overlap_is_not_a_run() -> None:
    assert shared_run("the court held this", "the court held that", min_words=8) is None


def test_the_sentence_around_an_offset_is_the_sentence() -> None:
    text = "The appeal fails. As held earlier, a misrepresentation vitiates consent. Costs follow."
    start, end = sentence_around(text, text.index("misrepresentation"))
    assert text[start:end].startswith("As held")
    assert text[start:end].endswith("consent.")


# --- sampling ---------------------------------------------------------------------------------


def test_sampling_returns_an_item_with_the_run_in_its_claim(corpus) -> None:
    session, citing, cited = corpus
    items, manifest = sample_base_items(session)
    assert len(items) == 1
    item = items[0]
    assert "misrepresentation vitiates consent" in item.claim
    assert item.quote.lower() in item.claim.lower()
    assert item.citing_key == "INSC:2019:1"
    assert item.cited_key == "INSC:2015:1"
    assert item.decade == 2010
    assert item.quote_words >= 12
    assert manifest["counts"]["kept"] == 1


def test_the_same_seed_yields_the_same_hash(corpus) -> None:
    session, _, _ = corpus
    _, first = sample_base_items(session, seed=20261027)
    _, second = sample_base_items(session, seed=20261027)
    assert first["items_sha256"] == second["items_sha256"]
    assert first["counts"] == second["counts"]


def test_an_edge_without_a_shared_run_is_counted_and_dropped(session) -> None:
    cited = _judgment(session, "INSC:2015:2", "ONE versus TWO", "1. Costs and interim relief only.\n")
    citing = _judgment(session, "INSC:2019:2", "THREE versus FOUR", "1. A wholly different matter.\n")
    session.add(CitationEdge(citing_id=citing.id, cited_id=cited.id, cited_alias="2015 INSC 2", source="test"))
    session.commit()
    build_index(session)
    items, manifest = sample_base_items(session)
    assert items == []
    assert manifest["counts"]["edges_seen"] == 1
    assert manifest["counts"]["no_run"] == 1
