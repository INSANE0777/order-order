"""Failure mode 9: the sentence cut before the words that matter.

Everything the brief quoted is the court's, word for word. What it did was stop. That makes this a
string operation, and the tests hold it to being one — it fires on a verbatim prefix and a dropped
qualifier, and stays silent on a paraphrase, on a whole sentence quoted whole, and on a brief that
kept the qualification and merely rearranged the sentence around it.
"""

from __future__ import annotations

from orderorder.engine.truncation import QUALIFIER, find_truncation
from orderorder.ingest.segment import segment

JUDGMENT = """1. Leave granted in the special leave petition filed by the appellant in this matter.

2. The stage to appreciate the evidence with a view to find fault or inconsistencies in the two
medical reports would arise only when the prosecution leads evidence by examining the doctors in
support of the medical reports.

3. A misrepresentation of a material fact vitiates the consent of the contracting party, and the
burden of proving that inducement lies upon the party who alleges it.

4. In view of the above, the appeals are dismissed with no order as to costs whatsoever.
"""

PARAGRAPHS = segment(JUDGMENT)


def test_a_quotation_stopped_before_its_qualification_is_caught() -> None:
    brief = (
        "The stage to appreciate the evidence with a view to find fault or inconsistencies in the "
        "two medical reports would arise: 2019 INSC 528, para 2."
    )
    found = find_truncation(brief, PARAGRAPHS)
    assert found is not None
    assert found.paragraph_label == "2"
    assert found.qualifier == "only when"
    assert "prosecution leads evidence" in found.dropped
    assert "would arise" in found.kept


def test_the_finding_names_the_words_that_were_cut() -> None:
    """Describing the omission is the model's answer. Quoting it is better and needs nobody."""
    brief = (
        "The stage to appreciate the evidence with a view to find fault or inconsistencies in the "
        "two medical reports would arise: 2019 INSC 528, para 2."
    )
    note = find_truncation(brief, PARAGRAPHS).note
    assert "the sentence continues" in note
    assert "only when the prosecution leads evidence" in note


def test_a_sentence_quoted_whole_is_not_a_truncation() -> None:
    brief = (
        "The stage to appreciate the evidence with a view to find fault or inconsistencies in the "
        "two medical reports would arise only when the prosecution leads evidence by examining the "
        "doctors in support of the medical reports: 2019 INSC 528, para 2."
    )
    assert find_truncation(brief, PARAGRAPHS) is None


def test_a_paraphrase_has_no_prefix_to_find() -> None:
    brief = "Evidence is appreciated only after the doctors are examined: 2019 INSC 528, para 2."
    assert find_truncation(brief, PARAGRAPHS) is None


def test_a_sentence_with_nothing_qualifying_after_the_cut_is_not_reported() -> None:
    """Stopping early is only a finding where what was dropped changes the proposition."""
    brief = (
        "A misrepresentation of a material fact vitiates the consent of the contracting party: "
        "2019 INSC 528, para 3."
    )
    assert find_truncation(brief, PARAGRAPHS) is None


def test_a_brief_that_kept_the_qualification_has_dropped_nothing() -> None:
    """Rearranging a sentence around its proviso is not cutting the proviso off."""
    brief = (
        "Only when the prosecution leads evidence does the stage to appreciate the evidence with a "
        "view to find fault or inconsistencies in the two medical reports arise: 2019 INSC 528."
    )
    assert find_truncation(brief, PARAGRAPHS) is None


def test_too_little_kept_is_not_a_quotation_at_all() -> None:
    brief = "The stage would arise: 2019 INSC 528, para 2."
    assert find_truncation(brief, PARAGRAPHS) is None


def test_no_paragraphs_is_no_finding() -> None:
    assert find_truncation("anything at all", []) is None


def test_the_qualifier_pattern_covers_how_courts_actually_qualify() -> None:
    for phrase in (
        "would arise only when the prosecution leads evidence",
        "is void unless the parties agree otherwise",
        "applies provided that notice has been given",
        "is subject to the conditions in Section 12",
        "in the facts and circumstances of this case",
        "so long as the tenant continues to pay",
        "having regard to the nature of the offence",
    ):
        assert QUALIFIER.search(phrase), phrase
    for phrase in (
        "the appeal is accordingly allowed with costs",
        "we are in complete agreement with the High Court",
    ):
        assert not QUALIFIER.search(phrase), phrase
