"""Is the court the brief names the court that decided it?

Failure mode 3. A brief writes "as the Supreme Court held" and cites a High Court judgment; or "a
Constitution Bench has settled the point" and cites two judges. Both make an authority sound binding
when it is not, and both are checkable without reading a word of the judgment, because the corpus
already knows which court decided it and how many judges sat.

Two claims are read out of the brief's own sentence and compared with the record:

  * **The court.** "the Supreme Court held", "the Apex Court", "the High Court" — what the brief says
    decided the case.
  * **The bench.** "a Constitution Bench", "a three-Judge Bench", "a Division Bench" — how much weight
    the brief claims for it. A Constitution Bench binds where two judges do not, so claiming one is
    claiming a great deal.

Only overstatement is a finding. A brief that says "a two-Judge Bench" of a case decided by five is
being modest about its own authority, which harms nobody. And where the record is silent — the corpus
holds no bench strength for that judgment — the answer is that the claim was not assessed, never that
it was wrong.

This is deliberately about what the brief *says*, not about which authority the brief *ought* to have
cited. Whether a larger bench has settled the same point is a question about the point, and answering
it needs the citator and a reading of what was decided; it is not something the metadata can settle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SUPREME_COURT = "supreme_court"
HIGH_COURT = "high_court"

# What the brief says decided the case. "This Court" is deliberately absent: in a brief it means the
# court being addressed, not the court that decided the authority, and reading it either way would
# invent findings.
# A court counts as *attributed* only where the brief says it decided something. Naming a court in a
# narrative recital — "On 22.3.2007 the High Court passed an order making the notice absolute" — says
# where the case came from, not whose holding is relied on, and reading that as an attribution turns
# the commonest sentence in any statement of facts into a finding.
HOLDING_VERB = (
    r"(?:has\s+|have\s+|had\s+|was\s+|were\s+)?"
    r"(?:held|observed|laid\s+down|ruled|settled|decided|declared|opined|reiterated|clarified|"
    r"stated|concluded|expressed"
    # "took a contrary view", "was of the view that" — a view is a holding by another name.
    r"|took\s+(?:a|the)\s+[\w-]+\s+view|of\s+the\s+view)"
)
COURT_CLAIMS: list[tuple[str, re.Pattern[str]]] = [
    (
        SUPREME_COURT,
        re.compile(
            r"(?i)\b(?:the\s+)?(?:Hon(?:'|’)?ble\s+)?"
            r"(?:Supreme\s+Court(?:\s+of\s+India)?|Apex\s+Court)"
            r"[^.]{0,40}?\s+" + HOLDING_VERB + r"\b"
        ),
    ),
    (
        HIGH_COURT,
        re.compile(
            r"(?i)\b(?:the\s+)?(?:Hon(?:'|’)?ble\s+)?(?:[A-Z][\w&.]+\s+)?High\s+Court"
            r"[^.]{0,40}?\s+" + HOLDING_VERB + r"\b"
        ),
    ),
]

# What turns a "the High Court held …" shape into a recital of the case's history rather than the
# brief's claim about the authority it cites: a fronted procedural participle just before the court
# phrase -- "Rejecting the plea, the High Court opined that …". The brief is recounting what happened
# below; the words are the citation's own narration of it, and the proposition attributed inside the
# that-clause belongs to the case below, not to what the brief says the cited judgment decided. A
# genuine attribution -- "the High Court has held that X" -- carries no such participle. Without this
# rule, every clean brief sentence lifted from a judgment that recounts the case below reads as
# failure mode 3, which is the false positive the September 2026 holdout caught.
RECITAL_MARKER = re.compile(
    r"""(?ix)
    \b(?: reject | allow | dismiss | set(?:ting)?\s+aside | quash | remand
          | accept | accede | concur | differ | modify | uphold
    )\w*
    \b[^,]{0,60},\s*$
    """
)

def _is_recital(proposition: str, match_start: int) -> bool:
    """Is the court phrase preceded by a fronted procedural participle?"""
    before = proposition[max(0, match_start - 80) : match_start]
    return RECITAL_MARKER.search(before) is not None

# How much weight the brief claims. A Constitution Bench is five judges by Article 145(3); a Division
# Bench is two and a Full Bench three, though those are High Court usages and only claim a minimum.
BENCH_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "seven": 7,
    "nine": 9,
    "eleven": 11,
    "thirteen": 13,
}
NUMBERED_BENCH = re.compile(
    r"(?i)\b(?P<word>two|three|four|five|seven|nine|eleven|thirteen)[-\s]?(?:Judge|Member)s?\s+Bench\b"
)
CONSTITUTION_BENCH = re.compile(r"(?i)\bConstitution\s+Bench\b")
DIVISION_BENCH = re.compile(r"(?i)\bDivision\s+Bench\b")

CONSTITUTION_BENCH_SIZE = 5
DIVISION_BENCH_SIZE = 2

OK = "ok"
WRONG_COURT = "wrong_court"
OVERSTATED_BENCH = "overstated_bench"
NOT_ASSESSED = "not_assessed"


@dataclass
class Attribution:
    """What the brief claims about the court that decided the case it cites."""

    court: str | None = None
    bench: int | None = None
    court_cue: str | None = None
    bench_cue: str | None = None

    @property
    def says_anything(self) -> bool:
        return self.court is not None or self.bench is not None


@dataclass
class HierarchyCheck:
    """The brief's claim about the court, against what the corpus records."""

    status: str
    claimed_court: str | None = None
    actual_court: str | None = None
    claimed_bench: int | None = None
    actual_bench: int | None = None
    cue: str | None = None
    note: str | None = None

    @property
    def is_problem(self) -> bool:
        return self.status in {WRONG_COURT, OVERSTATED_BENCH}


def read_attribution(proposition: str) -> Attribution:
    """What the brief's own sentence says about the deciding court and its strength."""
    attribution = Attribution()
    for court, pattern in COURT_CLAIMS:
        for match in pattern.finditer(proposition):
            if _is_recital(proposition, match.start()):
                continue  # a narrated view from the case below, not the brief's attribution
            if attribution.court is None:
                attribution.court = court
                attribution.court_cue = " ".join(match.group(0).split())
            break

    if match := CONSTITUTION_BENCH.search(proposition):
        attribution.bench = CONSTITUTION_BENCH_SIZE
        attribution.bench_cue = match.group(0)
    elif match := NUMBERED_BENCH.search(proposition):
        attribution.bench = BENCH_WORDS[match.group("word").lower()]
        attribution.bench_cue = " ".join(match.group(0).split())
    elif match := DIVISION_BENCH.search(proposition):
        attribution.bench = DIVISION_BENCH_SIZE
        attribution.bench_cue = match.group(0)
    return attribution


def court_of(court_name: str | None) -> str | None:
    """Which kind of court a judgment's recorded court name is."""
    if not court_name:
        return None
    name = court_name.lower()
    if "supreme court" in name:
        return SUPREME_COURT
    if "high court" in name:
        return HIGH_COURT
    return None


def check_hierarchy(
    proposition: str, court_name: str | None, bench_strength: int | None
) -> HierarchyCheck:
    """Compare what the brief says about the court with what the corpus records."""
    attribution = read_attribution(proposition)
    actual_court = court_of(court_name)

    if not attribution.says_anything:
        return HierarchyCheck(
            status=NOT_ASSESSED,
            actual_court=actual_court,
            actual_bench=bench_strength,
            note="the brief does not say which court decided this, so there was nothing to check",
        )

    # The court first: passing a High Court decision off as the Supreme Court's is the graver claim,
    # because it turns persuasive authority into binding authority.
    if attribution.court and actual_court and attribution.court != actual_court:
        return HierarchyCheck(
            status=WRONG_COURT,
            claimed_court=attribution.court,
            actual_court=actual_court,
            claimed_bench=attribution.bench,
            actual_bench=bench_strength,
            cue=attribution.court_cue,
            note=(
                f"the brief attributes this to {attribution.court.replace('_', ' ')} "
                f"({attribution.court_cue!r}), but it was decided by {court_name}"
            ),
        )

    if attribution.bench and bench_strength and attribution.bench > bench_strength:
        return HierarchyCheck(
            status=OVERSTATED_BENCH,
            claimed_court=attribution.court,
            actual_court=actual_court,
            claimed_bench=attribution.bench,
            actual_bench=bench_strength,
            cue=attribution.bench_cue,
            note=(
                f"the brief calls this {attribution.bench_cue!r}, which is {attribution.bench} judges; "
                f"the judgment was decided by {bench_strength}"
            ),
        )

    if attribution.bench and not bench_strength:
        return HierarchyCheck(
            status=NOT_ASSESSED,
            claimed_court=attribution.court,
            actual_court=actual_court,
            claimed_bench=attribution.bench,
            cue=attribution.bench_cue,
            note=(
                f"the brief calls this {attribution.bench_cue!r}, but the corpus records no bench "
                "strength for this judgment, so the claim was not checked"
            ),
        )

    return HierarchyCheck(
        status=OK,
        claimed_court=attribution.court,
        actual_court=actual_court,
        claimed_bench=attribution.bench,
        actual_bench=bench_strength,
        cue=attribution.court_cue or attribution.bench_cue,
    )
