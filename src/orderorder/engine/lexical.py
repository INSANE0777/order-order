"""BM25 ranking over the paragraphs of a single judgment.

Retrieval inside one judgment is a small problem: even a long judgment has a few hundred paragraphs, so
scoring them in Python takes microseconds and needs no index, no extension and no service. That keeps
the hackathon build free and identical on SQLite and Postgres.

This is the lexical half of the hybrid retrieval the architecture specifies. The dense half (BGE-M3
embeddings) fuses with it through `reciprocal_rank_fusion` when it arrives; the fusion function is here
already so the seam is explicit. Corpus-wide search is a different problem and belongs in Postgres.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

K1 = 1.5
B = 0.75
RRF_K = 60

# Words carrying no discriminating power in a judgment. Deliberately short: legal terms stay.
STOPWORDS = frozenset(
    """
    a an the and or but if of in on at to for with without by from as is are was were be been being
    that this these those it its it's he she they them his her their we us our you your i
    not no nor so than then there here which who whom whose what when where why how
    have has had do does did shall will would should could may might must can
    said such other same any all each both few more most some only own very
    """.split()  # noqa: SIM905 - a readable block of words beats a 100-element list literal
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens with stopwords removed. Legal vocabulary is deliberately preserved."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class ScoredDocument:
    index: int
    score: float
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class BM25Index:
    """An in-memory BM25 index over one judgment's paragraphs."""

    documents: list[list[str]]
    doc_freq: dict[str, int]
    doc_len: list[int]
    avg_len: float
    n: int

    @classmethod
    def build(cls, texts: list[str]) -> BM25Index:
        documents = [tokenize(t) for t in texts]
        doc_freq: Counter[str] = Counter()
        for tokens in documents:
            doc_freq.update(set(tokens))
        lengths = [len(d) for d in documents]
        avg = (sum(lengths) / len(lengths)) if lengths else 0.0
        return cls(documents, dict(doc_freq), lengths, avg, len(documents))

    def _idf(self, term: str) -> float:
        df = self.doc_freq.get(term, 0)
        if df == 0:
            return 0.0
        # BM25 idf, floored at zero so a term in every paragraph cannot push a score negative.
        return max(0.0, math.log(1 + (self.n - df + 0.5) / (df + 0.5)))

    def score(self, query: str, *, top_k: int | None = None) -> list[ScoredDocument]:
        """Rank paragraphs against the query, best first. Zero-scoring paragraphs are dropped."""
        terms = tokenize(query)
        if not terms or self.n == 0:
            return []
        query_terms = Counter(terms)
        results: list[ScoredDocument] = []
        for i, tokens in enumerate(self.documents):
            if not tokens:
                continue
            counts = Counter(tokens)
            score = 0.0
            matched: list[str] = []
            length = self.doc_len[i]
            for term in query_terms:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf(term)
                if idf <= 0:
                    continue
                denominator = tf + K1 * (1 - B + B * (length / self.avg_len if self.avg_len else 1))
                score += idf * (tf * (K1 + 1)) / denominator
                matched.append(term)
            if score > 0:
                results.append(ScoredDocument(i, score, sorted(set(matched))))
        results.sort(key=lambda r: (-r.score, r.index))
        return results[:top_k] if top_k else results


def reciprocal_rank_fusion(rankings: list[list[int]], *, k: int = RRF_K) -> list[tuple[int, float]]:
    """Fuse several rankings of the same items into one, best first.

    Reciprocal rank fusion needs no score calibration between the rankers, which is why it is the right
    way to combine BM25 with cosine similarity once embeddings exist.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
