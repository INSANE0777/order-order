"""Whose words are these?

A passage can be inside a judgment without being the court's view of the law. It may be the court
setting out what an advocate argued, or what the court below held, or a block quoted from an earlier
judgment, or the publisher's headnote. And even when the court is speaking, it may be the dissent.

Two failure modes live here. Mode 5, wrong voice: the brief quotes counsel's submission as if the
court had held it. Mode 6, minority opinion: the brief quotes a dissent as the holding. Both are
common, and both are invisible to anyone reading a paragraph out of context, which is exactly how
citations are checked today.

The division of labour follows the rest of the engine: **structure and cues decide, the model only
explains.**

  * The opinion a paragraph belongs to is a structural fact computed at ingestion from the judgment's
    own announcement of a dissent or concurrence. Nothing overrides it.
  * The voice within a paragraph is decided by attributing cues in the text ("learned counsel
    submitted", "the High Court held"), and the cue that governs is the last one before the sentence
    actually relied on, because a paragraph often recites an argument and then rejects it.
  * A model is consulted for one thing only: whether a court that quoted another source adopted its
    view or rejected it. That is a reading question with no cue to match, and it changes nothing about
    which voice was found.

Every answer carries the cue that produced it, so a reader can check the finding against the text
rather than trusting the label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orderorder.engine.locator import Candidate
from orderorder.engine.prompts import VOICE_PROMPT, VOICE_VERSION
from orderorder.engine.providers import StructuredModel
from orderorder.engine.schemas import VoiceAssessment

# Voices, as in ARCHITECTURE.md section 8: the enumeration a verdict may carry.
COURT_VOICES = {"court_majority", "court_concurring", "court_dissent"}
NOT_THE_COURT = {"counsel_argument", "lower_court", "headnote"}

# Attributing cues. Each pattern marks the words that follow it as somebody else's until the court
# resumes. They are deliberately literal: a cue that has to be guessed at is not evidence.
COUNSEL_CUES = re.compile(
    r"""(?ix)
    \b(?:
        learned\s+(?:senior\s+)?(?:counsel|advocate|ASG|Additional\s+Solicitor\s+General|
            Solicitor\s+General|Attorney\s+General|Government\s+Advocate|Amicus\s+Curiae)
      | (?:it\s+(?:was|is)\s+(?:strenuously\s+|vehemently\s+|further\s+)?
            (?:contended|submitted|urged|argued|canvassed|pleaded))
      | (?:the\s+(?:appellant|respondent|petitioner|plaintiff|defendant|State)s?\s+
            (?:has|have|had)?\s*(?:contended|submitted|urged|argued|would\s+contend|contends|submits))
      | (?:on\s+behalf\s+of\s+the\s+(?:appellant|respondent|petitioner|plaintiff|defendant))
      | (?:submission[s]?\s+(?:of|made\s+by)\s+(?:the\s+)?learned)
    )\b
    """
)
LOWER_COURT_CUES = re.compile(
    r"""(?ix)
    \b(?:
        the\s+(?:High\s+Court|Trial\s+Court|trial\s+court|District\s+Judge|Sessions\s+Judge|
            learned\s+Single\s+Judge|Division\s+Bench|Tribunal|National\s+Commission|Commission|
            Appellate\s+Authority|first\s+appellate\s+court|courts?\s+below)
            # "The High Court has vide the impugned judgement held ..." — the court and its verb are
            # routinely separated by how and when it acted, so a bounded run is allowed between them.
            # The class excludes a full stop, so the run cannot reach a verb in the next sentence.
            [^.]{0,45}?\s+
        (?:held|observed|found|concluded|took\s+the\s+view|was\s+of\s+the\s+view|dismissed|allowed|
            recorded|reasoned|directed)
      | (?:impugned\s+(?:judgment|judgement|order)\s+(?:holds|held|records|proceeds))
    )\b
    """
)
# "In X v. Y this Court observed:" introduces words that are an earlier bench's, not this one's.
#
# The pieces below are shared by the branches. A case name; "(supra)", which is how Indian judgments
# refer back to a case already cited; the reporter's bracketed repetition of the whole citation, which
# is why one bounded run has to admit lower-case letters while the other does not; and the verbs a
# court uses when reporting what an earlier one said.
_CASE_NAME = r"[A-Z][\w.'-]*(?:\s+[\w.'-]+){0,6}\s+v[s]?\.?\s+[A-Z][\w.'-]*(?:\s+[\w.'-]+){0,6}"
# "[Dolat Ram v. State of Haryana, (1995) 1 SCC 349 : 1995 SCC (Cri) 237]" — SCC prints the full
# citation in brackets after the short name, and it contains lower-case letters, so it is matched as a
# bracketed unit rather than by a character class.
_BRACKETED_CITATION = r"(?:\s*\[[^\]]{0,180}\])?"
_REPORTER_RUN = r"[\s,():;\[\]\d.A-Z-]{0,40}?"
_ATTRIBUTING_VERB = r"(?:has\s+|had\s+)?(?:observed|held|laid\s+down|stated|ruled|opined|explained)"
_EARLIER_BENCH = (
    r"(?:this|the|a)\s+"
    r"(?:(?:two|three|five|seven|nine|eleven|thirteen)[-\s]?Judge\s+)?"
    r"(?:Constitution\s+Bench|coordinate\s+Bench|larger\s+Bench|Division\s+Bench|Bench|Court)"
)

QUOTED_PRECEDENT_CUES = re.compile(
    rf"""(?ix)
    \b(?:
        # "A two-Judge Bench of this Court in Dolat Ram v. State of Haryana [ ... ] laid down ..."
        # The bench is named before the case rather than after it, which is the commonest form of all
        # and the one a brief most often passes off as the deciding court's own holding.
        {_EARLIER_BENCH}\s+of\s+this\s+Court\s+in\s+{_CASE_NAME}
            (?:\s*\(supra\))? {_BRACKETED_CITATION} {_REPORTER_RUN}\s*
            {_ATTRIBUTING_VERB}

        # "In Khet Singh vs. Union of India (supra) this Court, after considering a number of earlier
        # decisions, held that ..." — the earlier bench is named after the case, then words intervene
        # before its verb. Naming the bench is what makes that loose run safe; without the bench, the
        # branch after this one applies instead and allows nothing between the citation and the verb.
      | (?:in|see)\s+{_CASE_NAME}
            (?:\s*\(supra\))? {_BRACKETED_CITATION} {_REPORTER_RUN}
            {_EARLIER_BENCH}
            [^.]{{0,60}}?\s*
            {_ATTRIBUTING_VERB}

      | (?:in|see)\s+{_CASE_NAME}
            (?:\s*\(supra\))? {_BRACKETED_CITATION} {_REPORTER_RUN}\s*
            {_ATTRIBUTING_VERB}
      | (?:it\s+was\s+(?:held|observed|laid\s+down)\s+in\s+[A-Z])
      | (?:in\s+paragraph\s+\d{{1,3}}\s+of\s+the\s+(?:said\s+)?(?:judgment|decision|report))
      | (?:the\s+following\s+(?:passage|observations?)\s+(?:from|in)\s+)
    )
    """
)

# The court taking the text back. A recital of an argument ends when the bench answers it.
COURT_RESUMES_CUES = re.compile(
    r"""(?ix)
    \b(?:
        (?:we|this\s+Court)\s+(?:are|is|am)?\s*
            (?:of\s+the\s+(?:considered\s+)?(?:view|opinion)|unable\s+to\s+(?:accept|agree|persuade)|
               not\s+(?:in\s+agreement|persuaded)|hold|find|are\s+satisfied|agree|disagree|
               have\s+no\s+hesitation|are\s+unable)
      | (?:in\s+our\s+(?:considered\s+)?(?:view|opinion|judgment))
      | (?:having\s+(?:heard|considered|examined|bestowed))
      | (?:we\s+are\s+afraid)
      | (?:the\s+(?:submission|contention|argument)s?\s+(?:is|are|was|were)\s+
            (?:without\s+merit|misconceived|liable\s+to\s+be\s+rejected|not\s+acceptable|untenable))
      | (?:this\s+contention\s+(?:cannot|does\s+not|must))
      | (?:we\s+(?:respectfully\s+)?(?:approve|endorse|reiterate|follow)\s+)
    )\b
    """
)

# Adoption or rejection of quoted words, where the court says so in terms. Used only to answer the
# endorsement question without a model when the text already answers it.
ADOPTS = re.compile(
    r"(?i)\b(?:we\s+(?:respectfully\s+)?(?:agree|approve|endorse|concur|reiterate|follow|adopt)"
    r"|quoted\s+with\s+approval|approved\s+in|we\s+are\s+in\s+respectful\s+agreement)\b"
)
REJECTS = re.compile(
    r"(?i)\b(?:we\s+(?:respectfully\s+)?(?:disagree|dissent|are\s+unable\s+to\s+agree|do\s+not\s+approve)"
    r"|no\s+longer\s+good\s+law|stands?\s+overruled|we\s+overrule|is\s+hereby\s+overruled)\b"
)

OPINION_VOICE = {
    "majority": "court_majority",
    "concurring": "court_concurring",
    "dissenting": "court_dissent",
    "headnote": "headnote",
}


@dataclass
class VoiceVerdict:
    """Whose words the relied-on passage carries, and the evidence for saying so."""

    voice: str
    opinion_kind: str | None = None
    opinion_author: str | None = None
    cue: str | None = None
    cue_offset: int | None = None
    endorsed: bool | None = None
    method: str = "rule"  # opinion | rule | sequence | model | default
    reason: str | None = None
    needs_review: bool = False
    prompt_version: str | None = None

    @property
    def is_the_court(self) -> bool:
        """Whether the passage is this court speaking in its own voice, majority or concurring."""
        return self.voice in {"court_majority", "court_concurring"}

    @property
    def is_dissent(self) -> bool:
        return self.voice == "court_dissent"

    @property
    def is_problem(self) -> bool:
        """Whether relying on this passage as the court's holding is a misattribution (mode 5)."""
        if self.voice in NOT_THE_COURT:
            return True
        return self.voice == "quoted_precedent" and self.endorsed is not True


def _last_cue(pattern: re.Pattern[str], text: str) -> tuple[str, int] | None:
    """The last match of a pattern in the text, with its offset. Nearest cue governs what follows.

    The cue is reported with its whitespace collapsed, because a cue that straddles a line break in
    the PDF's text ("learned\\nAdvocate") is the same cue and should read as one in a finding.
    """
    found = None
    for match in pattern.finditer(text):
        found = (" ".join(match.group(0).split()), match.start())
    return found


def attribute_voice(
    candidate: Candidate,
    *,
    quote_start: int | None = None,
    model: StructuredModel | None = None,
) -> VoiceVerdict:
    """Decide whose words the relied-on sentence carries.

    `quote_start` is the offset of the verified quote inside the paragraph. When it is known, only the
    text before it is searched for cues, because a paragraph that recites a submission and then rejects
    it carries two voices and the one that governs is whichever spoke last before the sentence relied
    on. Without a quote the whole paragraph is searched, which is the weaker reading and is recorded
    as such.
    """
    opinion_kind = candidate.opinion_kind
    author = candidate.opinion_author

    # The publisher's headnote is not the court's text at all, and no cue can change that.
    if opinion_kind == "headnote":
        return VoiceVerdict(
            voice="headnote",
            opinion_kind=opinion_kind,
            method="opinion",
            reason="the passage is the reporter's editorial headnote, not the court's words",
        )

    prefix = candidate.body[:quote_start] if quote_start else candidate.body
    cues = {
        "counsel_argument": _last_cue(COUNSEL_CUES, prefix),
        "lower_court": _last_cue(LOWER_COURT_CUES, prefix),
        "quoted_precedent": _last_cue(QUOTED_PRECEDENT_CUES, prefix),
    }
    resumed = _last_cue(COURT_RESUMES_CUES, prefix)
    governing = max(
        ((voice, hit) for voice, hit in cues.items() if hit is not None),
        key=lambda item: item[1][1],
        default=None,
    )

    # The court answering an argument takes the paragraph back: a cue that comes before the court
    # resumes no longer governs the sentence relied on.
    if governing is not None and (resumed is None or governing[1][1] > resumed[1]):
        voice, (cue, offset) = governing
        verdict = VoiceVerdict(
            voice=voice,
            opinion_kind=opinion_kind,
            opinion_author=author,
            cue=cue,
            cue_offset=offset,
            method="rule",
            reason=f"the passage follows {cue!r}, so the words are not the court's own holding",
            needs_review=quote_start is None,
        )
        if voice == "quoted_precedent":
            _decide_endorsement(verdict, candidate, quote_start, model)
        return verdict

    # No attributing cue governs: the court is speaking. Which court, and in which opinion, is
    # structural rather than textual.
    if candidate.likely_quoted and opinion_kind != "dissenting":
        # The paragraph's printed number breaks the judgment's sequence, which is what a block quoted
        # from another judgment looks like when it brings its own numbering with it.
        verdict = VoiceVerdict(
            voice="quoted_precedent",
            opinion_kind=opinion_kind,
            opinion_author=author,
            method="sequence",
            reason=(
                "the paragraph's printed number breaks this judgment's sequence, so it is probably "
                "quoted from another judgment"
            ),
            needs_review=True,
        )
        _decide_endorsement(verdict, candidate, quote_start, model)
        return verdict

    voice = OPINION_VOICE.get(opinion_kind or "", "court_majority" if opinion_kind else "unclear")
    if voice == "unclear":
        return VoiceVerdict(
            voice="unclear",
            method="default",
            reason="the judgment's opinion boundaries are not known for this text version",
            needs_review=True,
        )
    # A paragraph that recites an argument and then answers it is the court's from the answer onward,
    # but only a verified quote says which half the brief leaned on. Without one, the safe answer is
    # the court's voice with the disagreement on the record, not a clean bill of health.
    mixed = governing is not None and quote_start is None
    return VoiceVerdict(
        voice=voice,
        opinion_kind=opinion_kind,
        opinion_author=author,
        cue=governing[1][0] if mixed else None,
        method="opinion",
        needs_review=mixed,
        reason=(
            (
                f"the paragraph carries more than one voice: it recites {governing[1][0]!r} before the "
                "court answers it, and no verified quote fixes which the brief relied on"
            )
            if mixed
            else (
                f"no cue attributes the passage to anyone else, and it falls in the {opinion_kind} "
                "opinion" + (f" of {author}" if author else "")
            )
        ),
    )


def _decide_endorsement(
    verdict: VoiceVerdict,
    candidate: Candidate,
    quote_start: int | None,
    model: StructuredModel | None,
) -> None:
    """Did this court adopt the words it quoted, or reject them?

    Quoted words may still be the law: a bench that quotes an earlier judgment with approval makes
    that passage its own. The text usually says which, and where it does the cue decides. Only when it
    does not is a model asked, and its answer changes the endorsement alone, never the voice.
    """
    after = candidate.body[quote_start:] if quote_start else candidate.body
    if REJECTS.search(after):
        verdict.endorsed = False
        verdict.reason = (verdict.reason or "") + "; this court rejected the passage it quoted"
        return
    if ADOPTS.search(after):
        verdict.endorsed = True
        verdict.needs_review = False
        verdict.reason = (verdict.reason or "") + "; this court quoted it with approval"
        return

    if model is None:
        verdict.needs_review = True
        return

    try:
        answer = model.invoke(
            VOICE_PROMPT.format(
                label=candidate.printed_label or f"#{candidate.seq}", paragraph=candidate.body
            )
        )
    except Exception as exc:  # noqa: BLE001 - a provider outage must not lose the rule-based finding
        verdict.needs_review = True
        verdict.reason = (verdict.reason or "") + (
            f"; whether this court adopted the quoted view could not be checked ({type(exc).__name__})"
        )
        return
    if not isinstance(answer, VoiceAssessment):
        verdict.needs_review = True
        return

    verdict.prompt_version = VOICE_VERSION
    if answer.endorsed is None:
        verdict.needs_review = True
        return
    verdict.endorsed = answer.endorsed
    verdict.method = "model"
    verdict.needs_review = not answer.endorsed
    if answer.reason:
        verdict.reason = (verdict.reason or "") + f"; {answer.reason}"


def relied_on(candidates: list[Candidate], matched_label: str | None) -> Candidate | None:
    """The paragraph a verdict should be about.

    Only two paragraphs are ever definite enough to attribute: the one holding a quote that verified
    against the stored text, and the one the brief itself pinpointed. A paragraph that merely ranked
    highest is a guess, and labelling a guess as a dissent would produce exactly the confident-and-wrong
    output this engine exists to prevent.
    """
    if matched_label:
        found = next((c for c in candidates if c.printed_label == matched_label), None)
        if found is not None:
            return found
    return next((c for c in candidates if c.is_claimed_pinpoint), None)
