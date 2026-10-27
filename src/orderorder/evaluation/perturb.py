"""Real citations broken in one known way, and what the engine made of them.

The study lives here rather than in the evaluation harness because its unit is a citation
occurrence, not a planted gold item. Sampling finds a sentence in one judgment that reproduces a
run of words from a paragraph of another; that pair is a citation whose claim really does come from
the cited paragraph, so a broken version of it has ground truth by construction.

Nothing in this module changes how a brief is verified. `run_arms` calls an injected `verify_fn`,
which the CLI supplies and the tests stub.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.db.models import CitationEdge, Judgment, JudgmentTextVersion, Paragraph

# Eight consecutive words is long enough that a shared run means the same sentence, not the same
# subject. The quote must be longer still before it is worth calling a quotation.
SHINGLE_WORDS = 8
MIN_QUOTE_WORDS = 12
MIN_CLAIM_CHARS = 40
MAX_CLAIM_CHARS = 400

WORD = re.compile(r"[A-Za-z0-9']+")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
TWO_CASES = re.compile(r"\bv\.\s", re.IGNORECASE)


@dataclass(frozen=True)
class BaseItem:
    """One real citation: a sentence of the citing judgment and the paragraph it reproduces."""

    item_id: str
    citing_key: str
    citing_paragraph_id: str
    cited_key: str
    cited_judgment_id: str
    cited_paragraph_id: str
    cited_label: str | None
    citation_raw: str
    claim: str
    quote: str
    quote_start: int
    quote_end: int
    quote_words: int
    decade: int
    bench_strength: int | None
    cited_paragraph_count: int


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0).lower(), m.start(), m.end()) for m in WORD.finditer(text)]


def _shared_run_detail(
    citing_body: str, cited_body: str, *, min_words: int = SHINGLE_WORDS
) -> tuple[int, int, int, int, int] | None:
    """(citing_start, citing_end, cited_start, cited_end, words) for the longest shared run."""
    citing, cited = _tokens(citing_body), _tokens(cited_body)
    if len(citing) < min_words or len(cited) < min_words:
        return None

    grams: dict[tuple[str, ...], list[int]] = {}
    for i in range(len(cited) - min_words + 1):
        key = tuple(word for word, _, _ in cited[i : i + min_words])
        grams.setdefault(key, []).append(i)

    best: tuple[int, int, int, int, int] | None = None
    for j in range(len(citing) - min_words + 1):
        key = tuple(word for word, _, _ in citing[j : j + min_words])
        for i in grams.get(key, ()):
            left = 0
            while i - left > 0 and j - left > 0 and cited[i - left - 1][0] == citing[j - left - 1][0]:
                left += 1
            right = 0
            while (
                i + min_words + right < len(cited)
                and j + min_words + right < len(citing)
                and cited[i + min_words + right][0] == citing[j + min_words + right][0]
            ):
                right += 1
            words = min_words + left + right
            if best is None or words > best[4]:
                cs, ce = citing[j - left][1], citing[j + min_words + right - 1][2]
                ts, te = cited[i - left][1], cited[i + min_words + right - 1][2]
                best = (cs, ce, ts, te, words)
    return best


def shared_run(
    citing_body: str, cited_body: str, *, min_words: int = SHINGLE_WORDS
) -> tuple[str, int, int] | None:
    """The longest run of words the two bodies share: its text in the cited body, offset, length."""
    detail = _shared_run_detail(citing_body, cited_body, min_words=min_words)
    if detail is None:
        return None
    _, _, start, end, words = detail
    return cited_body[start:end], start, words


def sentence_around(text: str, offset: int) -> tuple[int, int]:
    """Character span of the sentence containing `offset`, with breaks on . ! ?"""
    starts = [0] + [m.end() for m in SENTENCE_BREAK.finditer(text)]
    ends = [m.start() for m in SENTENCE_BREAK.finditer(text)] + [len(text)]
    start = max((s for s in starts if s <= offset), default=0)
    end = min((e for e in ends if e >= offset), default=len(text))
    return start, end


def _text_version(session: Session, judgment_id: str) -> JudgmentTextVersion | None:
    rows = session.execute(
        select(JudgmentTextVersion)
        .where(JudgmentTextVersion.judgment_id == judgment_id)
        .order_by(JudgmentTextVersion.preferred.desc(), JudgmentTextVersion.version_key)
    ).scalars()
    return rows.first()


def _paragraphs(session: Session, judgment_id: str) -> tuple[JudgmentTextVersion, list[Paragraph]]:
    version = _text_version(session, judgment_id)
    if version is None:
        return None, []
    rows = session.execute(
        select(Paragraph).where(Paragraph.text_version_id == version.id).order_by(Paragraph.seq)
    ).scalars()
    return version, list(rows)


def _item_id(citing_key: str, citing_para: str, cited_key: str, cited_para: str) -> str:
    raw = f"{citing_key}|{citing_para}|{cited_key}|{cited_para}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _match(claim_paragraphs: list[Paragraph], target_paragraphs: list[Paragraph]):
    """The longest shared run between any paragraph of the citing and cited judgments."""
    best = None
    for claim_para in claim_paragraphs:
        for target_para in target_paragraphs:
            detail = _shared_run_detail(claim_para.body, target_para.body)
            if detail is None:
                continue
            cs, ce, ts, te, words = detail
            if best is None or words > best[0]:
                best = (words, claim_para, target_para, cs, ce, ts, te)
    return best


def sample_base_items(
    session: Session,
    *,
    per_decade: int = 25,
    seed: int = 20261027,
    max_per_judgment: int = 2,
) -> tuple[list[BaseItem], dict[str, Any]]:
    """Draw real citations that reproduce a paragraph of the judgment they cite.

    Deterministic: the candidate list is ordered before the seeded shuffle, so the same corpus and
    seed always produce the same items in the same order.
    """
    counts: Counter[str] = Counter()
    edges = (
        session.execute(
            select(CitationEdge)
            .where(CitationEdge.cited_id.is_not(None))
            .order_by(CitationEdge.id)
        )
        .scalars()
        .all()
    )

    candidates: list[BaseItem] = []
    per_citing: Counter[str] = Counter()
    for edge in edges:
        counts["edges_seen"] += 1
        citing = session.get(Judgment, edge.citing_id)
        cited = session.get(Judgment, edge.cited_id)
        if citing is None or cited is None:
            counts["missing_judgment"] += 1
            continue
        if per_citing[citing.id] >= max_per_judgment:
            counts["judgment_cap"] += 1
            continue
        if cited.decided_on is None:
            counts["no_date"] += 1
            continue

        claim_version, claim_paragraphs = _paragraphs(session, citing.id)
        target_version, target_paragraphs = _paragraphs(session, cited.id)
        if not claim_paragraphs or not target_paragraphs:
            counts["no_text"] += 1
            continue
        if target_version.ocr_derived or claim_version.ocr_derived:
            counts["ocr"] += 1
            continue

        match = _match(claim_paragraphs, target_paragraphs)
        if match is None:
            counts["no_run"] += 1
            continue
        words, claim_para, target_para, cs, _, ts, te = match
        if words < MIN_QUOTE_WORDS:
            counts["short_run"] += 1
            continue

        start, end = sentence_around(claim_para.body, cs)
        claim = claim_para.body[start:end].strip()
        if not (MIN_CLAIM_CHARS <= len(claim) <= MAX_CLAIM_CHARS):
            counts["claim_length"] += 1
            continue
        if len(TWO_CASES.findall(claim)) >= 2:
            counts["multi_citation"] += 1
            continue

        candidates.append(
            BaseItem(
                item_id=_item_id(citing.canonical_key, claim_para.id, cited.canonical_key, target_para.id),
                citing_key=citing.canonical_key,
                citing_paragraph_id=claim_para.id,
                cited_key=cited.canonical_key,
                cited_judgment_id=cited.id,
                cited_paragraph_id=target_para.id,
                cited_label=target_para.printed_label,
                citation_raw=edge.cited_alias or cited.neutral_citation or cited.canonical_key,
                claim=claim,
                quote=target_para.body[ts:te],
                quote_start=ts,
                quote_end=te,
                quote_words=words,
                decade=(cited.decided_on.year // 10) * 10,
                bench_strength=cited.bench_strength,
                cited_paragraph_count=len(target_paragraphs),
            )
        )
        per_citing[citing.id] += 1

    ordered = sorted(candidates, key=lambda item: (item.decade, item.item_id))
    random.Random(seed).shuffle(ordered)

    chosen: list[BaseItem] = []
    taken: Counter[int] = Counter()
    for item in ordered:
        if taken[item.decade] >= per_decade:
            counts["decade_quota"] += 1
            continue
        taken[item.decade] += 1
        chosen.append(item)
    chosen.sort(key=lambda item: (item.decade, item.item_id))

    counts["kept"] = len(chosen)
    payload = json.dumps([asdict(item) for item in chosen], sort_keys=True, default=str)
    manifest = {
        "seed": seed,
        "per_decade": per_decade,
        "max_per_judgment": max_per_judgment,
        "shingle_words": SHINGLE_WORDS,
        "min_quote_words": MIN_QUOTE_WORDS,
        "counts": dict(counts),
        "decades": dict(sorted(taken.items())),
        "items_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    return chosen, manifest
