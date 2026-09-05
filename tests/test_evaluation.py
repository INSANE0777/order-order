"""The evaluation harness: the gold set, the generator, and the scoring.

These tests are about the measuring instrument rather than the thing measured, and the risk with a
measuring instrument is that it flatters. Two properties matter more than the rest:

  * a **clean item is genuinely clean** — the court's own words, correctly pinpointed — because a
    generator that quietly plants something in its clean items makes the false positive rate
    meaningless, and it is the false positive rate that decides whether the verdict board is worth
    reading;
  * a **planted item is genuinely planted** — the mode named in the label is the thing that was done
    to the item, not a description of what was hoped for.

The scoring is tested against hand-built verdicts rather than the engine, so that a change in the
engine moves the score and not the arithmetic.
"""

from __future__ import annotations

import datetime as dt
import random

import pytest

from orderorder.db.models import CitationAlias, Judgment
from orderorder.engine.verdict import CitationVerdict, Finding
from orderorder.evaluation.generate import (
    QUALIFIER,
    _party_name,
    _shifted,
    _usable,
    collect_seed,
    plant,
)
from orderorder.evaluation.gold import GoldItem, GoldLabels, read_gold, summarise, write_gold
from orderorder.evaluation.run import ItemResult, Report, format_report
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

JUDGMENT = """1. Leave granted.

2. It was strenuously contended on behalf of the appellant that any misrepresentation whatsoever
vitiates consent in a commercial contract, however immaterial the misstatement may have been.

3. A misrepresentation of a material fact vitiates the consent of the other party only where it
induced the contract, and the burden of proving inducement lies upon the party alleging it.

4. The principle stated above governs the present appeal and disposes of the only question that
was argued at the hearing before us over the course of two full days.

5. We express no opinion on whether the same principle would govern a contract of insurance, that
question not having been argued before us at any stage of these proceedings.

6. In view of the above, the appeals are dismissed with no order as to costs.
"""


def _add(session, key: str, title: str, text: str, *, bench: int = 2, year: int = 2019) -> Judgment:
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
            reporter="SCC",
            citation_string=f"({year}) 4 SCC 118",
            normalized=f"SCC:{year}:4:118",
        )
    )
    store_extracted(
        session,
        judgment,
        ExtractedJudgment(source_path=key, page_count=4, headnote="", judgment=text),
    )
    return judgment


@pytest.fixture
def seed(session):
    judgment = _add(session, "INSC:2019:1", "ALPHA versus BETA", JUDGMENT)
    session.commit()
    collected = collect_seed(session, judgment)
    assert collected is not None
    return collected


# --- the gold file ------------------------------------------------------------------------------


def test_a_gold_set_survives_a_round_trip(tmp_path) -> None:
    items = [
        GoldItem(id="a", claim_text="The burden lies on the party alleging it", citation_raw="(2019) 4 SCC 118"),
        GoldItem(
            id="b",
            claim_text="Something else entirely",
            citation_raw="(2019) 9 SCC 4001",
            planted_error=1,
            labels=GoldLabels(exists=False),
        ),
    ]
    path = tmp_path / "gold.jsonl"
    assert write_gold(items, path) == 2

    back = read_gold(path)
    assert [i.id for i in back] == ["a", "b"]
    assert back[0].is_clean
    assert back[1].planted_error == 1
    assert back[1].labels.exists is False


def test_a_hand_edited_file_still_loads(tmp_path) -> None:
    """Blank lines and unknown keys are what a hand-edited file looks like."""
    path = tmp_path / "gold.jsonl"
    path.write_text(
        '{"id": "a", "claim_text": "x", "citation_raw": "y", "reviewer_note": "looks wrong"}\n'
        "\n"
        '{"id": "b", "claim_text": "x", "citation_raw": "y"}\n',
        encoding="utf-8",
    )
    items = read_gold(path)
    assert [i.id for i in items] == ["a", "b"]


def test_a_missing_file_reads_as_empty(tmp_path) -> None:
    assert read_gold(tmp_path / "nothing.jsonl") == []


def test_the_brief_sentence_reads_as_a_brief_would_write_it() -> None:
    item = GoldItem(
        id="a",
        claim_text="The burden lies upon the party alleging it.",
        citation_raw="(2019) 4 SCC 118, para 3",
    )
    assert item.brief_sentence == "The burden lies upon the party alleging it: (2019) 4 SCC 118, para 3."


def test_the_summary_counts_clean_items_last() -> None:
    items = [
        GoldItem(id="a", claim_text="x", citation_raw="y"),
        GoldItem(id="b", claim_text="x", citation_raw="y", planted_error=1),
        GoldItem(id="c", claim_text="x", citation_raw="y", planted_error=1),
    ]
    counts = summarise(items)
    assert counts == {"phantom": 2, "clean": 1}
    assert list(counts)[-1] == "clean"


# --- the generator ------------------------------------------------------------------------------


def test_sentences_are_sorted_by_whose_words_they_are(seed) -> None:
    counsel = [s for _, s in seed.counsel_sentences]
    court = [s for _, s in seed.court_sentences]
    assert any("strenuously contended" in s for s in counsel)
    assert any("vitiates the consent of the other party only where" in s for s in court)
    # The submission must not also be offered as the court's own words.
    assert not any("strenuously contended" in s for s in court)


def test_a_paragraph_declining_to_decide_is_kept_apart(seed) -> None:
    obiter = [s for _, s in seed.obiter_sentences]
    assert any("express no opinion" in s for s in obiter)
    assert not any("express no opinion" in s for _, s in seed.court_sentences)


def test_page_furniture_is_not_a_proposition() -> None:
    assert _usable("A misrepresentation vitiates consent only where it induced the contract to be made.")
    assert not _usable("Leave granted.")  # too short to be a proposition
    assert not _usable("(2019) 4 SCC 118 (2018) 3 SCC 1 (2017) 2 SCC 9 (2016) 1 SCC 4 and others cited")
    assert not _usable("the sentence begins lower case and so is a fragment of the one above it here")
    # Column extraction produces half-sentences; an advocate asserts whole ones.
    assert not _usable("In case of the sample lifted from one of the five sticks the content was")


def test_a_sentence_announcing_a_quotation_is_not_the_proposition() -> None:
    """What follows is the proposition. This sentence describes another case, and says so.

    Offered as a claim it carries that other case's bench into an assertion about this one, and the
    engine is right to object; scoring the objection as a false positive would be scoring it for
    being right.
    """
    assert not _usable(
        "In paragraphs 365 and 366, the Constitution Bench of this Court has observed as under:-"
    )
    assert not _usable(
        "The relevant portion of the impugned judgment of the High Court reads as follows:"
    )
    assert not _usable(
        "In this regard we may usefully refer to a passage from the authority of the larger Bench."
    )


def test_a_sentence_naming_another_authority_is_not_used() -> None:
    """A gold item pairs one claim with one citation; a second citation inside it makes it ambiguous."""
    assert not _usable(
        "The same view was taken by this Court on the question in Kasturi v. Iyyamperumal and others."
    )
    assert not _usable(
        "This principle was settled in the decision reported at (1973) 4 SCC 225 many years ago."
    )


def test_the_party_name_reads_as_a_brief_would_write_it() -> None:
    assert _party_name("GURMIT SINGH BHATIA versus KIRAN KANT ROBINSON AND OTHERS") == "Gurmit Singh Bhatia"
    assert _party_name("STATE OF KERALA & ORS. versus SOMEONE ELSE") == "State Of Kerala"
    assert _party_name("PARMESHWAR NANDA ETC. v. THE STATE OF JHARKHAND") == "Parmeshwar Nanda"


def test_the_shifted_pinpoint_lands_away_from_the_paragraph() -> None:
    assert _shifted(["1", "2", "3"], "2") == "9"
    # A label that is not a plain number cannot be shifted arithmetically; go well past the end.
    assert _shifted(["1", "2"], "5.1") == "70"


def test_every_seed_yields_a_clean_item(seed, session) -> None:
    items = plant(seed, session, random.Random(1), [])
    clean = [i for i in items if i.is_clean]
    assert len(clean) == 1
    item = clean[0]
    # The clean item is the court's own words at the paragraph they are in.
    assert item.labels.voice == "court_majority"
    assert item.labels.paragraph_label in {p for p, _ in seed.court_sentences}
    assert item.claim_text in {s for _, s in seed.court_sentences}


def test_the_planted_modes_are_what_the_labels_say(seed, session) -> None:
    items = {
        i.id.rsplit("-", 1)[1]: i
        for i in plant(seed, session, random.Random(1), [], decoy="(2020) 4 SCC 118")
    }

    assert items["m1"].planted_error == 1
    assert items["m1"].labels.exists is False
    assert items["m1"].labels.judgment_key is None

    assert items["m2"].planted_error == 2
    # A mis-cite names the right case and points at a reference belonging to another. If the
    # reference resolved nowhere the item would be a phantom, and mode 1 is not mode 2.
    assert "Alpha" in items["m2"].citation_raw
    assert seed.citation not in items["m2"].citation_raw
    assert "(2020) 4 SCC 118" in items["m2"].citation_raw

    assert items["m3"].planted_error == 3
    assert "Constitution Bench" in items["m3"].claim_text

    assert items["m5"].planted_error == 5
    assert items["m5"].claim_text in {s for _, s in seed.counsel_sentences}

    assert items["m7"].planted_error == 7
    assert items["m7"].claim_text in {s for _, s in seed.obiter_sentences}

    assert items["m12"].planted_error == 12
    assert items["m12"].labels.paragraph_label not in items["m12"].citation_raw


def test_a_bench_is_only_overstated_where_the_record_is_smaller(session) -> None:
    """Claiming a Constitution Bench for a Constitution Bench plants nothing, so no item is made."""
    judgment = _add(session, "INSC:2019:5", "GAMMA versus DELTA", JUDGMENT, bench=5)
    session.commit()
    collected = collect_seed(session, judgment)
    assert collected is not None
    suffixes = {i.id.rsplit("-", 1)[1] for i in plant(collected, session, random.Random(1), [])}
    assert "m3" not in suffixes


def test_the_qualifier_pattern_finds_what_a_brief_drops() -> None:
    match = QUALIFIER.search("A misrepresentation vitiates consent only where it induced the contract")
    assert match and match.group(0) == "only where"
    assert QUALIFIER.search("The appeal is dismissed") is None


def test_a_truncated_item_stops_before_the_qualifier(seed, session) -> None:
    items = {i.id.rsplit("-", 1)[1]: i for i in plant(seed, session, random.Random(1), [])}
    if "m9" not in items:  # the seed carried no qualified sentence long enough to truncate
        pytest.skip("this seed has no truncatable sentence")
    truncated = items["m9"].claim_text
    assert QUALIFIER.search(truncated) is None
    assert any(s.startswith(truncated.rstrip(".")) for _, s in seed.court_sentences)


# --- the scoring --------------------------------------------------------------------------------


def _result(
    mode: int | None,
    found: list[int],
    *,
    support: str = "not_assessed",
    verified: bool = False,
) -> ItemResult:
    item = GoldItem(id=f"i{mode}", claim_text="x", citation_raw="(2019) 4 SCC 118", planted_error=mode)
    verdict = CitationVerdict(
        citation_raw=item.citation_raw,
        proposition="x",
        existence="found",
        support=support,
        quote_verified=verified,
        findings=[Finding(mode=m, label="l", detail="d") for m in found],
    )
    return ItemResult(item, verdict)


def test_a_planted_mode_counts_only_when_the_verdict_names_it() -> None:
    assert _result(5, [5]).caught
    # Finding something wrong is not the same as finding the right thing wrong.
    assert not _result(5, [12]).caught
    assert _result(5, [12, 5]).caught


def test_a_finding_on_a_clean_item_is_a_false_positive() -> None:
    assert _result(None, [12]).false_positive
    assert not _result(None, []).false_positive
    # A planted item that the engine flags is not a false positive, whatever it flagged.
    assert not _result(5, [12]).false_positive


def test_recall_is_reported_per_mode() -> None:
    report = Report(results=[_result(5, [5]), _result(5, []), _result(12, [12])])
    assert report.recall_by_mode() == {5: (1, 2), 12: (1, 1)}


def test_the_false_positive_rate_is_over_the_clean_items_alone() -> None:
    report = Report(results=[_result(None, []), _result(None, [12]), _result(5, [5])])
    assert report.false_positive_rate == 0.5


def test_the_false_positive_rate_is_none_without_clean_items() -> None:
    """A gold set of nothing but planted errors cannot answer the question, and must not pretend to."""
    assert Report(results=[_result(5, [5])]).false_positive_rate is None


def test_quote_grounding_counts_only_verdicts_claiming_support() -> None:
    report = Report(
        results=[
            _result(None, [], support="full", verified=True),
            _result(None, [], support="partial", verified=False),
            _result(None, [], support="not_assessed", verified=False),
        ]
    )
    assert report.quote_grounding_rate == 0.5


def test_a_mode_needing_a_model_is_unassessed_not_missed() -> None:
    report = Report(results=[_result(7, []), _result(5, [])], model_configured=False)
    assert report.unassessed_modes() == {7}

    with_model = Report(results=[_result(7, [])], model_configured=True)
    assert with_model.unassessed_modes() == set()


def test_the_report_says_which_modes_were_not_judged() -> None:
    report = Report(results=[_result(7, []), _result(5, [5]), _result(None, [])], model_configured=False)
    text = "\n".join(format_report(report))
    assert "needs a model; not counted" in text
    assert "obiter as ratio" in text
    assert "false positives on clean citations : 0/1" in text


def test_a_broken_invariant_is_named_in_the_report() -> None:
    report = Report(results=[_result(None, [], support="full", verified=False)])
    text = "\n".join(format_report(report))
    assert "INVARIANT BROKEN" in text
