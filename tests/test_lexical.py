"""BM25 ranking inside one judgment, and the fusion seam the dense retriever will use."""

from __future__ import annotations

from orderorder.engine.lexical import BM25Index, reciprocal_rank_fusion, tokenize

PARAGRAPHS = [
    "Feeling aggrieved by the impugned judgment, the appellant preferred these appeals.",
    "The facts of the case leading to these appeals in nutshell are as under.",
    "A misrepresentation vitiates consent only where it induced the contract to sell.",
    "In view of the above, we are in complete agreement with the view taken by the High Court.",
    "The plaintiff is the dominus litis and cannot be compelled to implead a party.",
]


def test_tokenize_drops_stopwords_and_keeps_legal_terms() -> None:
    tokens = tokenize("The plaintiff is the dominus litis of the suit")
    assert "plaintiff" in tokens
    assert "dominus" in tokens
    assert "the" not in tokens
    assert "is" not in tokens


def test_ranks_the_relevant_paragraph_first() -> None:
    index = BM25Index.build(PARAGRAPHS)
    ranked = index.score("misrepresentation vitiates consent inducement")
    assert ranked
    assert ranked[0].index == 2


def test_dominus_litis_query_finds_its_paragraph() -> None:
    index = BM25Index.build(PARAGRAPHS)
    assert index.score("dominus litis implead")[0].index == 4


def test_scores_descend() -> None:
    ranked = BM25Index.build(PARAGRAPHS).score("appeals judgment High Court")
    assert [r.score for r in ranked] == sorted((r.score for r in ranked), reverse=True)


def test_matched_terms_are_reported() -> None:
    ranked = BM25Index.build(PARAGRAPHS).score("misrepresentation consent")
    assert "misrepresentation" in ranked[0].matched_terms


def test_unmatched_query_returns_nothing() -> None:
    assert BM25Index.build(PARAGRAPHS).score("cryptocurrency taxation offshore") == []


def test_stopword_only_query_returns_nothing() -> None:
    assert BM25Index.build(PARAGRAPHS).score("the and of is") == []


def test_top_k_limits_results() -> None:
    ranked = BM25Index.build(PARAGRAPHS).score("the appellant judgment court appeals", top_k=2)
    assert len(ranked) <= 2


def test_empty_index_is_safe() -> None:
    assert BM25Index.build([]).score("anything") == []


def test_scores_are_never_negative() -> None:
    """A term present in every paragraph must not drive a score below zero."""
    repeated = ["the court held that the appeal is allowed"] * 4
    for result in BM25Index.build(repeated).score("court appeal"):
        assert result.score >= 0


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    """An item ranked well by both rankers must beat one ranked first by only a single ranker."""
    fused = reciprocal_rank_fusion([[7, 1, 2], [1, 7, 3]])
    assert fused[0][0] == 1
    assert dict(fused)[1] > dict(fused)[2]


def test_fusion_of_one_ranking_preserves_order() -> None:
    assert [item for item, _ in reciprocal_rank_fusion([[5, 3, 9]])] == [5, 3, 9]
