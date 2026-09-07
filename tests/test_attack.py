"""The self-attack on a draft this tool wrote.

The trap this section walks into is that everything in the draft has already passed the gate, so a
self-attack that looks for what the gate looks for finds nothing and prints an assurance. So what is
tested here is that it looks somewhere else — the citation graph, the bench strengths, the dates, and
the corpus itself for a judgment that says the other thing — and that it says out loud what it did not
look at.
"""

from __future__ import annotations

import datetime as dt

import pytest

from orderorder.db.models import CitationAlias, CitationEdge, Judgment
from orderorder.drafting.assemble import Point, assemble
from orderorder.drafting.attack import (
    CONTRARY,
    DISTINGUISHED,
    MIN_CITED_SHARE,
    NOT_CHECKED,
    ORDER,
    OUTRANKED,
    THIN,
    UNSUPPORTED,
    attack_draft,
    cited_share,
)
from orderorder.drafting.plan import parse_plan
from orderorder.drafting.render import to_markdown
from orderorder.engine.authority import BOUND, NARROWED, REFUSED, Binding, Considered
from orderorder.engine.citator import TreatmentEdge, TreatmentReport
from orderorder.engine.scope import ScopeVerdict
from orderorder.engine.search import Authority, build_index
from orderorder.engine.verdict import CitationVerdict
from orderorder.ingest.pdf import ExtractedJudgment
from orderorder.ingest.store import store_extracted

CLAIM = "The doctrine of frustration has no application where the parties allocated the risk"

ALPHA = """1. Leave granted.

2. The doctrine of frustration has no application where the parties have expressly allocated the
risk of the supervening event between themselves in the contract that they made.

3. The appeal is accordingly dismissed with no order as to costs.
"""

GAMMA = """1. Leave granted.

2. We reiterate that the doctrine of frustration has no application where the parties have
allocated the risk of the supervening event between themselves, and we say so for a larger bench.

3. The appeal is dismissed.
"""

PLAN = f"""court: In the Supreme Court of India
parties: X versus Y

# issue Whether frustration was made out
{CLAIM}.

# prayer
allow the appeal
"""


def _judgment(session, key: str, title: str, text: str, *, year: int, bench: int) -> Judgment:
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
        ExtractedJudgment(source_path=key, page_count=2, headnote="", judgment=text),
    )
    return judgment


OPPOSITE = """1. Leave granted.

2. The doctrine of frustration applies notwithstanding an allocation by the parties of the risk of
the supervening event between themselves in their contract.

3. The appeal is allowed.
"""


@pytest.fixture
def corpus(session):
    _judgment(session, "INSC:2019:1", "ALPHA versus BETA", ALPHA, year=2019, bench=2)
    _judgment(session, "INSC:2022:9", "GAMMA versus DELTA", GAMMA, year=2022, bench=3)
    session.commit()
    build_index(session)
    return session


@pytest.fixture
def with_a_contrary_judgment(session):
    """The same corpus, plus a judgment holding the other way on the very proposition."""
    _judgment(session, "INSC:2019:1", "ALPHA versus BETA", ALPHA, year=2019, bench=2)
    _judgment(session, "INSC:2023:4", "EPSILON versus ZETA", OPPOSITE, year=2023, bench=3)
    session.commit()
    build_index(session)
    return session


@pytest.fixture
def well_cited(corpus):
    """A corpus where being uncited is unusual, so the thin attack has something to stand on.

    Two judgments and an edge between them: half the corpus has been cited, which clears
    `MIN_CITED_SHARE`. The real corpus does not clear it -- 79% of it has never been cited -- and
    `test_a_sparse_citation_graph_says_nothing` is that case.
    """
    alpha = corpus.query(Judgment).filter_by(canonical_key="INSC:2019:1").one()
    gamma = corpus.query(Judgment).filter_by(canonical_key="INSC:2022:9").one()
    corpus.add(CitationEdge(citing_id=gamma.id, cited_id=alpha.id, treatment="referred"))
    corpus.commit()
    return corpus


def _authority(session=None, key: str = "INSC:2019:1", **kwargs) -> Authority:
    judgment_id = "j1"
    if session is not None:
        judgment_id = session.query(Judgment).filter_by(canonical_key=key).one().id
    base = {
        "judgment_id": judgment_id,
        "canonical_key": key,
        "title": "ALPHA versus BETA",
        "citation": "(2019) 4 SCC 118",
        "court": "Supreme Court of India",
        "decided_on": "2019-06-01",
        "bench_strength": 2,
        "paragraph_label": "2",
        "paragraph_seq": 2,
        "body": CLAIM + ".",
        "relevance": 10.0,
        "score": 10.1,
        "treatment": TreatmentReport(judgment_id=judgment_id, status="good_law", citing_count=3),
    }
    base.update(kwargs)
    return Authority(**base)


def _bound_draft(authority: Authority, *, status: str = BOUND, scope: ScopeVerdict | None = None):
    verdict = CitationVerdict(
        citation_raw=authority.citation or "",
        proposition=CLAIM + ".",
        existence="found",
        support="full" if status == BOUND else "partial",
        quote="no application where the parties have expressly allocated the risk",
        quote_verified=True,
        scope=scope,
    )
    chosen = Considered(authority, verdict, status, "the court says this")
    binding = Binding(CLAIM + ".", status, chosen.reason, chosen=chosen, considered=[chosen])
    return assemble(parse_plan(PLAN), {CLAIM + ".": binding})


# --- what the gate cannot catch ---------------------------------------------------------------------


def test_a_case_held_inapplicable_on_its_facts_is_an_attack_not_a_defect(session) -> None:
    """The gate refuses overruled law. Law that a later court distinguished is still good law.

    Which is exactly why it belongs here: it is not something wrong with the authority, it is the
    argument the other side is going to make about it.
    """
    treatment = TreatmentReport(
        judgment_id="j1",
        status="good_law",
        citing_count=1,
        edges=[
            TreatmentEdge(
                citing_key="INSC:2023:5",
                citing_title="EPSILON versus ZETA",
                citing_date="2023-03-01",
                citing_bench=2,
                treatment="distinguished",
                paragraph_label="14",
            )
        ],
    )
    draft = _bound_draft(_authority(treatment=treatment))
    attacks = [a for a in attack_draft(session, draft) if a.kind == DISTINGUISHED]
    assert len(attacks) == 1
    assert "EPSILON versus ZETA" in attacks[0].says
    assert "2023" in attacks[0].says


def test_an_authority_nobody_has_cited_is_worth_saying_out_loud(well_cited) -> None:
    treatment = TreatmentReport(judgment_id="j1", status="good_law", citing_count=0)
    draft = _bound_draft(_authority(treatment=treatment))
    assert [a.kind for a in attack_draft(well_cited, draft) if a.kind == THIN]


def test_a_sparse_citation_graph_says_nothing_about_one_authority(corpus) -> None:
    """The bug this guard exists for.

    `corpus` has two judgments and no edges, so nothing in it has ever been cited -- which is the
    shape of the real corpus, where 8,716 edges over 9,429 judgments leave 79% never cited. At that
    density "no later judgment has cited this" describes the corpus, not the authority, and it fired
    on four authorities in five. A section of noise is a section that gets skipped, and it takes the
    real attacks with it.
    """
    treatment = TreatmentReport(judgment_id="j1", status="good_law", citing_count=0)
    draft = _bound_draft(_authority(corpus, treatment=treatment))
    assert cited_share(corpus) < MIN_CITED_SHARE
    assert not [a for a in attack_draft(corpus, draft) if a.kind == THIN]


def test_a_well_cited_authority_is_not_called_thin(well_cited) -> None:
    draft = _bound_draft(_authority())
    assert not [a for a in attack_draft(well_cited, draft) if a.kind == THIN]


def test_a_larger_bench_on_the_same_words_is_surfaced_as_a_lead(corpus) -> None:
    """The first thing the other side's junior will find. Finding it after they do is the expensive way."""
    draft = _bound_draft(_authority(corpus))
    outranked = [a for a in attack_draft(corpus, draft) if a.kind == OUTRANKED]
    assert outranked
    assert "GAMMA versus DELTA" in outranked[0].says
    assert "3 judges" in outranked[0].says


def test_the_judgment_the_draft_cites_does_not_outrank_itself(corpus) -> None:
    draft = _bound_draft(_authority(corpus, key="INSC:2022:9", bench_strength=3, decided_on="2022-06-01"))
    outranked = [a for a in attack_draft(corpus, draft) if a.kind == OUTRANKED]
    assert all("GAMMA" not in a.says for a in outranked)


def test_a_judgment_that_says_the_opposite_is_an_attack(with_a_contrary_judgment) -> None:
    """The attack an opponent opens with, and the one the gate cannot make.

    Everything else here is about the authority behind the point. This is about the point.
    """
    draft = _bound_draft(_authority(with_a_contrary_judgment))
    attacks = attack_draft(with_a_contrary_judgment, draft)
    contrary = [a for a in attacks if a.kind == CONTRARY]
    assert contrary
    assert "EPSILON" in contrary[0].says
    assert "applies notwithstanding" in contrary[0].says
    assert "Read it" in contrary[0].fix


def test_a_point_is_not_attacked_with_its_own_authority(with_a_contrary_judgment) -> None:
    draft = _bound_draft(_authority(with_a_contrary_judgment))
    attacks = attack_draft(with_a_contrary_judgment, draft)
    assert all("ALPHA" not in a.says for a in attacks if a.kind == CONTRARY)


def test_the_contrary_search_can_be_left_out(with_a_contrary_judgment) -> None:
    """It is the expensive one: a corpus search per point against a citation-graph lookup."""
    draft = _bound_draft(_authority(with_a_contrary_judgment))
    attacks = attack_draft(with_a_contrary_judgment, draft, search_contrary=False)
    assert not [a for a in attacks if a.kind == CONTRARY]


def test_the_contrary_attack_comes_before_the_leads(with_a_contrary_judgment) -> None:
    """A judgment saying the other thing outranks "here is another case on the same words"."""
    assert ORDER.index(CONTRARY) < ORDER.index(OUTRANKED)


def test_a_proposition_with_no_authority_is_the_first_attack(session) -> None:
    draft = assemble(parse_plan(PLAN), {CLAIM + ".": Binding(CLAIM + ".", REFUSED, "nothing found")})
    attacks = attack_draft(session, draft)
    assert attacks[0].kind == UNSUPPORTED
    assert attacks[0].citation is None


def test_a_narrowing_the_draft_already_made_is_still_an_attack(session) -> None:
    """The draft argues the narrower form. The opponent will still say the wider one was abandoned."""
    scope = ScopeVerdict(
        claim=CLAIM,
        support="partial",
        model_support="partial",
        narrowed_proposition="Frustration does not apply where the contract allocates the risk",
    )
    draft = _bound_draft(_authority(), status=NARROWED, scope=scope)
    narrowed = [a for a in attack_draft(session, draft) if a.kind == "narrowed"]
    assert len(narrowed) == 1
    assert CLAIM in narrowed[0].fix


# --- what it says it did not look at ----------------------------------------------------------------


def test_the_section_says_what_it_did_not_check(session) -> None:
    """A self-attack that stops at what it found reads as a statement that this is all there is."""
    draft = _bound_draft(_authority())
    text = to_markdown(draft, attack_draft(session, draft))
    assert NOT_CHECKED in text
    assert "governs the facts of this matter was not checked" in text


def test_an_empty_self_attack_says_where_it_looked(session) -> None:
    draft = _bound_draft(_authority())
    text = to_markdown(draft, [])
    assert "Nothing found in the citation graph" in text
    assert NOT_CHECKED in text


def test_the_document_has_no_self_attack_section_when_none_was_asked_for(session) -> None:
    draft = _bound_draft(_authority())
    assert "WHAT THE OTHER SIDE WILL SAY" not in to_markdown(draft)


def test_the_citation_graph_is_read_from_the_database(corpus) -> None:
    """Not a hand-built report: the edge is a row, and `treatment_of` is what finds it."""
    alpha = corpus.query(Judgment).filter_by(canonical_key="INSC:2019:1").one()
    gamma = corpus.query(Judgment).filter_by(canonical_key="INSC:2022:9").one()
    corpus.add(CitationEdge(citing_id=gamma.id, cited_id=alpha.id, treatment="distinguished"))
    corpus.commit()

    from orderorder.engine.citator import treatment_of

    authority = _authority(corpus, treatment=treatment_of(corpus, alpha.id))
    attacks = [a for a in attack_draft(corpus, _bound_draft(authority)) if a.kind == DISTINGUISHED]
    assert len(attacks) == 1
    assert "GAMMA versus DELTA" in attacks[0].says


def test_every_attack_names_the_proposition_it_is_about(session) -> None:
    """A list of attacks with no sentence attached is a list a person cannot act on."""
    draft = _bound_draft(_authority(treatment=TreatmentReport(judgment_id="j1", status="good_law")))
    for attack in attack_draft(session, draft):
        assert attack.proposition
        assert attack.fix


def test_a_point_that_is_cited_carries_its_pinpoint_into_the_attack(well_cited) -> None:
    treatment = TreatmentReport(judgment_id="j1", status="good_law", citing_count=0)
    draft = _bound_draft(_authority(treatment=treatment))
    thin = [a for a in attack_draft(well_cited, draft) if a.kind == THIN][0]
    assert thin.citation == "(2019) 4 SCC 118, para 2"


def test_points_are_read_from_the_draft_not_the_bindings(session) -> None:
    """The attack runs over the assembled document, so anything the assembler dropped is invisible."""
    draft = _bound_draft(_authority())
    assert isinstance(draft.points[0], Point)
    assert len(draft.points) == 1
