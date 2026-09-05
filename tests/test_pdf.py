"""Cleaning Supreme Court Reports PDFs.

These tests use synthetic page text shaped like the real extraction, so they run without network access
or a PDF file. The shapes come from a real judgment: [2019] 9 S.C.R. 593.
"""

from __future__ import annotations

from orderorder.ingest.pdf import (
    clean_pages,
    find_separate_opinions,
    pdf_key,
    pdf_url,
    split_headnote,
)

PAGE_ONE = """A
B
C
D
E
F
G
H
593
GURMIT SINGH BHATIA
v.
KIRAN KANT ROBINSON AND OTHERS
(Civil Appeal Nos. 5522-5523 of 2019)
JULY 17, 2019
Code of Civil Procedure, 1908 � Or.1, r.10 � Impleadment of party.
HELD: The plaintiff is the dominus litis.
 [2019] 9 S.C.R. 593"""

PAGE_TWO = """A
B
C
594 SUPREME COURT REPORTS [2019] 9 S.C.R.
GURMIT SINGH BHATIA v. KIRAN KANT ROBINSON
CIVIL APPELLATE JURISDICTION : Civil Appeal Nos. 5522-5523 of 2019.
The Judgment of the Court was delivered by
M. R. SHAH , J.
1. Feeling aggrieved and dissatisfied with the impugned judgment dated
3.7.2013, the appellant preferred these appeals before this Court seeking
relief against the order of the High Court of Chhattisgarh at Bilaspur."""

PAGE_THREE = """A
B
594
GURMIT SINGH BHATIA v. KIRAN KANT ROBINSON
2. The facts of the case leading to these appeals in nutshell are as under
and they require a careful statement before the questions of law are taken up."""


def test_margin_letters_are_removed() -> None:
    text, _ = clean_pages([PAGE_ONE, PAGE_TWO, PAGE_THREE])
    for line in text.splitlines():
        assert line.strip() not in set("ABCDEFGH")


def test_running_headers_are_removed() -> None:
    text, _ = clean_pages([PAGE_ONE, PAGE_TWO, PAGE_THREE])
    assert "SUPREME COURT REPORTS" not in text
    # The party-name header repeats across pages and must go, without being hard-coded.
    assert "GURMIT SINGH BHATIA v. KIRAN KANT ROBINSON" not in text


def test_page_numbers_and_citation_lines_are_removed() -> None:
    text, _ = clean_pages([PAGE_ONE, PAGE_TWO, PAGE_THREE])
    assert "[2019] 9 S.C.R. 593" not in text
    assert not any(line.strip() == "593" for line in text.splitlines())


def test_replacement_character_becomes_an_en_dash() -> None:
    text, _ = clean_pages([PAGE_ONE, PAGE_TWO, PAGE_THREE])
    assert "�" not in text
    assert "–" in text


def test_removed_count_is_reported() -> None:
    _, removed = clean_pages([PAGE_ONE, PAGE_TWO, PAGE_THREE])
    assert removed > 10


def test_content_survives_cleaning() -> None:
    text, _ = clean_pages([PAGE_ONE, PAGE_TWO, PAGE_THREE])
    assert "Feeling aggrieved" in text
    assert "dominus litis" in text


def test_headnote_is_split_from_the_judgment() -> None:
    text, _ = clean_pages([PAGE_ONE, PAGE_TWO, PAGE_THREE])
    headnote, judgment, author, notes = split_headnote(text)
    assert "HELD: The plaintiff is the dominus litis." in headnote
    assert "Feeling aggrieved" in judgment
    # The editorial summary must not leak into the text that pinpoints resolve against.
    assert "HELD:" not in judgment
    assert notes


def test_author_is_extracted() -> None:
    text, _ = clean_pages([PAGE_ONE, PAGE_TWO, PAGE_THREE])
    _, _, author, _ = split_headnote(text)
    assert author == "M. R. SHAH"


def test_document_without_a_boundary_is_kept_whole() -> None:
    body = "1. This is a judgment with no recognisable opening marker. " * 20
    headnote, judgment, _, notes = split_headnote(body)
    assert headnote == ""
    assert judgment.startswith("1. This is a judgment")
    assert "no headnote boundary found" in notes[0]


def test_separate_opinions_are_detected() -> None:
    text = "1. The majority view.\n\nR. F. NARIMAN, J. (dissenting)\n\n2. I respectfully disagree."
    found = find_separate_opinions(text)
    assert len(found) == 1
    offset, kind, judge = found[0]
    assert kind == "dissenting"
    assert "NARIMAN" in judge
    assert offset > 0


def test_no_separate_opinion_in_a_unanimous_judgment() -> None:
    assert find_separate_opinions("1. We are in complete agreement with the High Court.") == []


def test_pdf_key_and_url_follow_the_bucket_layout() -> None:
    assert pdf_key("2019_9_593_605", 2019) == "data/pdf/year=2019/english/2019_9_593_605_EN.pdf"
    assert pdf_url("2019_9_593_605", 2019).endswith("2019_9_593_605_EN.pdf")


# --- the modern Reports format and the coram ----------------------------------
#
# The Reports changed format around 2020. Judgments now print counsel appearances, then an explicit
# "Judgment / Order of the Supreme Court" line, then the author. The coram above the headnote is the
# authority on bench strength: the open-data metadata names only the presiding judge, so a two-judge
# bench arrives recorded as one, and bench strength decides which precedents bind which.

from orderorder.ingest.pdf import find_author, find_coram, split_trailer  # noqa: E402

MODERN_PAGE = """CIVIL APPELLATE JURISDICTION: Civil Appeal No. 14830 of 2024
From the Judgment and Order dated 24.05.2022 of the High Court
Appearances for Parties
Nikhil Jain, Ms. Divya Jain, Advs. for the Appellant.
Krishna Ballabh Thakur, Adv. for the Respondents.
Judgment / Order of the Supreme Court
Judgment
Vikram Nath, J.
1. Leave granted, and the appeal is taken up for final disposal today.
2. This appeal assails the final judgment and order passed by the High Court
in a writ petition, which dismissed the petition and upheld the order below.
3. The facts giving rise to the present appeal lie in a narrow compass and may
be stated briefly. The appellant instituted proceedings before the trial court
seeking a declaration of title, which came to be decided against him.
4. We have heard learned counsel for the parties and perused the record with
their assistance. The question that falls for our consideration is whether the
High Court was justified in interfering with the concurrent findings of fact."""


def test_modern_format_starts_at_the_judgment_marker() -> None:
    headnote, judgment, _, _ = split_headnote(MODERN_PAGE)
    assert judgment.startswith("Judgment / Order of the Supreme Court")
    # Counsel names are not the court's words and must stay out of the judgment text.
    assert "Advs. for the Appellant" not in judgment
    assert "Advs. for the Appellant" in headnote


def test_modern_format_author_is_extracted() -> None:
    _, judgment, author, _ = split_headnote(MODERN_PAGE)
    assert author == "Vikram Nath"


def test_author_regex_does_not_swallow_the_preceding_heading() -> None:
    """With re.MULTILINE a whitespace class would run past the line start and capture 'Judgment'."""
    assert find_author("Judgment\nBela M. Trivedi, J.\n1. Leave granted.") == "Bela M. Trivedi"


def test_old_format_author_still_works() -> None:
    text = "The Judgment of the Court was delivered by\nM. R. SHAH , J.\n1. Feeling aggrieved."
    assert find_author(text) == "M. R. SHAH"


def test_author_absent() -> None:
    assert find_author("1. There is no author line in this text at all.") is None


def test_coram_gives_the_full_bench() -> None:
    judges = find_coram("[DR. DHANANJAYA Y. CHANDRACHUD AND M. R. SHAH, JJ.]")
    assert judges == ["DHANANJAYA Y. CHANDRACHUD", "M. R. SHAH"]


def test_coram_strips_the_authoring_asterisk() -> None:
    """The Reports mark the authoring judge with an asterisk; the name must not keep it."""
    assert find_coram("[Surya Kant* and Ujjal Bhuyan, JJ.]") == ["Surya Kant", "Ujjal Bhuyan"]


def test_coram_of_a_single_judge() -> None:
    assert find_coram("[VIKRAM NATH, J.]") == ["VIKRAM NATH"]


def test_coram_of_a_constitution_bench() -> None:
    line = "[A. B. One, C. D. Two, E. F. Three, G. H. Four AND I. J. Five, JJ.]"
    assert len(find_coram(line)) == 5


def test_no_coram_line() -> None:
    assert find_coram("There is no coram printed in this text.") == []


def test_bench_strength_comes_from_the_coram() -> None:
    from orderorder.ingest.pdf import ExtractedJudgment

    extracted = ExtractedJudgment(
        source_path="x",
        page_count=1,
        headnote="",
        judgment="1. Text.",
        coram=["Bela M. Trivedi", "Satish Chandra Sharma"],
    )
    assert extracted.bench_strength == 2
    assert ExtractedJudgment(source_path="x", page_count=1, headnote="", judgment="").bench_strength is None


# --- where the court stops ------------------------------------------------------------------------

TRAILER_JUDGMENT = (
    "The Judgment of the Court was delivered by\nDIPAK MISRA, J.\n\n"
    "1. Leave granted in both the special leave petitions filed by the appellant herein.\n\n"
    "2. A misrepresentation vitiates consent only where it induced the contract, and the burden of "
    "proving inducement lies upon the party alleging it before the trial court.\n\n"
    "3. In view of the above the appeals are allowed. No order as to costs.\n"
    "Result of the case: Appeals allowed.\n"
    "-\n"
    "Headnotes prepared by: Divya Pandey, Hony. Associate Editor\n"
)


def test_the_reporters_closing_matter_is_not_the_judgment() -> None:
    judgment, trailer = split_trailer(TRAILER_JUDGMENT)
    assert judgment.endswith("No order as to costs.")
    assert trailer.startswith("Result of the case:")
    assert "Headnotes prepared by" in trailer
    # A quote taken from the trailer must not be findable in the judgment text.
    assert "Divya Pandey" not in judgment


def test_a_judgment_the_reporter_did_not_sign_off_is_kept_whole() -> None:
    text = "1. Leave granted.\n\n2. The appeal is dismissed with no order as to costs.\n"
    judgment, trailer = split_trailer(text)
    assert judgment == text  # returned untouched, not merely unflagged
    assert trailer == ""


def test_the_headnotes_line_alone_ends_the_judgment() -> None:
    """Most judgments carry both markers; some carry only this one."""
    text = (
        "1. Leave granted in this matter which arises out of a decree for specific performance.\n\n"
        "2. In that view of the matter, the appeal being devoid of merits is dismissed.\n"
        "Headnotes prepared by: Appeal dismissed.\nAnkit Gyan\n"
    )
    judgment, trailer = split_trailer(text)
    assert judgment.endswith("is dismissed.")
    assert trailer.startswith("Headnotes prepared by:")


def test_a_marker_in_the_opening_third_is_not_the_end_of_the_judgment() -> None:
    """The headnote summarises the disposition too. Cutting there would throw the judgment away."""
    text = (
        "Result of the case: Appeal allowed.\n\n"
        + "\n\n".join(
            f"{n}. Paragraph {n} of the court's reasoning, at some length so the document is long."
            for n in range(1, 20)
        )
        + "\n"
    )
    judgment, trailer = split_trailer(text)
    assert trailer == ""
    assert judgment.startswith("Result of the case")


def test_extraction_reports_that_the_trailer_was_removed() -> None:
    _headnote, judgment, _author, _notes = split_headnote(TRAILER_JUDGMENT)
    kept, trailer = split_trailer(judgment)
    assert trailer
    assert "Headnotes prepared by" not in kept


# --- the volume's sign-off ------------------------------------------------------------------------


def test_the_volumes_signoff_is_not_the_judgment() -> None:
    """Printed across the foot of the last page, and run together into one line by extraction."""
    text = (
        "1. Leave granted in this matter.\n\n"
        "2. The appeal is allowed. No order as to costs.\n"
        "Divya Pandey Appeal allowed.\n"
        "(Assisted by : Deepak Panwar, LCRA)"
    )
    judgment, trailer = split_trailer(text)
    assert judgment.endswith("No order as to costs.")
    assert "Divya Pandey" in trailer
    assert "Assisted by" in trailer


def test_the_courts_own_disposition_is_left_alone() -> None:
    """The court writes a sentence; the footer writes a noun phrase after somebody's name."""
    for ending in (
        "The appeal is allowed and the matter is remitted to the High Court for fresh consideration.",
        "Accordingly, the appeals are dismissed with no order as to costs.",
        "In the result, the writ petition is disposed of in the above terms.",
    ):
        text = f"1. Leave granted.\n\n2. {ending}"
        judgment, trailer = split_trailer(text)
        assert trailer == "", ending
        assert judgment == text


def test_a_footnote_printed_below_the_signoff_survives() -> None:
    """Those are the court's, and they sit under the footer on the page."""
    text = (
        "1. Leave granted.\n\n"
        "2. The appeals are dismissed.\n"
        "Kalpana K. Tripathy Appeals allowed.\n"
        "1 Criminal Appeal No. 2178 of 2017."
    )
    judgment, trailer = split_trailer(text)
    assert judgment.endswith("1 Criminal Appeal No. 2178 of 2017.")
    assert trailer == "Kalpana K. Tripathy Appeals allowed."


def test_the_signoff_is_recognised_however_the_editor_is_spelled() -> None:
    """Six editors sign the corpus and OCR mangles all six names; the shape is what is matched."""
    for line in (
        "Devika Gujral Contempt Petitions disposed of.",
        "Kalpana K. Tripatby Appeals allowed.",
        "NidhiJain Review Petition disposed of.",
        "Nidhi Jain and Anurag Bhaskar Appeal allowed.",
        "Bibhuti Bhushan Bose Special Leave Petition dismissed.",
        "D.G. Suo Motu Petition disposed of.",
    ):
        text = f"1. Leave granted.\n\n2. The appeal is disposed of.\n{line}"
        judgment, trailer = split_trailer(text)
        assert trailer == line, line
        assert judgment.endswith("The appeal is disposed of.")


def test_a_signoff_shaped_line_in_the_body_is_not_cut() -> None:
    """Only the closing lines are considered; the same words in the middle are the court's."""
    text = (
        "1. Leave granted.\n\n"
        "2. Rajendra Prasad Appeals allowed.\n\n"
        + "\n\n".join(f"{n}. Paragraph {n} of the court's reasoning at some length." for n in range(3, 9))
    )
    judgment, trailer = split_trailer(text)
    assert trailer == ""
    assert "Rajendra Prasad Appeals allowed." in judgment
