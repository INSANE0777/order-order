"""Find the paragraph a proposition rests on, and check the pinpoint the brief claimed.

Two jobs, both model-free:

  * **locate** ranks a judgment's paragraphs against a proposition and returns candidates. A language
    model is asked later to pick from these candidates and to copy out a verbatim quote; the quote is
    then string-verified by `engine.quotes`, which is what makes "supported" mean something.
  * **check_pinpoint** compares the paragraph the brief cited with what the judgment actually contains.
    This alone catches the Delhi High Court case from September 2025, where a brief pinpointed
    paragraphs 73 and 74 of a judgment that has 27 paragraphs. It also catches the quieter version,
    where the paragraph exists but is not the one the words came from: a long verbatim run of the
    brief's own sentence turning up in a different paragraph settles that without a model.

Both return evidence rather than a conclusion, because the verdict is assembled from all the detectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orderorder.engine.lexical import BM25Index, ScoredDocument, tokenize
from orderorder.engine.quotes import NO_SHARED_RUN, QuoteMatch, SharedRun, find_quote, longest_shared_run
from orderorder.ingest.segment import SegParagraph, find_out_of_sequence

DEFAULT_TOP_K = 8


@dataclass
class Candidate:
    """One paragraph offered as the possible source of a proposition."""

    seq: int
    printed_label: str | None
    score: float
    matched_terms: list[str]
    body: str
    is_claimed_pinpoint: bool = False
    likely_quoted: bool = False
    opinion_kind: str | None = None
    opinion_author: str | None = None
    role: str | None = None

    @property
    def preview(self) -> str:
        return self.body[:200] + ("..." if len(self.body) > 200 else "")


@dataclass
class PinpointCheck:
    """What the brief claimed against what the judgment holds."""

    claimed: str | None
    status: str  # ok | not_in_judgment | out_of_range | wrong_paragraph | none_claimed
    highest_label: str | None = None
    paragraph_count: int = 0
    available: list[str] = field(default_factory=list)
    note: str | None = None
    found_at: str | None = None
    anchor: str | None = None

    @property
    def is_problem(self) -> bool:
        return self.status in {"not_in_judgment", "out_of_range", "wrong_paragraph"}

    @property
    def exists(self) -> bool:
        """The paragraph the brief named is in the judgment, whatever it says."""
        return self.status in {"ok", "wrong_paragraph"}


@dataclass
class LocationResult:
    candidates: list[Candidate]
    pinpoint: PinpointCheck
    query_terms: list[str] = field(default_factory=list)

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


def _numeric(label: str | None) -> float | None:
    """Sort key for a printed label, so '5.1' orders between 5 and 6 and text labels are ignored."""
    if not label:
        return None
    try:
        parts = label.split(".")
        value = float(parts[0])
        if len(parts) > 1 and parts[1].isdigit():
            value += int(parts[1]) / 100
        return value
    except (ValueError, IndexError):
        return None


def _words_are_elsewhere(
    paragraphs: list[SegParagraph], claimed: str, proposition: str
) -> tuple[str, SharedRun] | None:
    """Where in the judgment the brief's own words actually are, if not where it said.

    Only a verbatim run decides this, and only a long one. A brief that paraphrases shares nothing
    with the judgment but stock phrasing, so a short overlap proves nothing either way; ten
    consecutive words does not happen by accident. And the finding needs both halves — the words
    somewhere else *and* not at the pinpoint — because a phrase the judgment repeats would otherwise
    convict a citation that was right.

    This is the same discipline as the rest of the engine: a string match, not a similarity score, and
    silence where there is no match.
    """
    at_pinpoint = NO_SHARED_RUN
    best_label: str | None = None
    best_run = NO_SHARED_RUN

    for paragraph in paragraphs:
        label = paragraph.printed_label
        if not label:
            continue
        run = longest_shared_run(proposition, paragraph.body)
        # Labels are not unique: a judgment that quotes another carries its numbering too, so
        # "paragraph 2" can name two paragraphs. Neither of them is *elsewhere* than paragraph 2, and
        # counting the second as elsewhere reported a citation as pointing away from where it points.
        if label == claimed:
            at_pinpoint = max(at_pinpoint, run, key=lambda r: r.words)
        elif run.words > best_run.words:
            best_label, best_run = label, run

    if at_pinpoint.is_distinctive or not best_run.is_distinctive or best_label is None:
        return None
    return best_label, best_run


def check_pinpoint(
    paragraphs: list[SegParagraph], claimed: str | None, proposition: str | None = None
) -> PinpointCheck:
    """Verify that the paragraph a brief cites exists in the judgment, and that it is the right one."""
    labels = [p.printed_label for p in paragraphs if p.printed_label]
    numbers = [n for n in (_numeric(label) for label in labels) if n is not None]
    highest = max(numbers) if numbers else None
    highest_label = None
    if highest is not None:
        highest_label = next(
            (label for label in labels if _numeric(label) == highest),
            None,
        )

    if not claimed:
        return PinpointCheck(None, "none_claimed", highest_label, len(paragraphs), labels)

    claimed = str(claimed).strip()
    if claimed in labels:
        elsewhere = _words_are_elsewhere(paragraphs, claimed, proposition) if proposition else None
        if elsewhere is None:
            return PinpointCheck(claimed, "ok", highest_label, len(paragraphs), labels)
        found_at, run = elsewhere
        return PinpointCheck(
            claimed,
            "wrong_paragraph",
            highest_label,
            len(paragraphs),
            labels,
            note=(
                f"the brief cites paragraph {claimed}, but {run.words} consecutive words of its own "
                f"sentence appear in paragraph {found_at} and not in {claimed}: {run.text!r}"
            ),
            found_at=found_at,
            anchor=run.text,
        )

    claimed_number = _numeric(claimed)
    if claimed_number is not None and highest is not None and claimed_number > highest:
        return PinpointCheck(
            claimed,
            "out_of_range",
            highest_label,
            len(paragraphs),
            labels,
            note=(
                f"the brief cites paragraph {claimed}, but this judgment's numbering stops at "
                f"{highest_label} ({len(paragraphs)} paragraphs)"
            ),
        )
    return PinpointCheck(
        claimed,
        "not_in_judgment",
        highest_label,
        len(paragraphs),
        labels,
        note=f"paragraph {claimed} is not among this judgment's printed labels",
    )


def locate(
    paragraphs: list[SegParagraph],
    proposition: str,
    *,
    claimed_pinpoint: str | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> LocationResult:
    """Rank paragraphs against the proposition.

    The paragraph the brief pinpointed is always included in the candidate set even when it ranks
    poorly, so the verdict can report that the cited paragraph does not in fact support the claim.
    """
    pinpoint = check_pinpoint(paragraphs, claimed_pinpoint, proposition)
    if not paragraphs:
        return LocationResult([], pinpoint)

    index = BM25Index.build([p.body for p in paragraphs])
    ranked = index.score(proposition, top_k=top_k)
    quoted = find_out_of_sequence(paragraphs)

    chosen: dict[int, ScoredDocument] = {r.index: r for r in ranked}
    # A judgment that quotes another carries that judgment's numbering too, so "paragraph 2" can name
    # two paragraphs. The court's own comes first, and that is the one a pinpoint means: matching the
    # label alone marked a quoted block as the cited paragraph and reported the court's own holding as
    # somebody else's words.
    pinpoint_position: int | None = None
    if claimed_pinpoint:
        wanted = str(claimed_pinpoint).strip()
        for position, paragraph in enumerate(paragraphs):
            if paragraph.printed_label == wanted:
                pinpoint_position = position
                break
        if pinpoint_position is not None and pinpoint_position not in chosen:
            chosen[pinpoint_position] = ScoredDocument(pinpoint_position, 0.0, [])

    candidates: list[Candidate] = []
    for position, scored in chosen.items():
        paragraph = paragraphs[position]
        candidates.append(
            Candidate(
                seq=paragraph.seq,
                printed_label=paragraph.printed_label,
                score=round(scored.score, 3),
                matched_terms=scored.matched_terms,
                body=paragraph.body,
                is_claimed_pinpoint=(position == pinpoint_position),
                likely_quoted=paragraph.seq in quoted,
                opinion_kind=paragraph.opinion_kind,
                opinion_author=paragraph.opinion_author,
                role=paragraph.role,
            )
        )
    candidates.sort(key=lambda c: (-c.score, c.seq))
    return LocationResult(candidates, pinpoint, tokenize(proposition))


def verify_in_candidates(
    quote: str, candidates: list[Candidate], *, ocr_derived: bool = False
) -> tuple[Candidate | None, QuoteMatch]:
    """Find which candidate paragraph actually contains a quote.

    This is the step that turns a model's answer into evidence: the model names a paragraph and copies a
    sentence, and only a string match here lets the claim be called supported.
    """
    best_miss = QuoteMatch(False, "not_found")
    for candidate in candidates:
        match = find_quote(quote, candidate.body, ocr_derived=ocr_derived)
        if match.found:
            return candidate, match
        if match.match_type == "too_short":
            best_miss = match
    return None, best_miss
