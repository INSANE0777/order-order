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
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from orderorder.db.models import CitationAlias, CitationEdge, Judgment, JudgmentTextVersion, Paragraph

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


def _fts_phrase(words: list[str]) -> str:
    return '"' + " ".join(word.replace('"', "") for word in words) + '"'


def _window(body: str) -> list[str] | None:
    """Eight consecutive words from the middle of a paragraph, where the holding usually sits."""
    tokens = WORD.findall(body)
    if len(tokens) < SHINGLE_WORDS:
        return None
    start = max(0, (len(tokens) - SHINGLE_WORDS) // 2)
    return [token.lower() for token in tokens[start : start + SHINGLE_WORDS]]


def _search_bodies(session: Session, judgment_id: str, phrase: str, limit: int = 5) -> list[str]:
    """Paragraph bodies of one judgment that contain the phrase, via the full-text index."""
    rows = session.execute(
        sql_text(
            "SELECT body FROM paragraph_fts WHERE paragraph_fts MATCH :q AND judgment_id = :j LIMIT :n"
        ),
        {"q": phrase, "j": judgment_id, "n": limit},
    ).all()
    return [row[0] for row in rows]


def _decade_counts(session: Session) -> dict[int, int]:
    rows = session.execute(
        sql_text(
            "SELECT (CAST(substr(decided_on, 1, 4) AS INTEGER) / 10) * 10 AS decade, COUNT(*) "
            "FROM judgment WHERE decided_on IS NOT NULL GROUP BY decade"
        )
    ).all()
    return {int(decade): int(count) for decade, count in rows}


def sample_base_items(
    session: Session,
    *,
    per_decade: int = 25,
    seed: int = 20261027,
    max_per_judgment: int = 2,
    max_edges: int = 20000,
    progress=None,
) -> tuple[list[BaseItem], dict[str, Any]]:
    """Draw real citations that reproduce a paragraph of the judgment they cite.

    Each edge costs a handful of full-text probes rather than a paragraph-by-paragraph
    comparison: eight words from the middle of a cited paragraph are searched inside the citing
    judgment, and only a hit that really contains them becomes an item. The walk stops as soon as
    every decade holds three times its quota, so the work is bounded by the quota, not the corpus.
    """
    counts: Counter[str] = Counter()
    present = _decade_counts(session)
    target = {decade: per_decade * 3 for decade, count in present.items() if count >= per_decade}
    if not target:
        # A corpus too small to fill one decade still owes each decade it has a shot at.
        target = {decade: max(count, 1) for decade, count in present.items()}
    counts["decades_targeted"] = len(target)

    edges = session.execute(
        select(
            CitationEdge.id,
            CitationEdge.citing_id,
            CitationEdge.cited_id,
            CitationEdge.cited_alias,
        )
        .where(CitationEdge.cited_id.is_not(None))
        .order_by(CitationEdge.id)
        .execution_options(yield_per=500)
    )

    candidates: list[BaseItem] = []
    pool: Counter[int] = Counter()
    per_citing: Counter[str] = Counter()
    examined = 0
    for _edge_id, citing_id, cited_id, alias in edges:
        if examined >= max_edges or (target and all(pool[d] >= n for d, n in target.items())):
            break
        examined += 1
        if progress is not None and examined % 1000 == 0:
            progress(examined, len(candidates), dict(pool))
        counts["edges_seen"] += 1
        citing = session.get(Judgment, citing_id)
        cited = session.get(Judgment, cited_id)
        if citing is None or cited is None:
            counts["missing_judgment"] += 1
            continue
        if cited.decided_on is None:
            counts["no_date"] += 1
            continue
        decade = (cited.decided_on.year // 10) * 10
        if decade not in target or pool[decade] >= target[decade]:
            counts["decade_full"] += 1
            continue
        if per_citing[citing.id] >= max_per_judgment:
            counts["judgment_cap"] += 1
            continue

        target_version, target_paragraphs = _paragraphs(session, cited.id)
        if not target_paragraphs:
            counts["no_text"] += 1
            continue
        if target_version.ocr_derived:
            counts["ocr"] += 1
            continue

        match = None
        for paragraph in target_paragraphs[:60]:
            window = _window(paragraph.body)
            if window is None or len(paragraph.body) < MIN_CLAIM_CHARS:
                continue
            for body in _search_bodies(session, citing.id, _fts_phrase(window)):
                detail = _shared_run_detail(body, paragraph.body)
                if detail is None:
                    continue
                if match is None or detail[4] > match[0]:
                    match = (
                        detail[4],
                        body,
                        paragraph,
                        detail[0],
                        detail[1],
                        detail[2],
                        detail[3],
                    )
        if match is None:
            counts["no_run"] += 1
            continue

        words, claim_body, target_paragraph, cs, _, ts, te = match
        if words < MIN_QUOTE_WORDS:
            counts["short_run"] += 1
            continue

        start, end = sentence_around(claim_body, cs)
        claim = claim_body[start:end].strip()
        if not (MIN_CLAIM_CHARS <= len(claim) <= MAX_CLAIM_CHARS):
            counts["claim_length"] += 1
            continue
        if len(TWO_CASES.findall(claim)) >= 2:
            counts["multi_citation"] += 1
            continue

        candidates.append(
            BaseItem(
                item_id=_item_id(
                    citing.canonical_key,
                    f"{citing.id}:{cs}",
                    cited.canonical_key,
                    target_paragraph.id,
                ),
                citing_key=citing.canonical_key,
                citing_paragraph_id=f"{citing.id}:{cs}",
                cited_key=cited.canonical_key,
                cited_judgment_id=cited.id,
                cited_paragraph_id=target_paragraph.id,
                cited_label=target_paragraph.printed_label,
                citation_raw=alias or cited.neutral_citation or cited.canonical_key,
                claim=claim,
                quote=target_paragraph.body[ts:te],
                quote_start=ts,
                quote_end=te,
                quote_words=words,
                decade=decade,
                bench_strength=cited.bench_strength,
                cited_paragraph_count=len(target_paragraphs),
            )
        )
        per_citing[citing.id] += 1
        pool[decade] += 1

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
        "max_edges": max_edges,
        "shingle_words": SHINGLE_WORDS,
        "min_quote_words": MIN_QUOTE_WORDS,
        "counts": dict(counts),
        "decades": dict(sorted(taken.items())),
        "items_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }
    return chosen, manifest


# --- the paraphrase prompt --------------------------------------------------------------------

PARAPHRASE_PROMPT = """Rewrite the sentence below in your own words, as an advocate would state the
same proposition in a brief.

Rules:
- Keep the same legal proposition and the same qualifiers.
- Do not copy a run of eight or more consecutive words from it.
- Do not name the case or any party.
- Return one sentence, between 40 and 400 characters.

Sentence:
{claim}

Words that must not be copied verbatim:
{quote}
"""


class ParaphraseOut(BaseModel):
    """The model's restatement."""

    text: str = Field(description="One sentence restating the proposition in different words.")


@dataclass(frozen=True)
class Paraphrase:
    item_id: str
    text: str
    longest_shared_run: int


def longest_shared_run(text: str, source: str) -> int:
    """How many consecutive words `text` shares with `source`, at its longest."""
    detail = _shared_run_detail(text, source, min_words=1)
    return detail[4] if detail else 0


def make_paraphrases(
    items: list[BaseItem],
    model,
    *,
    reject_log: list[dict] | None = None,
) -> list[Paraphrase]:
    """Restate each claim without copying the judgment. One retry, then a recorded rejection."""
    reject_log = reject_log if reject_log is not None else []
    out: list[Paraphrase] = []
    for item in items:
        reason, detail = "error", ""
        for _ in range(2):
            try:
                answer = model.invoke(PARAPHRASE_PROMPT.format(claim=item.claim, quote=item.quote))
                text = (getattr(answer, "text", "") or "").strip()
            except Exception as exc:  # noqa: BLE001 - a failed rewrite is data, not a crash
                reason, detail = "error", f"{type(exc).__name__}: {exc}"
                continue
            shared = longest_shared_run(text, item.quote)
            if not (MIN_CLAIM_CHARS <= len(text) <= MAX_CLAIM_CHARS):
                reason, detail = "length", f"{len(text)} characters"
            elif shared >= SHINGLE_WORDS:
                reason, detail = "overlap", f"{shared} shared words"
            elif len(TWO_CASES.findall(text)) >= 2:
                reason, detail = "multi_citation", text[:80]
            else:
                out.append(Paraphrase(item_id=item.item_id, text=text, longest_shared_run=shared))
                reason = ""
                break
        if reason:
            reject_log.append({"item_id": item.item_id, "reason": reason, "detail": detail})
    return out


# --- arms -------------------------------------------------------------------------------------

POINTER_MODES = frozenset({1, 2, 3, 4, 12})
PARAPHRASE_ARMS = frozenset(
    {"paraphrase_clean", "paraphrase_wrong_paragraph", "paraphrase_wrong_judgment"}
)


@dataclass(frozen=True)
class ArmItem:
    arm: str
    item_id: str
    claim: str
    citation: str
    expected_modes: tuple[int, ...]
    distractor_key: str | None = None
    distractor_rank: int | None = None


def _citation_for(session: Session, judgment: Judgment, label: str | None) -> str:
    alias = (
        session.execute(select(CitationAlias).where(CitationAlias.judgment_id == judgment.id))
        .scalars()
        .first()
    )
    base = (
        alias.citation_string
        if alias is not None
        else (judgment.neutral_citation or judgment.canonical_key)
    )
    return f"{base}, para {label}" if label else base


def _wrong_paragraph(
    target_paragraphs: list[Paragraph], item: BaseItem, rng: random.Random
) -> Paragraph | None:
    """A paragraph far enough away that the quote cannot be there, chosen deterministically."""
    quote = " ".join(WORD.findall(item.quote.lower()))
    target_seq = next((p.seq for p in target_paragraphs if p.id == item.cited_paragraph_id), None)
    if target_seq is None:
        return None
    eligible = [
        p
        for p in target_paragraphs
        if abs(p.seq - target_seq) >= 2 and quote not in " ".join(WORD.findall(p.body.lower()))
    ]
    return rng.choice(eligible) if eligible else None


def _wrong_judgment(
    session: Session, item: BaseItem, rng: random.Random
) -> Judgment | None:
    """Another judgment the same brief cites, from the same decade, that does not contain the quote."""
    citing = session.execute(
        select(Judgment).where(Judgment.canonical_key == item.citing_key)
    ).scalars().first()
    if citing is None:
        return None
    siblings = (
        session.execute(
            select(Judgment)
            .join(CitationEdge, CitationEdge.cited_id == Judgment.id)
            .where(CitationEdge.citing_id == citing.id)
            .order_by(Judgment.canonical_key)
        )
        .scalars()
        .all()
    )
    quote = " ".join(WORD.findall(item.quote.lower()))
    eligible = []
    for judgment in siblings:
        if judgment.canonical_key == item.cited_key or judgment.decided_on is None:
            continue
        if (judgment.decided_on.year // 10) * 10 != item.decade:
            continue
        _, paragraphs = _paragraphs(session, judgment.id)
        if not paragraphs:
            continue
        if any(quote in " ".join(WORD.findall(p.body.lower())) for p in paragraphs):
            continue
        eligible.append(judgment)
    return rng.choice(eligible) if eligible else None


def build_arms(
    session: Session,
    items: list[BaseItem],
    paraphrases: list[Paraphrase],
    *,
    seed: int = 20261027,
) -> list[ArmItem]:
    """Six arms per item that has a paraphrase, three otherwise."""
    by_item = {p.item_id: p for p in paraphrases}
    arms: list[ArmItem] = []
    for item in items:
        rng = random.Random(f"{seed}:{item.item_id}")
        cited = session.get(Judgment, item.cited_judgment_id)
        if cited is None:
            continue
        _, target_paragraphs = _paragraphs(session, cited.id)
        clean_citation = _citation_for(session, cited, item.cited_label)

        for family, claim in (
            ("verbatim", item.claim),
            ("paraphrase", by_item[item.item_id].text if item.item_id in by_item else None),
        ):
            if claim is None:
                continue
            arms.append(
                ArmItem(
                    arm=f"{family}_clean",
                    item_id=item.item_id,
                    claim=claim,
                    citation=clean_citation,
                    expected_modes=(),
                )
            )
            neighbor = _wrong_paragraph(target_paragraphs, item, rng)
            if neighbor is not None:
                arms.append(
                    ArmItem(
                        arm=f"{family}_wrong_paragraph",
                        item_id=item.item_id,
                        claim=claim,
                        citation=_citation_for(session, cited, neighbor.printed_label),
                        expected_modes=(12, 4),
                        distractor_key=neighbor.id,
                    )
                )
            other = _wrong_judgment(session, item, rng)
            if other is not None:
                arms.append(
                    ArmItem(
                        arm=f"{family}_wrong_judgment",
                        item_id=item.item_id,
                        claim=claim,
                        citation=_citation_for(session, other, None),
                        expected_modes=(2, 4),
                        distractor_key=other.canonical_key,
                    )
                )
    arms.sort(key=lambda a: (a.item_id, a.arm))
    return arms


# --- scoring ----------------------------------------------------------------------------------


def _interval(k: int, n: int) -> dict[str, float | int]:
    point, low, high = wilson(k, n)
    return {"point": point, "low": low, "high": high, "n": n}


def wilson(k: int, n: int, *, z: float = 1.96) -> tuple[float, float, float]:
    """Point estimate and Wilson score interval. Never reports certainty at n = 100%."""
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denominator
    return p, max(0.0, centre - half), min(1.0, centre + half)


def classify(arm: ArmItem, row: dict) -> str:
    """One of error, wrong_flag, caught, pass, abstain, not_caught — in that precedence."""
    if row.get("error"):
        return "error"
    if row.get("node_error"):
        return "abstain"
    findings = row.get("findings") or []
    modes = {finding.get("mode") for finding in findings}
    pointer = bool(modes & POINTER_MODES)

    if arm.arm.endswith("clean"):
        if row.get("existence") == "not_found":
            return "wrong_flag"
        if pointer:
            return "wrong_flag"
        if row.get("needs_review") and not findings:
            return "abstain"
        return "pass"
    if pointer:
        return "caught"
    if row.get("needs_review"):
        return "abstain"
    return "not_caught"


def summarise(arms: list[ArmItem], rows: list[dict]) -> dict:
    """Per-arm outcomes with intervals. No pooled rate, and nothing below n = 10 is published."""
    outcome_by_key = {(row.get("arm"), row.get("item_id")): classify(arm, row) for arm in arms for row in rows if row.get("arm") == arm.arm and row.get("item_id") == arm.item_id}
    by_arm: dict[str, list[str]] = {}
    for arm in arms:
        outcome = outcome_by_key.get((arm.arm, arm.item_id))
        if outcome is not None:
            by_arm.setdefault(arm.arm, []).append(outcome)

    report: dict[str, dict] = {}
    for arm_name, outcomes in by_arm.items():
        counts = Counter(outcomes)
        decided_n = counts["caught"] + counts["not_caught"]
        all_n = decided_n + counts["abstain"] + counts["error"]
        clean_n = counts["pass"] + counts["wrong_flag"]
        cell: dict = {
            "constructed": len(outcomes),
            "intended": sum(1 for a in arms if a.arm == arm_name),
            **{key: counts[key] for key in ("pass", "wrong_flag", "caught", "not_caught", "abstain", "error")},
            "suppressed": len(outcomes) < 10,
        }
        if arm_name.endswith("clean"):
            cell["false_alarm"] = _interval(counts["wrong_flag"], clean_n)
        else:
            cell["decided_catch"] = _interval(counts["caught"], decided_n)
            cell["all_in_catch"] = _interval(counts["caught"], all_n)
        report[arm_name] = cell
    return {"arms": report, "rows": len(rows)}


# --- runner -----------------------------------------------------------------------------------

CACHE_KEYS = ("arm", "item_id")


def run_arms(
    arms: list[ArmItem],
    *,
    verify_fn,
    cache_path,
    workers: int = 1,
    on_result=None,
) -> list[dict]:
    """Run every arm once, resuming from the cache and never re-billing a completed item."""
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    done: dict[tuple[str, str], dict] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not row.get("error"):
                done[(row["arm"], row["item_id"])] = row

    pending = [arm for arm in arms if (arm.arm, arm.item_id) not in done]
    lock = threading.Lock()

    def work(arm: ArmItem) -> dict:
        try:
            row = dict(verify_fn(arm))
        except Exception as exc:  # noqa: BLE001 - one failed item must not abort the batch
            row = {"error": f"{type(exc).__name__}: {exc}"}
        row["arm"] = arm.arm
        row["item_id"] = arm.item_id
        with lock, cache_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        if on_result is not None:
            on_result(row)
        return row

    if workers > 1 and len(pending) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fresh = list(pool.map(work, pending))
    else:
        fresh = [work(arm) for arm in pending]

    rows = list(done.values()) + fresh
    rows.sort(key=lambda row: (row["arm"], row["item_id"]))
    return rows


# --- report -----------------------------------------------------------------------------------


def format_perturb(summary: dict) -> list[str]:
    """The study as a table of lines, in the shape the other evaluators print."""
    lines = [f"{summary.get('rows', 0)} arm results", ""]
    for arm in sorted(summary["arms"]):
        cell = summary["arms"][arm]
        lines.append(f"{arm:<32} n={cell['constructed']}")
        lines.append(
            f"  pass {cell['pass']} · wrong flag {cell['wrong_flag']} · caught {cell['caught']}"
            f" · not caught {cell['not_caught']} · abstain {cell['abstain']} · error {cell['error']}"
        )
        if cell.get("suppressed"):
            lines.append("  suppressed: fewer than ten items")
        elif arm.endswith("clean"):
            rate = cell["false_alarm"]
            lines.append(
                f"  false alarms {rate['point']:.0%} [{rate['low']:.0%}-{rate['high']:.0%}]"
                f"  n={rate['n']}"
            )
        else:
            decided = cell["decided_catch"]
            all_in = cell["all_in_catch"]
            lines.append(
                f"  decided catch {decided['point']:.0%}"
                f" [{decided['low']:.0%}-{decided['high']:.0%}]  n={decided['n']}"
            )
            lines.append(f"  all-in catch {all_in['point']:.0%}  n={all_in['n']}")
        lines.append("")
    return lines
