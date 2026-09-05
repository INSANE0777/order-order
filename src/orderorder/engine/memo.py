"""What opposing counsel would say about this citation, and what to do about it.

`docs/PRD.md` A13. The verdict says what is wrong; the memo says what that costs you in court. Those
are different documents for different moments — the verdict is a checklist, and this is the paragraph
you read the night before a hearing when you are deciding whether to keep an authority, narrow the
proposition, or find something better.

The architecture is specific that the memo is written "from the verdict object only", and that is
what makes it possible to write it without a model at all. A memo generated from the judgment could
say something the checks never established; a memo generated from the findings can only restate what
was already proved, in the voice of the person who will use it against you. Every sentence here is
therefore traceable to a finding, and the module cannot invent an attack that the engine did not
support. That is the same discipline as quote-or-nothing, applied to prose.

Three parts, and the third is the one that is usually missing:

  * **Attacks** — one per finding, in opposing counsel's voice, each with the concrete fact from the
    verdict that makes it stick, and a fix.
  * **What survives** — what was checked and came back sound. An advocate needs to know which
    authorities they can lean on, not only which ones they cannot.
  * **What was not checked** — stated plainly, because silence reads as safety and is not. A citation
    with no findings and no model configured has been checked for existence and pinpoint and nothing
    else, and saying so is the difference between a tool that is trusted and one that is trusted
    wrongly.

The attacks are ordered by what an opponent would actually lead with. A case that does not exist ends
the argument; a case that is no longer good law ends it almost as fast; a paragraph that turns out to
be counsel's own submission is embarrassing in a way a shifted pinpoint is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orderorder.engine.verdict import (
    MODE_DEAD_LAW,
    MODE_DISTINGUISHABLE,
    MODE_MINORITY,
    MODE_MISCITE,
    MODE_NOT_THERE,
    MODE_OBITER,
    MODE_OVERSTATEMENT,
    MODE_PHANTOM,
    MODE_QUOTED,
    MODE_WRONG_COURT,
    MODE_WRONG_PINPOINT,
    CitationVerdict,
)

MODE_SELECTIVE = 9

# What an opponent leads with. A citation that does not exist ends the argument; one that is no longer
# good law ends it almost as fast. A shifted pinpoint is a nuisance by comparison, and belongs last
# where it will not crowd out something graver.
SEVERITY = [
    MODE_PHANTOM,
    MODE_MISCITE,
    MODE_DEAD_LAW,
    MODE_NOT_THERE,
    MODE_QUOTED,
    MODE_MINORITY,
    MODE_WRONG_COURT,
    MODE_OBITER,
    MODE_SELECTIVE,
    MODE_OVERSTATEMENT,
    MODE_DISTINGUISHABLE,
    MODE_WRONG_PINPOINT,
]

# The line opposing counsel takes, and the fix that closes it off. Keyed by failure mode. Written to
# be said out loud, because that is how they will arrive.
ATTACKS: dict[int, tuple[str, str]] = {
    MODE_PHANTOM: (
        "My learned friend's authority does not exist.",
        "Remove it. If the proposition is right, find the case that actually says so; if it came from "
        "a language model, assume every other citation from the same source is suspect too.",
    ),
    MODE_MISCITE: (
        "That reference is to a different case altogether.",
        "Check the citation against the report. Give the correct reference, and say which reporter you "
        "are citing from, so the bench can find it.",
    ),
    MODE_DEAD_LAW: (
        "That case has been overruled, and my friend cites it as though it were good law.",
        "Drop it, or cite it only for a proposition the later judgment left standing and say so "
        "expressly. If the point still holds, cite the judgment that now holds it.",
    ),
    MODE_NOT_THERE: (
        "The judgment does not say what my friend says it says.",
        "Read the paragraph again. Either state the proposition the court actually stated, or find "
        "authority for the one you need.",
    ),
    MODE_QUOTED: (
        "Those are not that court's words. It was quoting somebody else.",
        "Cite the judgment the passage came from, at its own paragraph. If the citing court adopted "
        "the passage, say that it did, and cite the paragraph where it says so.",
    ),
    MODE_MINORITY: (
        "My friend is citing the dissent.",
        "Cite the majority. If the minority reasoning is what you want, present it as persuasive and "
        "name it as a dissent — the bench will notice either way, and it is better coming from you.",
    ),
    MODE_WRONG_COURT: (
        "The authority is not what my friend claims it is.",
        "State the court and the bench correctly. If you need a larger bench, the citator will say "
        "whether one has decided the point.",
    ),
    MODE_OBITER: (
        "That passage decided nothing. The court said in terms that it was not deciding the question.",
        "Present it as obiter, which is honest and still persuasive, or find a case where the point was "
        "necessary to the decision.",
    ),
    MODE_SELECTIVE: (
        "The sentence has been cut before the words that matter.",
        "Quote the qualification with the rule, and argue that your facts satisfy it. The bench will "
        "read the paragraph.",
    ),
    MODE_OVERSTATEMENT: (
        "The court put it far more narrowly than my friend does.",
        "Narrow the proposition to what the court actually held. A narrower point you can prove beats a "
        "wider one you cannot.",
    ),
    MODE_DISTINGUISHABLE: (
        "That case turned on facts we do not have here.",
        "Meet the distinction head on: say which facts are shared and why the difference does not "
        "matter, or find an authority closer to these facts.",
    ),
    MODE_WRONG_PINPOINT: (
        "The paragraph my friend has given us is not the paragraph the words are in.",
        "Correct the pinpoint. A bench that cannot find your passage stops looking for it.",
    ),
}

# What "no finding" means for each check, so that silence is never read as approval.
CHECKED_WELL = {
    "existence": "the citation resolves to a judgment in the corpus",
    "pinpoint": "the paragraph cited exists in that judgment",
    "voice": "the passage is the court's own words, not counsel's or a quotation",
    "treatment": "no later judgment in the corpus overrules or doubts it",
    "hierarchy": "the court and bench the brief claims match the record",
    "support": "a quote from the judgment was found and verified word for word",
}


@dataclass
class Attack:
    """One line an opponent can take, the fact behind it, and what closes it off."""

    mode: int
    line: str
    because: str
    fix: str


@dataclass
class Memo:
    """The case against one citation, assembled from its verdict and nothing else."""

    citation: str
    grade: str
    judgment_title: str | None = None
    attacks: list[Attack] = field(default_factory=list)
    survives: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return not self.attacks

    @property
    def worst(self) -> Attack | None:
        return self.attacks[0] if self.attacks else None


def _checks_run(verdict: CitationVerdict) -> tuple[list[str], list[str]]:
    """What the engine actually established about this citation, and what it never asked."""
    modes = {finding.mode for finding in verdict.findings}
    survives: list[str] = []
    unchecked: list[str] = []

    if verdict.existence == "found":
        survives.append(CHECKED_WELL["existence"])
    elif verdict.existence == "ambiguous":
        unchecked.append("which judgment this citation names: more than one matched")

    if verdict.pinpoint is None or verdict.pinpoint.status == "none_claimed":
        unchecked.append("which paragraph is relied on: the brief gives no pinpoint")
    elif verdict.pinpoint.status == "ok":
        survives.append(CHECKED_WELL["pinpoint"])

    if verdict.existence != "found":
        # Nothing below was reachable: there was no judgment to read.
        unchecked.append("everything that needs the judgment text, since the citation resolved to none")
        return survives, unchecked

    if verdict.voice is not None and not modes & {MODE_QUOTED, MODE_MINORITY}:
        survives.append(CHECKED_WELL["voice"])
    elif verdict.voice is None:
        unchecked.append("whose words the passage carries")

    if verdict.treatment is not None and MODE_DEAD_LAW not in modes:
        survives.append(CHECKED_WELL["treatment"])
    elif verdict.treatment is None:
        unchecked.append("whether any later judgment has overruled or doubted this one")

    if verdict.hierarchy is not None and verdict.hierarchy.status == "ok":
        survives.append(CHECKED_WELL["hierarchy"])
    elif verdict.hierarchy is not None and verdict.hierarchy.status == "not_assessed":
        unchecked.append(verdict.hierarchy.note or "the court and bench claimed")

    if verdict.quote_verified:
        survives.append(CHECKED_WELL["support"])
    elif verdict.support == "not_assessed":
        unchecked.append(
            "whether the judgment supports the proposition to the extent the brief states it, "
            "which needs a language model and none was configured"
        )

    if verdict.applicability is None:
        unchecked.append("whether the case governs the facts of this matter: no facts were supplied")

    return survives, unchecked


def write_memo(verdict: CitationVerdict) -> Memo:
    """Turn one verdict into the memo opposing counsel would write about it.

    Nothing here reads the judgment. Every attack is a finding the engine already made, restated as
    the sentence it will be said in, so the memo cannot claim more than was proved.
    """
    order = {mode: position for position, mode in enumerate(SEVERITY)}
    findings = sorted(verdict.findings, key=lambda f: order.get(f.mode, len(SEVERITY)))

    attacks: list[Attack] = []
    seen: set[int] = set()
    for finding in findings:
        line, fix = ATTACKS.get(
            finding.mode,
            ("This citation will not bear the weight put on it.", "Check it against the report."),
        )
        # One mode, one attack. Two findings of the same kind are one line in court.
        if finding.mode in seen:
            attacks[-1].because += f" {finding.detail.rstrip('.')}."
            continue
        seen.add(finding.mode)
        attacks.append(Attack(finding.mode, line, finding.detail or finding.label, fix))

    survives, unchecked = _checks_run(verdict)
    return Memo(
        citation=verdict.citation_raw,
        grade=verdict.grade,
        judgment_title=verdict.judgment_title,
        attacks=attacks,
        survives=survives,
        unchecked=unchecked,
    )


def render_memo(memo: Memo) -> list[str]:
    """The memo as lines, for the terminal or a report."""
    lines = [f"{memo.citation} - grade {memo.grade}"]
    if memo.judgment_title:
        lines.append(f"  {memo.judgment_title}")
    lines.append("")

    if memo.attacks:
        lines.append("  What the other side will say")
        for attack in memo.attacks:
            lines.append(f'    "{attack.line}"')
            lines.append(f"      because: {attack.because}")
            lines.append(f"      fix:     {attack.fix}")
            lines.append("")
    else:
        lines.append("  Nothing found to attack in what was checked.")
        lines.append("")

    if memo.survives:
        lines.append("  What holds up")
        lines.extend(f"    - {item}" for item in memo.survives)
        lines.append("")

    if memo.unchecked:
        lines.append("  What was not checked")
        lines.extend(f"    - {item}" for item in memo.unchecked)
        lines.append("")
    return lines
