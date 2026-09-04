"""The citator: is this authority still good law?

Failure mode 10. Two rules carry the weight here and both are pinned below. Treatment is read from
the sentence carrying the citation, because a paragraph cites four cases and treats them differently.
And a bench cannot overrule one at least as large as itself — a rule of arithmetic, not language,
which no cue phrase may override.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.citations.grammar import normalize_citation_string
from orderorder.db.models import CitationAlias, Judgment, Paragraph
from orderorder.engine.citator import (
    apply_bench_rule,
    build_citator,
    classify_treatment,
    edges_in_judgment,
    treatment_of,
)
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted


def _judgment(session, key: str, title: str, *, bench: int, year: int, scc: str, text: str = "") -> Judgment:
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
    # The alias key must be the grammar's own, not one invented here: an edge is found by looking up
    # exactly what the grammar makes of the citation printed in the citing judgment.
    session.add(
        CitationAlias(
            judgment_id=judgment.id,
            reporter="SCC",
            citation_string=scc,
            normalized=normalize_citation_string(scc),
        )
    )
    if text:
        store_extracted(
            session, judgment, ExtractedJudgment(source_path=key, page_count=4, headnote="", judgment=text)
        )
    return judgment


# --- treatment from the words -------------------------------------------------


@pytest.mark.parametrize(
    ("expected", "sentence"),
    [
        ("overruled", "The decision in Dolat Ram v. State of Haryana is hereby overruled."),
        ("overruled", "We hold that the said decision does not lay down the correct law."),
        ("overruled", "That judgment is no longer good law."),
        ("referred_to_larger_bench", "We refer the question to a larger Bench."),
        ("referred_to_larger_bench", "The matter requires reconsideration."),
        ("doubted", "With respect, we differ from the view taken in that case."),
        ("doubted", "We are unable to agree with the reasoning in Baluram."),
        ("distinguished", "That decision is clearly distinguishable on facts."),
        ("distinguished", "The judgment relied upon has no application to the facts of this case."),
        ("followed", "The issue is squarely covered by the decision in Kasturi."),
        ("relied_on", "Reliance was placed upon the decision in Robin Ramjibhai Patel."),
        ("affirmed", "The view taken therein is affirmed."),
        ("referred", "The appellant cited (2019) 4 SCC 1 in the course of arguments."),
    ],
)
def test_treatment_is_read_from_the_sentence(expected: str, sentence: str) -> None:
    assert classify_treatment(sentence) == expected


# --- the bench rule -----------------------------------------------------------


def test_a_smaller_bench_cannot_overrule_a_larger_one() -> None:
    """Two judges saying a three-judge decision is wrong have doubted it, not overruled it.

    Reporting an overruling that did not happen would be worse than missing one: an advocate would
    drop a binding authority on the strength of it.
    """
    assert apply_bench_rule("overruled", 2, 3) == ("doubted", "overruled")
    assert apply_bench_rule("overruled", 3, 3) == ("doubted", "overruled")


def test_a_larger_bench_may_overrule() -> None:
    assert apply_bench_rule("overruled", 5, 3) == ("overruled", None)
    assert apply_bench_rule("overruled", 7, 5) == ("overruled", None)


def test_an_unknown_bench_is_not_second_guessed() -> None:
    """With a bench strength missing there is no arithmetic to do, so the words stand."""
    assert apply_bench_rule("overruled", None, 3) == ("overruled", None)
    assert apply_bench_rule("overruled", 2, None) == ("overruled", None)


def test_the_rule_touches_nothing_but_overruling() -> None:
    assert apply_bench_rule("doubted", 2, 7) == ("doubted", None)
    assert apply_bench_rule("distinguished", 2, 7) == ("distinguished", None)
    assert apply_bench_rule("followed", 2, 7) == ("followed", None)


# --- edges and reports --------------------------------------------------------


@pytest.fixture
def corpus(session):
    """An earlier three-judge decision, and two later judgments that disagree with it."""
    earlier = _judgment(
        session, "INSC:2015:111", "KASTURI versus IYYAMPERUMAL", bench=3, year=2015, scc="(2015) 6 SCC 733"
    )
    _judgment(
        session,
        "INSC:2021:222",
        "SMALLER BENCH versus SOMEBODY",
        bench=2,
        year=2021,
        scc="(2021) 1 SCC 1",
        text=(
            "1. Leave granted. The appeal arises from a decree for specific performance passed by the "
            "High Court, which the appellant challenges on the ground of limitation and on the ground "
            "that the suit was not maintainable in its present form.\n\n"
            f"2. We are unable to agree with the reasoning in {earlier.title.title()}, "
            f"(2015) 6 SCC 733, which in our respectful view does not address the question now before "
            "us. The point is one of some general importance and we say no more about it here.\n\n"
            "3. The appeal is dismissed with no order as to costs."
        ),
    )
    _judgment(
        session,
        "INSC:2023:333",
        "LARGER BENCH versus SOMEBODY",
        bench=5,
        year=2023,
        scc="(2023) 2 SCC 2",
        text=(
            "1. Leave granted. This reference was occasioned by a conflict between two lines of "
            "authority on the impleadment of strangers to a contract in a suit for specific "
            "performance, and it falls to this Bench to resolve it.\n\n"
            f"2. Having considered the matter, the decision in {earlier.title.title()}, "
            "(2015) 6 SCC 733, is hereby overruled. The contrary view is restored and shall be "
            "followed by all courts.\n\n"
            "3. The reference is answered accordingly."
        ),
    )
    session.commit()
    build_citator(session)
    return session, earlier


def test_edges_are_extracted_with_their_treatment(corpus) -> None:
    session, earlier = corpus
    report = treatment_of(session, earlier.id)
    assert report.citing_count == 2
    assert {e.treatment for e in report.edges} == {"overruled", "doubted"}


def test_the_worst_treatment_decides_the_status(corpus) -> None:
    session, earlier = corpus
    report = treatment_of(session, earlier.id)
    assert report.status == "overruled"
    assert report.is_doubtful
    assert "INSC:2023:333" in (report.note or "")


def test_the_bench_rule_is_applied_when_the_report_is_built(session) -> None:
    """A two-judge bench claiming to overrule a three-judge one is recorded as doubt."""
    earlier = _judgment(
        session, "INSC:2015:111", "KASTURI versus IYYAMPERUMAL", bench=3, year=2015, scc="(2015) 6 SCC 733"
    )
    _judgment(
        session,
        "INSC:2021:222",
        "SMALLER versus SOMEBODY",
        bench=2,
        year=2021,
        scc="(2021) 1 SCC 1",
        text=(
            "1. Leave granted. The appeal concerns the impleadment of a stranger to the contract in a "
            "suit for specific performance, a question on which the authorities are not uniform.\n\n"
            "2. In our considered view the decision in Kasturi Versus Iyyamperumal, (2015) 6 SCC 733, "
            "is hereby overruled, since it does not accord with the scheme of Order 1 Rule 10 CPC as "
            "we understand it.\n\n"
            "3. The appeal is allowed."
        ),
    )
    session.commit()
    build_citator(session)

    report = treatment_of(session, earlier.id)
    assert report.status == "doubted"
    edge = report.worst
    assert edge is not None and edge.downgraded_from == "overruled"
    assert "cannot overrule" in (report.note or "")


def test_a_judgment_nobody_has_cited_is_reported_as_such(session) -> None:
    """Not the same as "no negative treatment exists": the corpus is not the whole of the law."""
    lonely = _judgment(session, "INSC:2016:999", "NOBODY versus NOBODY", bench=2, year=2016, scc="(2016) 1 SCC 9")
    session.commit()
    report = treatment_of(session, lonely.id)
    assert report.status == "good_law"
    assert report.citing_count == 0
    assert "which is not the same as none ever having done so" in (report.note or "")


def test_a_judgment_does_not_cite_itself(session) -> None:
    judgment = _judgment(
        session,
        "INSC:2019:1",
        "ALPHA versus BETA",
        bench=2,
        year=2019,
        scc="(2019) 1 SCC 1",
        text=(
            "1. Leave granted. This appeal concerns the interpretation of Section 19 of the Contract "
            "Act and the circumstances in which consent may be said to have been caused by a "
            "misrepresentation made by the other party to the agreement.\n\n"
            "2. The present case, reported as (2019) 1 SCC 1, requires no further elaboration on the "
            "point, the position being settled by a long line of authority which we need not set out.\n\n"
            "3. The appeal is dismissed."
        ),
    )
    session.commit()
    from orderorder.engine.citator import alias_map
    from orderorder.ingest.aliases import _paragraphs_of

    edges = edges_in_judgment(judgment, _paragraphs_of(session, judgment.id), alias_map(session))
    assert edges == []


def test_the_report_says_how_much_of_the_law_it_searched(corpus) -> None:
    session, earlier = corpus
    report = treatment_of(session, earlier.id)
    assert report.corpus_size == 2  # the two judgments whose text is held


# --- direction: who did what to whom -------------------------------------------


def _at(body: str, citation: str) -> str:
    """Classify treatment of one citation where it actually sits in the sentence."""
    start = body.index(citation)
    return classify_treatment(body, (start, start + len(citation)))


def test_a_case_that_did_the_overruling_is_not_recorded_as_overruled() -> None:
    """From the corpus. The cited case is the bench that overruled something else.

    Read the other way round, a live authority is reported as dead, which is the worst thing a
    citator can say and the reason direction is checked at all.
    """
    body = (
        "A three-Judge Bench of this Court in Mayavati Trading Private Limited v. Pradyut Deb Burman "
        "reported in (2019) 8 SCC 714 overruled the decision in Antique Art (supra) and clarified the "
        "position of law existing prior to the 2015 amendment."
    )
    assert _at(body, "(2019) 8 SCC 714") == "referred"


def test_a_case_that_did_the_reversing_is_not_recorded_as_reversed() -> None:
    body = "The said judgement was reversed by this Court in the Judgment reported in (2020) 10 SCC 264."
    assert _at(body, "(2020) 10 SCC 264") == "referred"


def test_a_case_the_court_merely_considered_is_not_doubted() -> None:
    body = (
        "This issue is elaborately considered by the Supreme Court in A. Ayyasamy v. A. Paramasivam "
        "reported in (2016) 10 SCC 386."
    )
    assert _at(body, "(2016) 10 SCC 386") == "referred"


def test_the_passive_form_attaches_to_the_citation_before_it() -> None:
    body = "The decision in Pune Municipal Corporation, (2014) 3 SCC 183, is hereby overruled."
    assert _at(body, "(2014) 3 SCC 183") == "overruled"


def test_the_active_form_attaches_to_the_citation_after_it() -> None:
    body = "We overrule the decision in Kasturi v. Iyyamperumal, (2005) 6 SCC 733, to that extent."
    assert _at(body, "(2005) 6 SCC 733") == "overruled"


def test_no_longer_good_law_attaches_to_the_case_it_follows() -> None:
    body = "That view, taken in (2014) 3 SCC 183, is no longer good law after the Constitution Bench."
    assert _at(body, "(2014) 3 SCC 183") == "overruled"


def test_a_cue_at_the_far_end_of_a_long_sentence_is_about_another_case() -> None:
    """A judgment's sentences run long and cite several cases; proximity is what ties a cue to one."""
    body = (
        "The appellant relied upon (2011) 2 SCC 100, a decision of two learned Judges of this Court "
        "rendered in a wholly different statutory context and on facts bearing no resemblance to "
        "those before us, and we need not consider it further at this stage of the discussion; the "
        "decision in Antique Art, (2019) 8 SCC 714, is hereby overruled."
    )
    # The first citation was relied on, which is what the words next to it say. What matters is that
    # the overruling at the far end of the sentence does not reach back and kill it.
    assert _at(body, "(2011) 2 SCC 100") == "relied_on"
    assert _at(body, "(2019) 8 SCC 714") == "overruled"


def test_a_quoted_overruling_is_not_credited_to_the_quoting_court() -> None:
    """Judgments quote the Constitution Bench that did the overruling, at length and verbatim.

    Recording that as the quoting court's own act would credit a two-judge bench with a five-judge
    bench's work — and the bench rule would then downgrade a real overruling to mere doubt. The fact
    is not lost: it is read from the judgment that actually gave it.
    """
    body = (
        "The Constitution Bench has observed and held as under:- “365. Resultantly, the decision "
        "rendered in Pune Municipal Corpn. v. Harakchand Misirimal Solanki, (2014) 3 SCC 183 is hereby "
        "overruled and all other decisions following it are also overruled.” We respectfully "
        "follow that decision."
    )
    start = body.index("(2014) 3 SCC 183")
    # The words themselves say "overruled", and read alone that is what they mean.
    assert classify_treatment(body, (start, start + len("(2014) 3 SCC 183"))) == "overruled"

    judgment = Judgment(canonical_key="INSC:2023:1", court="SC", title="QUOTER versus SOMEBODY", source="x")
    paragraph = Paragraph(
        text_version_id="v", seq=1, printed_label="12", body=body, char_start=0, char_end=len(body)
    )
    aliases = {normalize_citation_string("(2014) 3 SCC 183"): "cited-id"}
    edges = edges_in_judgment(judgment, [paragraph], aliases)
    assert [e.treatment for e in edges] == ["referred"]


# --- the audit: every negative edge the corpus produced, checked by hand -------


AUDIT = [
    # False positives found by reading all 21 negative edges of a full corpus run. Each is a real
    # sentence, and each was recorded as killing an authority that it does not kill.
    ("referred", "the 3-Judge Bench in Radhey Shyam v Chhabi Nath, (2015) 5 SCC 423 had only partly "
                 "overruled Surya Dev Rai (supra) in terms below:", "(2015) 5 SCC 423"),
    ("referred", "the subsequent decision of this Court in Commissioner of Customs vs. Dilip Kumar "
                 "[(2018) 9 SCC 1] by which this Court overruled the decision of this Court in Sun "
                 "Export Corporation", "(2018) 9 SCC 1"),
    ("referred", "the insurer while taking out the policies was reversed and the appeal was allowed. "
                 "(c) Canara Bank v. United India Insurance Co. (2020) 3 SCC 455, is a case in which "
                 "this Court held that if a column is left blank", "(2020) 3 SCC 455"),
    ("referred", "Krishna Veni Nagam v. Harish Nagam (2017) 4 SCC 150 - partly overruled. Bhuwan "
                 "Mohan Singh v. Meena (2015) 6 SCC 353 : (2014) 8 SCR 858 - referred to.",
                 "(2015) 6 SCC 353"),
    ("referred", "Kharak Singh v. State of Uttar Pradesh AIR 1963 SC 1295 - partly overruled. Maneka "
                 "Gandhi v. Union of India [1978] 2 SCR 621 : (1978) 1 SCC 248 - referred to.",
                 "[1978] 2 SCR 621"),
    # True positives from the same run, which the fixes must not lose.
    ("overruled", "all judgments rendered on the basis of Pune Municipal Corporation [(2014) 3 SCC "
                  "183] are overruled in view of the interpretation made to Section 24(2).",
                  "(2014) 3 SCC 183"),
    ("overruled", "Vijay Kumar Mishra v. High Court of Judicature at Patna (2016) 9 SCC 313 - "
                  "overruled.", "(2016) 9 SCC 313"),
    ("partly_overruled", "Krishna Veni Nagam v. Harish Nagam (2017) 4 SCC 150 - partly overruled.",
                         "(2017) 4 SCC 150"),
    ("doubted", "correctness of the decision of Pune Municipal Corporation [2014 (3) SCC 183] has "
                "been doubted by this Bench.", "2014 (3) SCC 183"),
    ("referred_to_larger_bench", "New India Assurance v. Hilli Multipurpose Cold Storage, reported in "
                                 "(2015) 16 SCC 20 has been referred to a larger Bench.",
                                 "(2015) 16 SCC 20"),
]


@pytest.mark.parametrize(("expected", "body", "citation"), AUDIT)
def test_the_hand_audited_corpus_sentences(expected: str, body: str, citation: str) -> None:
    """Read off a full corpus run and checked one by one. Precision here is the whole value.

    A citator that says "overruled" when it means "cited the case that overruled something else" is
    worse than no citator, because an advocate acts on it.
    """
    assert _at(body, citation) == expected


# --- undermined: what the judgment stood on was taken away ---------------------


@pytest.fixture
def chain(session):
    """A 2014 decision, a 2016 judgment that followed it, and a 2020 bench that overruled the first."""
    base = _judgment(session, "INSC:2014:1", "PUNE MUNICIPAL versus HARAKCHAND", bench=3, year=2014,
                     scc="(2014) 3 SCC 183")
    follower = _judgment(
        session, "INSC:2016:2", "VIJAY LATKA versus STATE OF HARYANA", bench=2, year=2016,
        scc="(2016) 2 SCC 764",
        text=(
            "1. Leave granted. This appeal concerns the lapsing of acquisition proceedings under "
            "Section 24(2) of the 2013 Act, a question on which the authorities have not spoken with "
            "one voice and which falls for decision here.\n\n"
            "2. The issue is squarely covered by the decision in Pune Municipal Corporation, "
            "(2014) 3 SCC 183, which we respectfully follow. The acquisition proceedings therefore "
            "lapsed on the failure to deposit compensation in court.\n\n"
            "3. The appeal is allowed with no order as to costs."
        ),
    )
    _judgment(
        session, "INSC:2020:3", "INDORE DEVELOPMENT AUTHORITY versus MANOHARLAL", bench=5, year=2020,
        scc="(2020) 8 SCC 129",
        text=(
            "1. Leave granted. This reference was occasioned by a conflict between two lines of "
            "authority upon the construction of Section 24(2) of the 2013 Act, and it falls to this "
            "Bench of five judges to resolve it once and for all.\n\n"
            "2. Resultantly, the decision rendered in Pune Municipal Corporation, (2014) 3 SCC 183, "
            "is hereby overruled. The contrary construction is restored.\n\n"
            "3. The reference is answered accordingly."
        ),
    )
    session.commit()
    build_citator(session)
    return session, base, follower


def test_a_judgment_that_followed_an_overruled_one_is_undermined(chain) -> None:
    """Nothing was said about this judgment. What it stood on was taken away.

    The Constitution Bench said as much in terms: "all other decisions in which Pune Municipal
    Corpn. has been followed, are also overruled."
    """
    session, _, follower = chain
    report = treatment_of(session, follower.id)
    assert report.status == "undermined"
    assert report.is_doubtful
    assert report.is_undermined
    assert len(report.undermined_by) == 1
    link = report.undermined_by[0]
    assert link.relied_on_key == "INSC:2014:1"
    assert link.relied_on_treatment == "overruled"
    assert link.killed_by_key == "INSC:2020:3"


def test_the_report_says_the_inference_is_not_a_holding(chain) -> None:
    """A court said the earlier case was wrong. No court has said anything about this one."""
    session, _, follower = chain
    note = treatment_of(session, follower.id).note or ""
    assert "not a holding of any court" in note
    assert "which part of the earlier case it used" in note


def test_the_case_that_was_actually_overruled_reports_that_not_this(chain) -> None:
    session, base, _ = chain
    assert treatment_of(session, base.id).status == "overruled"


def test_a_judgment_decided_after_the_overruling_is_not_undermined(session) -> None:
    """It had the news already, and may have dealt with it. Silence is not reliance."""
    _judgment(session, "INSC:2014:1", "PUNE MUNICIPAL versus HARAKCHAND", bench=3, year=2014,
              scc="(2014) 3 SCC 183")
    _judgment(
        session, "INSC:2020:3", "INDORE versus MANOHARLAL", bench=5, year=2020, scc="(2020) 8 SCC 129",
        text=("1. Leave granted. The reference concerns Section 24(2) of the 2013 Act and the "
              "conflict between two lines of authority upon its construction.\n\n"
              "2. Resultantly, the decision rendered in Pune Municipal Corporation, (2014) 3 SCC 183, "
              "is hereby overruled.\n\n3. The reference is answered."),
    )
    later = _judgment(
        session, "INSC:2023:4", "LATER versus SOMEBODY", bench=2, year=2023, scc="(2023) 1 SCC 1",
        text=("1. Leave granted. The appeal concerns the same statutory provision and the effect of "
              "the failure to deposit compensation within the time allowed by the Act.\n\n"
              "2. The issue is squarely covered by the decision in Pune Municipal Corporation, "
              "(2014) 3 SCC 183, which we follow.\n\n3. The appeal is allowed."),
    )
    session.commit()
    build_citator(session)
    assert treatment_of(session, later.id).status == "good_law"


def test_merely_referring_to_an_overruled_case_does_not_undermine(session) -> None:
    """Reliance is what carries the wound. A judgment that mentions a case did not stand on it."""
    _judgment(session, "INSC:2014:1", "PUNE MUNICIPAL versus HARAKCHAND", bench=3, year=2014,
              scc="(2014) 3 SCC 183")
    mentioner = _judgment(
        session, "INSC:2016:2", "MENTIONER versus SOMEBODY", bench=2, year=2016, scc="(2016) 2 SCC 764",
        text=("1. Leave granted. The appeal concerns the construction of Section 24(2) of the Act of "
              "2013 and the consequences of a failure to deposit compensation in court.\n\n"
              "2. The appellant cited Pune Municipal Corporation, (2014) 3 SCC 183, in the course of "
              "arguments, but nothing turns on it for present purposes.\n\n3. The appeal is dismissed."),
    )
    _judgment(
        session, "INSC:2020:3", "INDORE versus MANOHARLAL", bench=5, year=2020, scc="(2020) 8 SCC 129",
        text=("1. Leave granted. The reference concerns Section 24(2) of the 2013 Act and the "
              "conflict between two lines of authority upon its construction.\n\n"
              "2. Resultantly, the decision rendered in Pune Municipal Corporation, (2014) 3 SCC 183, "
              "is hereby overruled.\n\n3. The reference is answered."),
    )
    session.commit()
    build_citator(session)
    assert treatment_of(session, mentioner.id).status == "good_law"


def test_direct_treatment_outranks_the_inference(chain) -> None:
    """What a court said about this judgment beats what can be inferred about its foundations."""
    session, _, follower = chain
    _judgment(
        session, "INSC:2022:9", "CRITIC versus SOMEBODY", bench=3, year=2022, scc="(2022) 1 SCC 9",
        text=("1. Leave granted. The appeal turns on the same provision considered in the decisions "
              "referred to below, and on the effect of the deposit of compensation.\n\n"
              "2. With respect, we differ from the view taken in Vijay Latka versus State of Haryana, "
              "(2016) 2 SCC 764, for the reasons that follow.\n\n3. The appeal is allowed."),
    )
    session.commit()
    build_citator(session)
    report = treatment_of(session, follower.id)
    assert report.status == "doubted"


# --- "(supra)": a case named without its citation ------------------------------


def test_a_case_named_only_by_supra_is_still_an_edge(session) -> None:
    """The sentence that overruled Pune Municipal Corporation carries no citation at all.

    "Resultantly, the decision rendered in Pune Municipal Corporation & Anr. (supra) is hereby
    overruled" — the case was cited in full three hundred paragraphs earlier, and by the time the
    court comes to decide it says "(supra)". A citator reading only citations cannot see the thing it
    exists to find.
    """
    cited = _judgment(session, "INSC:2014:1", "PUNE MUNICIPAL CORPORATION & ANR. versus HARAKCHAND",
                      bench=3, year=2014, scc="(2014) 3 SCC 183")
    citing = _judgment(
        session, "INSC:2020:2", "INDORE DEVELOPMENT AUTHORITY versus MANOHARLAL", bench=5, year=2020,
        scc="(2020) 8 SCC 129",
        text=(
            "1. Leave granted. This reference concerns Section 24(2) of the 2013 Act and the conflict "
            "between two lines of authority upon its construction, which falls to this Bench.\n\n"
            "2. The decisions were surveyed at length, among them Pune Municipal Corporation, "
            "(2014) 3 SCC 183, upon which much of the argument turned before us.\n\n"
            "3. Resultantly, the decision rendered in Pune Municipal Corporation & Anr. (supra) is "
            "hereby overruled and the contrary construction is restored.\n\n"
            "4. The reference is answered accordingly."
        ),
    )
    session.commit()

    from orderorder.engine.citator import alias_map, title_map

    paragraphs = [p for p in _paragraphs(session, citing.id)]
    edges = edges_in_judgment(citing, paragraphs, alias_map(session), title_map(session))
    by_treatment = {e.treatment: e for e in edges if e.cited_id == cited.id}
    assert "overruled" in by_treatment
    assert "(supra)" in by_treatment["overruled"].cited_alias


def test_supra_resolves_only_against_cases_this_judgment_cites(session) -> None:
    """A "(supra)" means a case cited earlier here, so the corpus at large is not a candidate.

    Without that limit the name would be matched against nine thousand titles, and a common one —
    "State of Maharashtra v. Ramesh" — would attach an overruling to whichever happened to score best.
    """
    elsewhere = _judgment(session, "INSC:2014:9", "FAMOUS CASE versus SOMEBODY", bench=3, year=2014,
                          scc="(2014) 9 SCC 9")
    citing = _judgment(
        session, "INSC:2020:2", "LATER versus SOMEBODY", bench=5, year=2020, scc="(2020) 8 SCC 129",
        text=("1. Leave granted. The appeal concerns a question of construction upon which the "
              "authorities have not spoken with one voice, and which falls for decision here.\n\n"
              "2. The decision in Famous Case (supra) is hereby overruled, though we have not cited "
              "it anywhere in this judgment and it is named here for the first time.\n\n"
              "3. The appeal is allowed."),
    )
    session.commit()

    from orderorder.engine.citator import alias_map, title_map

    edges = edges_in_judgment(
        citing, _paragraphs(session, citing.id), alias_map(session), title_map(session)
    )
    assert [e for e in edges if e.cited_id == elsewhere.id] == []


def _paragraphs(session, judgment_id: str) -> list[Paragraph]:
    from sqlalchemy import select

    from orderorder.db.models import JudgmentTextVersion

    version = session.scalars(
        select(JudgmentTextVersion).where(JudgmentTextVersion.judgment_id == judgment_id)
    ).first()
    return list(
        session.scalars(
            select(Paragraph).where(Paragraph.text_version_id == version.id).order_by(Paragraph.seq)
        ).all()
    )
