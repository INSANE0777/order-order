"""The perturbation study: real citations broken in one known way, and what the engine made of them.

Every test here runs against an in-memory database or a stub. Nothing reaches the network, and
nothing needs the 3 GB corpus.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, CitationEdge, Judgment
from orderorder.engine.search import build_index
from orderorder.evaluation.perturb import (
    ArmItem,
    Paraphrase,
    ParaphraseOut,
    build_arms,
    classify,
    longest_shared_run,
    make_paraphrases,
    run_arms,
    sample_base_items,
    sentence_around,
    shared_run,
    summarise,
    wilson,
)
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

CITED = """1. A misrepresentation vitiates consent only where it induced the contract, and the
burden of proving inducement lies on the party alleging it. The rule is not absolute.

2. The appeal is dismissed with no order as to costs.

3. The parties bear their own costs in both courts.
"""

OTHER = """1. Interim custody is decided on the welfare of the child, not on the wealth of the parents.

2. The transfer petition is allowed.
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

# --- the paraphrase family --------------------------------------------------------------------


class _Stub:
    """Returns prepared answers and records the prompts it was given."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ParaphraseOut(text=answer)


def _items(session):
    return sample_base_items(session)[0]


def test_a_paraphrase_without_the_run_is_accepted(corpus) -> None:
    session, _, _ = corpus
    items = _items(session)
    text = "A consent obtained by deceit is voidable only when the deceit caused the agreement."
    paraphrases = make_paraphrases(items, _Stub(text))
    assert len(paraphrases) == 1
    assert paraphrases[0].text == text
    assert paraphrases[0].longest_shared_run < 8


def test_a_paraphrase_that_copies_the_run_is_rejected(corpus) -> None:
    session, _, _ = corpus
    items = _items(session)
    copied = "A misrepresentation vitiates consent only where it induced the contract."
    copied = copied + " Nothing else."
    reject: list[dict] = []
    paraphrases = make_paraphrases(items, _Stub(copied, copied), reject_log=reject)
    assert paraphrases == []
    assert reject and reject[0]["reason"] == "overlap"


def test_a_model_that_raises_is_retried_then_rejected(corpus) -> None:
    session, _, _ = corpus
    items = _items(session)
    reject: list[dict] = []
    paraphrases = make_paraphrases(items, _Stub(RuntimeError("boom"), RuntimeError("boom")), reject_log=reject)
    assert paraphrases == []
    assert reject and reject[0]["reason"] == "error"


def test_the_longest_shared_run_counts_words() -> None:
    source = "a misrepresentation vitiates consent only where it induced the contract"
    assert longest_shared_run("consent only where it induced the contract", source) == 7
    assert longest_shared_run("nothing in common here at all", source) == 0


# --- arms -------------------------------------------------------------------------------------


@pytest.fixture
def sibling_corpus(corpus, session):
    session, citing, cited = corpus
    other = _judgment(session, "INSC:2016:9", "EPSILON versus ZETA", OTHER, year=2016)
    session.add(CitationEdge(citing_id=citing.id, cited_id=other.id, cited_alias="2016 INSC 9", source="test"))
    session.commit()
    return session, citing, cited, other


def test_four_arms_without_a_paraphrase(sibling_corpus) -> None:
    session, *_ = sibling_corpus
    items = _items(session)[:1]
    arms = build_arms(session, items, [])
    assert {a.arm for a in arms} == {
        "verbatim_clean",
        "verbatim_wrong_paragraph",
        "verbatim_wrong_judgment",
    }


def test_six_arms_with_a_paraphrase(sibling_corpus) -> None:
    session, *_ = sibling_corpus
    items = _items(session)[:1]
    paraphrase = Paraphrase(item_id=items[0].item_id, text="Consent is voidable when deceit caused it.", longest_shared_run=2)
    arms = build_arms(session, items, [paraphrase])
    assert len(arms) == 6
    para = next(a for a in arms if a.arm == "verbatim_wrong_paragraph")
    clean = next(a for a in arms if a.arm == "verbatim_clean")
    assert "para" in clean.citation
    assert para.citation != clean.citation
    assert para.expected_modes == (12, 4)


def test_the_wrong_judgment_is_not_the_cited_one(sibling_corpus) -> None:
    session, _, cited, other = sibling_corpus
    items = _items(session)[:1]
    arms = build_arms(session, items, [])
    wrong = next(a for a in arms if a.arm == "verbatim_wrong_judgment")
    assert wrong.distractor_key != cited.canonical_key
    assert wrong.distractor_key is not None


# --- scoring ----------------------------------------------------------------------------------


def _row(**kwargs):
    base = {
        "existence": "found",
        "support": "partial",
        "quote_verified": True,
        "quote_match_type": "exact",
        "needs_review": False,
        "confidence": 0.9,
        "findings": [],
        "error": None,
    }
    base.update(kwargs)
    return base


def _arm(arm: str, item_id: str = "x") -> ArmItem:
    return ArmItem(arm=arm, item_id=item_id, claim="c", citation="2015 INSC 1, para 3", expected_modes=(12, 4))


def test_a_clean_item_passes_with_no_pointer_finding() -> None:
    assert classify(_arm("verbatim_clean"), _row()) == "pass"


def test_a_phantom_is_a_wrong_flag_even_on_the_clean_arm() -> None:
    row = _row(existence="not_found", support="not_assessed", findings=[{"mode": 1, "label": "phantom"}])
    assert classify(_arm("verbatim_clean"), row) == "wrong_flag"


def test_a_neighbouring_paragraph_counts_as_caught() -> None:
    row = _row(findings=[{"mode": 12, "label": "wrong pinpoint"}])
    assert classify(_arm("verbatim_wrong_paragraph"), row) == "caught"


def test_a_non_pointer_finding_is_not_a_catch() -> None:
    row = _row(findings=[{"mode": 8, "label": "overstated"}])
    assert classify(_arm("verbatim_wrong_paragraph"), row) == "not_caught"


def test_an_error_outranks_a_catch() -> None:
    row = _row(findings=[{"mode": 12, "label": "wrong pinpoint"}], error="provider")
    assert classify(_arm("verbatim_wrong_paragraph"), row) == "error"


def test_a_swallowed_provider_error_is_an_abstention() -> None:
    row = _row(node_error=True, findings=[], needs_review=True)
    assert classify(_arm("verbatim_wrong_paragraph"), row) == "abstain"


def test_abstention_leaves_the_decided_denominator() -> None:
    arms = [_arm("verbatim_wrong_paragraph", "a"), _arm("verbatim_wrong_paragraph", "b")]
    rows = [
        _row(item_id="a", arm="verbatim_wrong_paragraph", findings=[{"mode": 12, "label": "p"}]),
        _row(item_id="b", arm="verbatim_wrong_paragraph", needs_review=True, support="not_assessed"),
    ]
    summary = summarise(arms, rows)
    cell = summary["arms"]["verbatim_wrong_paragraph"]
    assert cell["decided_catch"]["n"] == 1
    assert cell["all_in_catch"]["n"] == 2


def test_wilson_never_reports_certainty_from_a_small_sample() -> None:
    point, low, high = wilson(0, 200)
    assert point == 0.0
    assert 0.0 < high < 0.03
    point, low, high = wilson(10, 10)
    assert point == 1.0
    assert low < 1.0


def test_a_cell_below_ten_is_suppressed() -> None:
    arms = [_arm("verbatim_wrong_paragraph")]
    rows = [_row(item_id="x", arm="verbatim_wrong_paragraph") for _ in range(9)]
    summary = summarise(arms, rows)
    assert summary["arms"]["verbatim_wrong_paragraph"].get("suppressed") is True


# --- runner -----------------------------------------------------------------------------------


def test_the_runner_writes_one_row_per_arm_and_resumes(tmp_path) -> None:
    arms = [_arm("verbatim_clean"), _arm("verbatim_wrong_paragraph")]
    calls: list[str] = []

    def verify(arm):
        calls.append(arm.arm)
        return _row()

    cache = tmp_path / "responses.jsonl"
    run_arms(arms, verify_fn=verify, cache_path=cache)
    assert len(calls) == 2
    assert len(cache.read_text(encoding="utf-8").splitlines()) == 2

    run_arms(arms, verify_fn=verify, cache_path=cache)
    assert len(calls) == 2, "completed rows must not be re-run"


def test_an_errored_row_is_retried_and_a_failure_does_not_abort(tmp_path) -> None:
    arms = [_arm("verbatim_clean"), _arm("verbatim_wrong_paragraph")]
    cache = tmp_path / "responses.jsonl"
    cache.write_text(
        '{"arm": "verbatim_clean", "item_id": "x", "error": "provider"}\n', encoding="utf-8"
    )
    seen: list[str] = []

    def verify(arm):
        seen.append(arm.arm)
        if arm.arm == "verbatim_wrong_paragraph":
            raise RuntimeError("boom")
        return _row()

    rows = run_arms(arms, verify_fn=verify, cache_path=cache)
    assert "verbatim_clean" in seen
    assert len(rows) == 2
    assert any(row.get("error") for row in rows)


def test_four_workers_produce_the_same_rows_as_one(tmp_path) -> None:
    arms = [_arm("verbatim_clean", f"x{i}") for i in range(6)]

    def verify(arm):
        return _row()

    one = run_arms(arms, verify_fn=verify, cache_path=tmp_path / "one.jsonl", workers=1)
    four = run_arms(arms, verify_fn=verify, cache_path=tmp_path / "four.jsonl", workers=4)
    assert one == four
