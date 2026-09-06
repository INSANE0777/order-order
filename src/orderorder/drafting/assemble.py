"""A plan plus the engine's answers, arranged as a written submission.

`docs/PRD.md` B7 and B9. The plan (`drafting.plan`) says what the advocate wants to argue; the gate
(`engine.authority`) says which of those propositions may have an authority put behind them and which
may not. This module is what stands between the two, and its entire job is to make sure the second
answer survives into the document.

That is harder than it sounds, and it is the reason this is a module rather than a template. A
drafting tool is under constant pressure to produce a finished-looking file: an empty paragraph looks
like a bug, a refusal looks like a failure, and the obvious fix — quietly drop the propositions that
found no authority — produces a submission that reads as though every sentence in it is supported.
That is precisely the document this engine exists to catch when the other side files it.

So the rules here are:

  * a proposition that was refused stays in the draft, in its place in the argument, marked;
  * an unchecked passage is never given a citation, because a citation is a claim that it was checked;
  * a narrowed proposition is written as the court stated it, not as the advocate asked for it;
  * the table of authorities lists what the draft actually cites, and nothing that was not verified
    can be cited, so the two cannot drift apart;
  * the appendix carries the quote for every citation, so a reader can check the document against the
    corpus without the engine's help.

Nothing here calls a model. Every sentence in the assembled draft is either the advocate's own from
the plan, the court's own words from the corpus, or a fixed phrase from this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orderorder.drafting.plan import Issue, Plan
from orderorder.engine.authority import BOUND, NARROWED, REFUSED, UNCHECKED, Binding
from orderorder.engine.hierarchy import HIGH_COURT, SUPREME_COURT, court_of
from orderorder.ingest.metadata import tidy_title

# Court order in the table of authorities: the Supreme Court first, then High Courts, then anything
# whose court could not be read. Within a court, oldest first, which is how a line of authority reads.
COURT_ORDER = {SUPREME_COURT: 0, HIGH_COURT: 1}
# What the draft says where a proposition has no authority behind it. Visible, in the text, at the
# place where the argument would have gone.
MARKS = {
    UNCHECKED: "[NO VERIFIED AUTHORITY - a passage was found but nothing checked that it says this]",
    REFUSED: "[NO AUTHORITY FOUND - do not file this sentence as it stands]",
}


@dataclass
class Point:
    """One proposition in the argument, and what the engine could do with it."""

    proposition: str
    binding: Binding

    @property
    def status(self) -> str:
        return self.binding.status

    @property
    def is_cited(self) -> bool:
        """Whether this point carries a citation in the draft. Only a verified binding does."""
        return self.binding.is_usable

    @property
    def argued(self) -> str:
        """The sentence as it goes into the draft.

        A narrowed binding is written as the court stated it. Handing back the wider sentence with a
        citation to the narrower holding is the overstatement failure mode (`docs/PRD.md` §6, mode 4),
        and writing it here would be the engine committing it.
        """
        if self.status == NARROWED and self.binding.narrowed_to:
            return self.binding.narrowed_to.strip()
        return self.proposition.strip()

    @property
    def citation(self) -> str | None:
        return self.binding.chosen.pinpoint if self.is_cited and self.binding.chosen else None


@dataclass
class Argument:
    """One issue and the points advanced under it."""

    title: str
    points: list[Point] = field(default_factory=list)

    @property
    def cited(self) -> list[Point]:
        return [p for p in self.points if p.is_cited]


@dataclass
class AuthorityEntry:
    """One judgment in the table of authorities, with every paragraph the draft pinpoints."""

    citation: str
    title: str
    court: str | None
    decided_on: str | None
    paragraphs: list[str] = field(default_factory=list)

    @property
    def sort_key(self) -> tuple[int, str, str]:
        return (COURT_ORDER.get(court_of(self.court) or "", 2), self.decided_on or "", self.title)

    def render(self) -> str:
        paragraphs = ", ".join(self.paragraphs)
        tail = f" (para{'s' if len(self.paragraphs) > 1 else ''} {paragraphs})" if paragraphs else ""
        # `ingest.metadata` tidies this on the way in; the guard is here because a corpus imported
        # before that fix still holds eighteen titles ending in a bare "versus", and a table of
        # authorities is the last place to show one.
        return f"{tidy_title(self.title)}, {self.citation}{tail}"


@dataclass
class Draft:
    """A written submission and everything needed to check it."""

    plan: Plan
    arguments: list[Argument] = field(default_factory=list)

    @property
    def points(self) -> list[Point]:
        return [p for argument in self.arguments for p in argument.points]

    @property
    def unsupported(self) -> list[Point]:
        """Every point that goes into the draft without authority. The list a person must read."""
        return [p for p in self.points if not p.is_cited]

    @property
    def counts(self) -> dict[str, int]:
        out = {BOUND: 0, NARROWED: 0, UNCHECKED: 0, REFUSED: 0}
        for point in self.points:
            out[point.status] = out.get(point.status, 0) + 1
        return out

    def authorities(self) -> list[AuthorityEntry]:
        """The table of authorities, built from what the draft cites and nothing else."""
        entries: dict[str, AuthorityEntry] = {}
        for point in self.points:
            if not point.is_cited or point.binding.chosen is None:
                continue
            authority = point.binding.chosen.authority
            key = authority.canonical_key
            entry = entries.get(key)
            if entry is None:
                entry = AuthorityEntry(
                    citation=authority.citation or authority.canonical_key,
                    title=authority.title,
                    court=authority.court,
                    decided_on=authority.decided_on,
                )
                entries[key] = entry
            label = str(authority.paragraph_label or authority.paragraph_seq)
            if label not in entry.paragraphs:
                entry.paragraphs.append(label)
        for entry in entries.values():
            # Paragraph numbers read as numbers where they are numbers, and there are labels like
            # "12A" in Indian reports that are not.
            entry.paragraphs.sort(key=lambda p: (len(p), p))
        return sorted(entries.values(), key=lambda e: e.sort_key)


def assemble(plan: Plan, bindings: dict[str, Binding]) -> Draft:
    """Put the plan and the bindings together, in the plan's own order.

    `bindings` is keyed by proposition, which is how `engine.authority` is called and what the CLI
    already has. A proposition the caller could not bind gets a refusal rather than being dropped:
    silence in a draft is indistinguishable from support.
    """
    draft = Draft(plan=plan)
    for issue in plan.issues:
        draft.arguments.append(_argument(issue, bindings))
    return draft


def _argument(issue: Issue, bindings: dict[str, Binding]) -> Argument:
    argument = Argument(issue.title)
    for proposition in issue.propositions:
        binding = bindings.get(proposition)
        if binding is None:
            binding = Binding(proposition, REFUSED, "this proposition was not put to the engine")
        argument.points.append(Point(proposition, binding))
    return argument
