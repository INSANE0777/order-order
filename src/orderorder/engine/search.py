"""Which judgment backs this proposition, and where exactly in it?

The verification engine runs in one direction: a brief names a case, the resolver turns the citation
into a judgment, and the locator finds the paragraph. This module is the other direction, and it is
the one a lawyer preparing arguments actually starts from. There is no citation. There is a
proposition — "misrepresentation vitiates consent only where it induced the contract" — and the
question is which Supreme Court judgment says so, and which line of it.

Answering that means searching every paragraph of every judgment held, so the retrieval here is
corpus-wide, where `engine.lexical` is deliberately confined to one judgment. Three stages:

1. **Find candidate paragraphs.** SQLite's FTS5 index over paragraph bodies, ranked by BM25. Postgres
   gets the same treatment through its own full-text index when the corpus moves there, and dense
   retrieval fuses in through `reciprocal_rank_fusion` when embeddings arrive; the ranking is a list
   of paragraph ids either way, which is what keeps that swap cheap.
2. **Weigh the authority, not just the words.** A paragraph that matches the words well is worthless
   if it is counsel's submission, or the reporter's headnote, or a dissent. Every candidate goes
   through the same voice attribution the verifier uses, and a passage that is not the court speaking
   is dropped. Bench strength and recency then order what remains, because a seven-judge bench from
   1973 outranks a two-judge bench from last year on the same point.
3. **Name the line.** Within the winning paragraph, the sentence carrying most of the proposition's
   distinctive terms is picked out and returned with its offsets. That is the answer to "where in the
   three hundred pages", and it is computed without a model.

What this does not do is decide whether the paragraph *supports* the proposition to the extent the
lawyer means it. That is the scope comparator's job, it needs a model, and `orderorder find` will run
it when one is configured. Retrieval proposes; only the verifier confirms.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import bindparam
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from orderorder.db.models import Judgment
from orderorder.engine.lexical import tokenize
from orderorder.engine.locator import Candidate
from orderorder.engine.sentences import split_sentences
from orderorder.engine.voice import VoiceVerdict, attribute_voice

FTS_TABLE = "paragraph_fts"
DEFAULT_CANDIDATES = 120
DEFAULT_TOP = 5

# How much a judgment's standing counts beside how well its words match. A larger bench binds a
# smaller one, so bench strength is worth more than recency; both are worth less than relevance,
# which is why these are small.
BENCH_WEIGHT = 0.06
RECENCY_WEIGHT = 0.02
RECENCY_FLOOR_YEAR = 1950


@dataclass
class Authority:
    """One paragraph offered as authority for a proposition."""

    judgment_id: str
    canonical_key: str
    title: str
    citation: str | None
    decided_on: str | None
    bench_strength: int | None
    paragraph_label: str | None
    paragraph_seq: int
    body: str
    relevance: float
    score: float
    voice: VoiceVerdict | None = None
    line: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    matched_terms: list[str] = field(default_factory=list)

    @property
    def pinpoint(self) -> str:
        return f"{self.citation or self.canonical_key}, para {self.paragraph_label or self.paragraph_seq}"


def index_exists(session: Session) -> bool:
    row = session.execute(
        sql_text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"), {"name": FTS_TABLE}
    ).first()
    return row is not None


def build_index(session: Session, *, rebuild: bool = False) -> int:
    """Create the full-text index over every stored paragraph. Returns how many rows it holds.

    The index is a standalone FTS5 table rebuilt from `paragraph`, not a table kept in step by
    triggers. The corpus arrives in batches from `ingest bulk-text` and is otherwise static, so a
    rebuild after ingestion is simpler than triggers and cannot drift half-updated.
    """
    if rebuild and index_exists(session):
        session.execute(sql_text(f"DROP TABLE {FTS_TABLE}"))
        session.commit()

    session.execute(
        sql_text(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
                body,
                paragraph_id UNINDEXED,
                judgment_id UNINDEXED,
                tokenize='porter unicode61'
            )
            """
        )
    )
    count = session.execute(sql_text(f"SELECT count(*) FROM {FTS_TABLE}")).scalar() or 0
    if count:
        return count

    # Only the preferred text version of each judgment is indexed: the same judgment held twice would
    # otherwise return the same holding twice, from two numberings, as if they were two authorities.
    # The headnote is excluded at the index, not at query time, because it is the publisher's summary
    # and no amount of ranking should ever surface it as the court's authority.
    session.execute(
        sql_text(
            f"""
            INSERT INTO {FTS_TABLE} (body, paragraph_id, judgment_id)
            SELECT p.body, p.id, v.judgment_id
            FROM paragraph p
            JOIN judgment_text_version v ON v.id = p.text_version_id
            LEFT JOIN opinion o ON o.id = p.opinion_id
            WHERE v.preferred = 1
              AND (o.kind IS NULL OR o.kind != 'headnote')
            """
        )
    )
    session.commit()
    return session.execute(sql_text(f"SELECT count(*) FROM {FTS_TABLE}")).scalar() or 0


def fts_query(proposition: str) -> str:
    """Turn a proposition into an FTS5 query.

    Stopwords are already gone; each remaining term is quoted so that punctuation a legal phrase
    carries cannot be read as FTS5 syntax, and they are OR-ed because a judgment states a rule in its
    own words and will rarely carry all of them.
    """
    terms = [t for t in tokenize(proposition) if len(t) > 2]
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))


def search_paragraphs(session: Session, proposition: str, *, limit: int = DEFAULT_CANDIDATES) -> list[dict]:
    """Rank paragraphs across the whole corpus by BM25. Raw retrieval, before authority is weighed."""
    query = fts_query(proposition)
    if not query:
        return []
    rows = session.execute(
        sql_text(
            f"""
            SELECT paragraph_id, judgment_id, body, bm25({FTS_TABLE}) AS rank
            FROM {FTS_TABLE}
            WHERE {FTS_TABLE} MATCH :query
            ORDER BY rank
            LIMIT :limit
            """
        ),
        {"query": query, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def best_line(body: str, proposition: str) -> tuple[str | None, int | None, int | None]:
    """The sentence in a paragraph that carries most of the proposition's distinctive terms.

    This is the "where in the three hundred pages" answer. It is deliberately lexical: it points a
    reader at a line to read, and claims nothing about whether the line supports them.
    """
    wanted = set(tokenize(proposition))
    if not wanted:
        return None, None, None
    best: tuple[float, str, int] | None = None
    for sentence, offset in split_sentences(body):
        terms = set(tokenize(sentence))
        if not terms:
            continue
        overlap = len(wanted & terms)
        if not overlap:
            continue
        # Favour density over length: a long sentence should not win merely by containing more words.
        score = overlap + overlap / len(terms)
        if best is None or score > best[0]:
            best = (score, sentence, offset)
    if best is None:
        return None, None, None
    return best[1], best[2], best[2] + len(best[1])


def _authority_bonus(judgment: Judgment) -> float:
    """Standing, as a small addition to relevance. A larger bench binds a smaller one."""
    bonus = 0.0
    if judgment.bench_strength:
        bonus += BENCH_WEIGHT * min(judgment.bench_strength, 13)
    if judgment.decided_on:
        span = max(1, 2026 - RECENCY_FLOOR_YEAR)
        bonus += RECENCY_WEIGHT * ((judgment.decided_on.year - RECENCY_FLOOR_YEAR) / span)
    return bonus


def find_authorities(
    session: Session,
    proposition: str,
    *,
    top: int = DEFAULT_TOP,
    candidates: int = DEFAULT_CANDIDATES,
    court_voice_only: bool = True,
    one_per_judgment: bool = True,
) -> list[Authority]:
    """Search the corpus for paragraphs that could back a proposition, best first.

    `court_voice_only` is what separates this from a text search. A paragraph reciting counsel's
    argument matches a proposition's words as well as the holding does — better, sometimes, because
    an advocate states a rule more baldly than a court will. Offering one as authority would be
    handing a lawyer the very mistake the verifier exists to catch, so those are dropped here.
    """
    rows = search_paragraphs(session, proposition, limit=candidates)
    if not rows:
        return []

    judgments = {
        j.id: j
        for j in session.query(Judgment).filter(Judgment.id.in_({r["judgment_id"] for r in rows})).all()
    }
    labels = _paragraph_labels(session, [r["paragraph_id"] for r in rows])

    found: list[Authority] = []
    seen: set[str] = set()
    for row in rows:
        judgment = judgments.get(row["judgment_id"])
        if judgment is None:
            continue
        if one_per_judgment and judgment.id in seen:
            continue

        meta = labels.get(row["paragraph_id"], {})
        candidate = Candidate(
            seq=meta.get("seq", 0),
            printed_label=meta.get("printed_label"),
            score=0.0,
            matched_terms=[],
            body=row["body"],
            opinion_kind=meta.get("opinion_kind"),
            opinion_author=meta.get("opinion_author"),
        )
        voice = attribute_voice(candidate)
        if court_voice_only and not voice.is_the_court:
            continue

        # bm25() returns a negative number, better matches more negative. Flip it so bigger is better.
        relevance = -float(row["rank"])
        line, start, end = best_line(row["body"], proposition)
        found.append(
            Authority(
                judgment_id=judgment.id,
                canonical_key=judgment.canonical_key,
                title=judgment.title,
                citation=_preferred_citation(session, judgment.id),
                decided_on=judgment.decided_on.isoformat() if judgment.decided_on else None,
                bench_strength=judgment.bench_strength,
                paragraph_label=meta.get("printed_label"),
                paragraph_seq=meta.get("seq", 0),
                body=row["body"],
                relevance=round(relevance, 3),
                score=round(relevance + _authority_bonus(judgment), 3),
                voice=voice,
                line=line,
                line_start=start,
                line_end=end,
                matched_terms=sorted(set(tokenize(proposition)) & set(tokenize(row["body"]))),
            )
        )
        seen.add(judgment.id)

    found.sort(key=lambda a: -a.score)
    return found[:top]


def _paragraph_labels(session: Session, paragraph_ids: list[str]) -> dict[str, dict]:
    """Printed labels and opinion kinds for the retrieved paragraphs, in one query."""
    if not paragraph_ids:
        return {}
    statement = sql_text(
        """
        SELECT p.id, p.seq, p.printed_label, o.kind AS opinion_kind, o.author AS opinion_author
        FROM paragraph p
        LEFT JOIN opinion o ON o.id = p.opinion_id
        WHERE p.id IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))
    rows = session.execute(statement, {"ids": list(paragraph_ids)}).mappings().all()
    return {r["id"]: dict(r) for r in rows}


def _preferred_citation(session: Session, judgment_id: str) -> str | None:
    """The citation a lawyer would put in a brief. Reporter citations beat neutral ones in practice."""
    row = session.execute(
        sql_text(
            """
            SELECT citation_string, reporter FROM citation_alias
            WHERE judgment_id = :jid
            ORDER BY CASE reporter WHEN 'SCC' THEN 0 WHEN 'SCR' THEN 1 WHEN 'AIR' THEN 2 ELSE 3 END
            LIMIT 1
            """
        ),
        {"jid": judgment_id},
    ).first()
    return row[0] if row else None
