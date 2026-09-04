"""Learn the reporter citations the open data does not carry.

The AWS Open Data metadata gives each judgment two citations: its neutral citation (`2019 INSC 770`)
and its Supreme Court Reports citation (`[2019] 9 S.C.R. 593`). Practice runs on neither. Measured over
150 judgments of the corpus, of 1,504 citations they make to each other:

    SCC          957   64%
    SCC OnLine   229   15%
    AIR          111    7%
    SCR          100    7%
    INSC          57    4%

So an alias index built from the metadata alone resolves 2.8% of the citations judgments actually
make, and — worse — a brief citing a real case by its SCC number resolves to nothing and is reported
as a phantom. That is the most damaging mistake this product could make: an advocate told a sound
citation is fabricated.

The corpus can teach us the missing numbers. When a judgment writes

    Kasturi v. Iyyamperumal, (2005) 6 SCC 733

it is asserting that the case with those parties carries that citation. Match the parties against the
titles the corpus holds and the SCC number can be attached to the judgment it belongs to. That is
inference, not data, so three rules keep it honest:

  * **A high bar, and a clear winner.** The title match must clear a score floor and beat the
    runner-up by a margin, and the citation's year must sit within a year of the decision, because a
    case decided in December is reported in the next year's volume.
  * **Corroboration or near-certainty.** A near-perfect single match is accepted; anything less needs
    two different judgments to have said the same thing independently.
  * **Conflicts are discarded, not resolved.** If two judgments attach the same citation to different
    cases, one of them is wrong and there is no way to tell which, so neither is recorded.

Learned aliases are stored with `source="inferred"`, and the resolver says so when a citation resolves
through one, because a verdict that rests on an inference should say that it does.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process, utils
from sqlalchemy import select
from sqlalchemy.orm import Session

from orderorder.citations.grammar import extract_citations
from orderorder.db.models import CitationAlias, Judgment, JudgmentTextVersion, Paragraph

INFERRED = "inferred"
PAIRED = "paired"

# Two citations printed together, separated by nothing but punctuation, are the same case in two
# reporters. The Reports do this constantly in footnotes ("2007 INSC 496 : (2007) 6 SCC 162") and SCC
# does it in brackets after a case name ("(2021) 12 SCC 20 : 2021 SCC OnLine SC 704"). Where one of the
# pair is a citation the corpus already knows, the other is an alias for the same judgment — and that
# is the judgment's own word for it, not a guess, which makes it worth more than any fuzzy match.
PAIR_SEPARATOR = re.compile(r"^[\s:;=,]{1,4}$")

# The title match must clear this to count at all.
LEARN_SCORE = 92.0
# ... and beat the runner-up by this much, or the parties are too alike to tell apart.
LEARN_MARGIN = 6.0
# A match this good is accepted on one sighting; anything less needs two judgments to agree.
CONFIDENT_SCORE = 96.0
SIGHTINGS_REQUIRED = 2
# Party names shorter than this carry too little to match on ("State of U.P.").
MIN_PARTY_CHARS = 12


@dataclass
class Sighting:
    """One judgment asserting that a citation belongs to a case with these parties."""

    normalized: str
    citation_string: str
    reporter: str
    judgment_id: str
    score: float
    citing_id: str


@dataclass
class LearnStats:
    judgments_read: int = 0
    citations_seen: int = 0
    already_known: int = 0
    no_parties: int = 0
    no_match: int = 0
    sightings: int = 0
    paired: int = 0
    accepted: int = 0
    rejected_conflict: int = 0
    rejected_uncorroborated: int = 0
    by_reporter: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, int]:
        return {
            "judgments_read": self.judgments_read,
            "citations_seen": self.citations_seen,
            "already_known": self.already_known,
            "sightings": self.sightings,
            "paired": self.paired,
            "accepted": self.accepted,
            "rejected_conflict": self.rejected_conflict,
            "rejected_uncorroborated": self.rejected_uncorroborated,
        }


@dataclass
class TitleIndex:
    """Judgment titles, grouped by decision year, for repeated fuzzy matching.

    Built once. A per-citation database query would make this a day's work rather than a quarter of an
    hour, and the year narrowing is what keeps each match to a thousand candidates instead of ten.
    """

    by_year: dict[int, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))
    _windows: dict[int, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def build(cls, session: Session) -> TitleIndex:
        index = cls()
        rows = session.execute(
            select(Judgment.id, Judgment.title, Judgment.decided_on).where(Judgment.decided_on.is_not(None))
        ).all()
        for judgment_id, title, decided_on in rows:
            index.by_year[decided_on.year][judgment_id] = title or ""
        return index

    def window(self, year: int) -> dict[str, str]:
        """Titles from the year of the citation and the years either side of it.

        Cached per year. Merging three years of titles is a thousand dictionary inserts, and the corpus
        makes ninety thousand citations; doing it afresh each time is most of the run.
        """
        cached = self._windows.get(year)
        if cached is not None:
            return cached
        titles: dict[str, str] = {}
        for candidate_year in (year - 1, year, year + 1):
            titles.update(self.by_year.get(candidate_year, {}))
        self._windows[year] = titles
        return titles


def citation_pairs(body: str) -> list[list]:
    """Runs of citations printed together, which are one case in several reporters.

    Grouping is by position alone: two citations separated by nothing but punctuation are the same
    case, because no writer sets two different authorities a colon apart.
    """
    citations = sorted(extract_citations(body), key=lambda c: c.span[0])
    runs: list[list] = []
    current: list = []
    for citation in citations:
        if current and PAIR_SEPARATOR.match(body[current[-1].span[1] : citation.span[0]]):
            current.append(citation)
        else:
            if len(current) > 1:
                runs.append(current)
            current = [citation]
    if len(current) > 1:
        runs.append(current)
    return runs


def pair_sightings(session: Session, aliases: dict[str, str], *, limit: int | None = None) -> list[Sighting]:
    """Every citation the corpus prints alongside one it already knows.

    Deterministic: the judgment itself asserts that these are the same case, so there is nothing to
    infer and no score to weigh. A run naming two different known judgments is a parse error rather
    than a pairing, and is dropped.
    """
    found: list[Sighting] = []
    judgments = list(
        session.scalars(
            select(Judgment)
            .join(JudgmentTextVersion, JudgmentTextVersion.judgment_id == Judgment.id)
            .order_by(Judgment.decided_on.desc())
        ).all()
    )
    if limit:
        judgments = judgments[:limit]

    for judgment in judgments:
        for paragraph in _paragraphs_of(session, judgment.id):
            for run in citation_pairs(paragraph.body):
                known_ids = {aliases[c.normalized] for c in run if c.normalized in aliases}
                if len(known_ids) != 1:
                    continue
                judgment_id = known_ids.pop()
                for citation in run:
                    if citation.normalized in aliases:
                        continue
                    found.append(
                        Sighting(
                            normalized=citation.normalized,
                            citation_string=citation.raw,
                            reporter=citation.reporter,
                            judgment_id=judgment_id,
                            score=100.0,
                            citing_id=judgment.id,
                        )
                    )
    return found


def match_title(parties: str, titles: dict[str, str]) -> tuple[str, float] | None:
    """The judgment whose title these party names name, if one clearly does."""
    if not titles:
        return None
    matches = process.extract(
        parties,
        titles,
        scorer=fuzz.token_set_ratio,
        processor=utils.default_process,
        limit=2,
        score_cutoff=LEARN_SCORE,
    )
    if not matches:
        return None
    _, score, judgment_id = matches[0]
    if len(matches) > 1 and (score - matches[1][1]) < LEARN_MARGIN:
        return None  # two titles too alike to choose between
    return judgment_id, float(score)


def collect_sightings(
    session: Session,
    index: TitleIndex,
    known: set[str],
    *,
    limit: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    stats: LearnStats | None = None,
) -> list[Sighting]:
    """Read the corpus and record every citation whose parties name a judgment we hold."""
    stats = stats if stats is not None else LearnStats()
    judgments = list(
        session.scalars(
            select(Judgment)
            .join(JudgmentTextVersion, JudgmentTextVersion.judgment_id == Judgment.id)
            .order_by(Judgment.decided_on.desc())
        ).all()
    )
    if limit:
        judgments = judgments[:limit]

    sightings: list[Sighting] = []
    total = len(judgments)
    for done, judgment in enumerate(judgments, start=1):
        stats.judgments_read += 1
        for paragraph in _paragraphs_of(session, judgment.id):
            for citation in extract_citations(paragraph.body):
                stats.citations_seen += 1
                if citation.normalized in known:
                    stats.already_known += 1
                    continue
                parties = (citation.party_names or "").strip()
                if len(parties) < MIN_PARTY_CHARS or not citation.year:
                    stats.no_parties += 1
                    continue
                match = match_title(parties, index.window(citation.year))
                if match is None:
                    stats.no_match += 1
                    continue
                judgment_id, score = match
                if judgment_id == judgment.id:
                    continue  # a judgment citing itself teaches nothing
                stats.sightings += 1
                sightings.append(
                    Sighting(
                        normalized=citation.normalized,
                        citation_string=citation.raw,
                        reporter=citation.reporter,
                        judgment_id=judgment_id,
                        score=score,
                        citing_id=judgment.id,
                    )
                )
        if on_progress is not None:
            on_progress(done, total)
    return sightings


def accept(sightings: list[Sighting], stats: LearnStats) -> dict[str, Sighting]:
    """Decide which sightings are safe to record as aliases.

    A citation that two judgments attach to different cases is discarded outright: one of them is
    wrong, there is no way to tell which, and a wrong alias would make the resolver confidently name
    the wrong case — which is worse than naming none.
    """
    grouped: dict[str, list[Sighting]] = defaultdict(list)
    for sighting in sightings:
        grouped[sighting.normalized].append(sighting)

    accepted: dict[str, Sighting] = {}
    for normalized, group in grouped.items():
        judgment_ids = {s.judgment_id for s in group}
        if len(judgment_ids) > 1:
            stats.rejected_conflict += 1
            continue
        best = max(group, key=lambda s: s.score)
        citing = {s.citing_id for s in group}
        if best.score >= CONFIDENT_SCORE or len(citing) >= SIGHTINGS_REQUIRED:
            accepted[normalized] = best
            stats.accepted += 1
            stats.by_reporter[best.reporter] = stats.by_reporter.get(best.reporter, 0) + 1
        else:
            stats.rejected_uncorroborated += 1
    return accepted


def learn_aliases(
    session: Session,
    *,
    limit: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    dry_run: bool = False,
) -> LearnStats:
    """Read the corpus, infer the reporter citations it names, and record the safe ones."""
    stats = LearnStats()
    aliases = {
        normalized: judgment_id
        for normalized, judgment_id in session.execute(
            select(CitationAlias.normalized, CitationAlias.judgment_id)
        ).all()
    }

    # Pass one: what the corpus states outright. Pairing is deterministic and it feeds pass two, so a
    # citation learned here narrows the work the fuzzy matcher has to do at all.
    paired = pair_sightings(session, aliases, limit=limit)
    accepted_pairs: dict[str, Sighting] = {}
    for sighting in paired:
        conflict = accepted_pairs.get(sighting.normalized)
        if conflict is not None and conflict.judgment_id != sighting.judgment_id:
            accepted_pairs.pop(sighting.normalized)
            stats.rejected_conflict += 1
            continue
        accepted_pairs[sighting.normalized] = sighting
    stats.paired = len(accepted_pairs)

    if not dry_run:
        _record(session, accepted_pairs, aliases, source=PAIRED)

    # Pass two: what the corpus implies. Party names against titles, for citations no pairing reached.
    index = TitleIndex.build(session)
    sightings = collect_sightings(
        session, index, set(aliases), limit=limit, on_progress=on_progress, stats=stats
    )
    accepted = accept(sightings, stats)

    if dry_run:
        return stats

    _record(session, accepted, aliases, source=INFERRED)
    return stats


def _record(
    session: Session, accepted: dict[str, Sighting], aliases: dict[str, str], *, source: str
) -> None:
    """Write learned aliases, keeping the in-memory index in step so later passes see them."""
    for normalized, sighting in accepted.items():
        if normalized in aliases:
            continue
        session.add(
            CitationAlias(
                judgment_id=sighting.judgment_id,
                reporter=sighting.reporter,
                citation_string=sighting.citation_string,
                normalized=normalized,
                source=source,
            )
        )
        aliases[normalized] = sighting.judgment_id
    session.commit()


def _paragraphs_of(session: Session, judgment_id: str) -> list[Paragraph]:
    version = session.scalars(
        select(JudgmentTextVersion)
        .where(JudgmentTextVersion.judgment_id == judgment_id)
        .order_by(JudgmentTextVersion.preferred.desc())
    ).first()
    if version is None:
        return []
    return list(
        session.scalars(select(Paragraph).where(Paragraph.text_version_id == version.id)).all()
    )
