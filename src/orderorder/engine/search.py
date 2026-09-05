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
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from orderorder.db.models import Judgment
from orderorder.engine import embeddings
from orderorder.engine.citator import TreatmentReport, treatment_of
from orderorder.engine.lexical import reciprocal_rank_fusion, tokenize
from orderorder.engine.locator import Candidate
from orderorder.engine.sentences import split_sentences
from orderorder.engine.voice import VoiceVerdict, attribute_voice

FTS_TABLE = "paragraph_fts"
DEFAULT_CANDIDATES = 120
DEFAULT_TOP = 5

# Proximity retrieval. A run of five consecutive terms is long enough to be distinctive and short
# enough that a court restating the rule in nearly the same words still satisfies it; the window is
# wider than the run so the stopwords between them, which the index keeps and `tokenize` does not,
# have room. Several runs are taken across a long proposition and capped, because each is a query.
NEAR_TERMS = 5
NEAR_WINDOW = 12
MAX_NEAR_QUERIES = 6
NEAR_LIMIT = 40
# How many votes the dense ranking carries in the fusion. The lexical rankings agree with each
# other by construction, so counting them one apiece against a single dense vote is not neutrality.
DENSE_VOTES = 4
# Measured on the paraphrase query set, fusing the dense ranking at one vote and at several:
#   lexical only            case@1 33%   para@5 36%
#   + dense, one vote       case@1 34%   para@5 30%
#   + dense, three votes    case@1 33%   para@5 27%
#   + dense, eight votes    case@1 33%   para@5 25%
# Which is why `dense` defaults to off. See the note in `search_paragraphs`.
# Reciprocal rank fusion scores are around 0.016 at the top and fall slowly. Multiplied up, the
# spread across the first twenty results is a few points, which is where the standing bonus below
# was already pitched against BM25: enough to move an authority a place or two, never enough to
# lift an irrelevant one.
FUSION_SCALE = 1000.0

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
    court: str | None
    decided_on: str | None
    bench_strength: int | None
    paragraph_label: str | None
    paragraph_seq: int
    body: str
    relevance: float
    score: float
    voice: VoiceVerdict | None = None
    treatment: TreatmentReport | None = None
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


def near_queries(proposition: str) -> list[str]:
    """FTS5 proximity queries over runs of consecutive terms in the proposition.

    OR-ing the terms and ranking by BM25 asks which paragraph contains *many* of these words. That is
    the wrong question when the words came from a passage, because a long paragraph on the same
    subject can carry more of them than the one the passage is in. The right question is which
    paragraph has them *together*, and `NEAR` asks exactly that.

    Runs of a few consecutive terms rather than the whole proposition, because NEAR requires every
    term it names: a whole sentence would match nothing, and a run of five is short enough that a
    court restating a rule still satisfies it. Several runs across the proposition, fused, so no
    single one has to be the right one.
    """
    terms = [t for t in tokenize(proposition) if len(t) > 2]
    if len(terms) < NEAR_TERMS:
        return []
    starts = list(range(0, len(terms) - NEAR_TERMS + 1))
    if len(starts) > MAX_NEAR_QUERIES:
        step = len(starts) / MAX_NEAR_QUERIES
        starts = [starts[int(i * step)] for i in range(MAX_NEAR_QUERIES)]
    return [
        f"NEAR({' '.join(chr(34) + t + chr(34) for t in terms[s : s + NEAR_TERMS])}, {NEAR_WINDOW})"
        for s in starts
    ]


def _match(session: Session, query: str, limit: int) -> list[dict]:
    rows = (
        session.execute(
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
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def _paragraph_rows(session: Session, paragraph_ids: list[str]) -> list[dict]:
    """Bodies for paragraphs the dense ranking found and the lexical ones never saw."""
    if not paragraph_ids:
        return []
    statement = sql_text(
        """
        SELECT p.id AS paragraph_id, v.judgment_id AS judgment_id, p.body AS body, 0.0 AS rank
        FROM paragraph p
        JOIN judgment_text_version v ON v.id = p.text_version_id
        WHERE p.id IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))
    return [dict(r) for r in session.execute(statement, {"ids": paragraph_ids}).mappings().all()]


def search_paragraphs(
    session: Session, proposition: str, *, limit: int = DEFAULT_CANDIDATES, dense: bool = False
) -> list[dict]:
    """Rank paragraphs across the corpus, fusing how many of the words match with how close they sit.

    Raw retrieval, before authority is weighed. Three rankers, fused: BM25 over the OR of the terms,
    which finds paragraphs about the same subject; proximity, which finds the paragraph the words came
    from; and, where a vector store has been built, nearest neighbours in meaning, which is the only
    one of the three that can answer a paraphrase. None is reliable alone, they fail in different
    directions, and reciprocal rank fusion needs no calibration between them.
    """
    query = fts_query(proposition)
    if not query:
        return []

    by_words = _match(session, query, limit)
    rankings: list[list[str]] = [[row["paragraph_id"] for row in by_words]]
    rows = {row["paragraph_id"]: row for row in by_words}

    for near in near_queries(proposition):
        try:
            close = _match(session, near, NEAR_LIMIT)
        except OperationalError:
            # A term FTS5 cannot parse inside NEAR is not worth failing the search over; the word
            # ranking still stands on its own.
            continue
        rankings.append([row["paragraph_id"] for row in close])
        for row in close:
            rows.setdefault(row["paragraph_id"], row)

    # And meaning, if asked for — but it is off by default, and the measurement is why.
    #
    # A dense ranking is the only one of the three that could answer a paraphrase, since the other two
    # match words and a paraphrase shares none. Over this corpus, with the encoders that will run on a
    # CPU, it does not. Fused at one vote it takes paragraph recall on the paraphrase set from 36% to
    # 30%, and weighting it up makes that monotonically worse: 27% at three votes, 25% at eight. It is
    # adding noise to rankings that were carrying signal.
    #
    # The reason is scale rather than the fusion. Asked to pick the right paragraph out of a field of
    # 400, the static encoder gets it first 24 times in 40 — and a small sentence transformer, which
    # would cost 8.3 hours to run over this corpus against 4 minutes, gets it 23. Both are useless at
    # 391,356, because a thousand times more candidates means a thousand more chances to be nearer by
    # accident, and neither is discriminating enough to survive that.
    #
    # So the seam stays, off, and `orderorder embed --model ...` with a strong encoder on a GPU is the
    # experiment worth running next. What is *not* worth running is the same experiment with a bigger
    # CPU model, and that is the thing the discrimination test tells you before you spend the night.
    if dense:
        nearest = embeddings.search(proposition, top=limit)
        if nearest:
            ranked = [paragraph_id for paragraph_id, _score in nearest]
            rankings.extend([ranked] * DENSE_VOTES)
            for row in _paragraph_rows(session, [pid for pid in ranked if pid not in rows]):
                rows.setdefault(row["paragraph_id"], row)

    # The fused position is the ranking, so it has to be what `relevance` reports: leaving the BM25
    # score on the row would have the caller sort by the ranker the fusion was meant to correct, and
    # the proximity half would change nothing at all. Scores are divided by the number of rankers so
    # that a long proposition, which raises more proximity queries, does not come out scored higher
    # than a short one — the ranking within a search is unaffected either way, but the standing bonus
    # added downstream is a fixed size and has to mean the same thing in both.
    fused = reciprocal_rank_fusion(rankings)
    ranked: list[dict] = []
    for paragraph_id, score in fused[:limit]:
        row = dict(rows[paragraph_id])
        row["relevance"] = FUSION_SCALE * score / len(rankings)
        ranked.append(row)
    return ranked


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
    check_treatment: bool = True,
    dense: bool = False,
) -> list[Authority]:
    """Search the corpus for paragraphs that could back a proposition, best first.

    `court_voice_only` is what separates this from a text search. A paragraph reciting counsel's
    argument matches a proposition's words as well as the holding does — better, sometimes, because
    an advocate states a rule more baldly than a court will. Offering one as authority would be
    handing a lawyer the very mistake the verifier exists to catch, so those are dropped here.
    """
    rows = search_paragraphs(session, proposition, limit=candidates, dense=dense)
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

        relevance = float(row["relevance"])
        line, start, end = best_line(row["body"], proposition)
        found.append(
            Authority(
                judgment_id=judgment.id,
                canonical_key=judgment.canonical_key,
                title=judgment.title,
                citation=_preferred_citation(session, judgment.id),
                court=judgment.court,
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
    found = found[:top]

    # Whether an authority is still good law is asked only of the handful being offered, because it is
    # a query per judgment and the answer changes the ranking: an overruled case belongs below a sound
    # one however well its words match, and must never be handed over without the warning.
    if check_treatment:
        for authority in found:
            authority.treatment = treatment_of(session, authority.judgment_id)
        found.sort(key=lambda a: (a.treatment.is_doubtful if a.treatment else False, -a.score))
    return found


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
