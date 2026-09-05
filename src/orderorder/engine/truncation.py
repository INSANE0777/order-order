"""The sentence cut before the words that matter.

Failure mode 9. A court writes:

    The stage to appreciate the evidence would arise only when the prosecution leads evidence by
    examining the doctors in support of the medical reports.

and a brief quotes:

    The stage to appreciate the evidence would arise.

Everything quoted is the court's, word for word. What the brief did was stop.

The scope comparator finds this with a model, and reports it as an overstatement — which it is, and
the model names the dropped condition well. But truncation is a string operation, and where it can be
proved by string comparison it should be: a long run of the court's sentence appears in the brief
word for word, the rest of that sentence carries a qualifier, and nothing has to be believed. That gives
the finding its own number rather than folding it into mode 8, it works with no model configured, and
it names the exact words the brief left out rather than describing them.

The run is matched from the sentence's side rather than the brief's, because a brief's sentence
carries framing and the citation itself — "It is submitted that X, as held in (2019) 4 SCC 1, para
7" — and only the middle of it is the quotation. Asking how much of the *court's* sentence appears in
the brief's finds that middle without having to guess where it starts and stops.

What this cannot see is a brief that quotes the first half and states the qualification in its own
words in the next sentence, which is honest and common. The proposition this check gets is the
sentence carrying the citation and no more, so the finding is offered as what it is: the qualifier is
not in the sentence that cites the case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orderorder.engine.quotes import longest_shared_run, normalized
from orderorder.engine.sentences import split_sentences
from orderorder.ingest.segment import SegParagraph

# The words a court attaches a rule to, and a brief drops. Every one of them narrows what precedes it,
# which is why cutting immediately before one changes the proposition rather than shortening it.
QUALIFIER = re.compile(
    r"(?i)\b("
    r"only\s+(?:where|when|if|in|upon|after|to\s+the\s+extent)"
    r"|unless|provided\s+that|subject\s+to|except\s+(?:where|when|in)"
    r"|so\s+long\s+as|as\s+long\s+as|in\s+the\s+facts\s+(?:and\s+circumstances\s+)?of"
    r"|having\s+regard\s+to|save\s+(?:where|in)|but\s+only|and\s+not\s+otherwise"
    r"|if\s+and\s+only\s+if|on\s+condition\s+that|in\s+cases\s+where"
    r")\b"
)

# How much of the court's sentence has to appear in the brief before this is a quotation at all.
MIN_KEPT_WORDS = 8
# And how much has to be missing before stopping there is a choice rather than an ellipsis.
MIN_DROPPED_WORDS = 4


@dataclass
class Truncation:
    """A sentence the brief kept the front of."""

    paragraph_label: str | None
    kept: str
    dropped: str
    qualifier: str

    @property
    def note(self) -> str:
        return (
            f"the brief quotes the court as far as {self.kept!r} and stops; the sentence continues "
            f"{self.dropped!r}, which qualifies it"
        )


def find_truncation(proposition: str, paragraphs: list[SegParagraph]) -> Truncation | None:
    """The court's sentence the brief quoted part of and stopped, if there is one.

    The run is looked for anywhere in the sentence, not only at its start, because a brief quotes the
    middle. The sentence that prompted this begins "Without adverting much into its pith and
    substance, it is ubiquitous that..." and no brief carries that; what a brief carries is the rule
    in the middle, and the "unless" clause at the end is what it leaves behind.

    Silence otherwise, and silence is the common case: a brief that paraphrases has no verbatim run to
    find, and a brief that quotes to the end of a sentence has dropped nothing.
    """
    claim = normalized(proposition)
    if not claim:
        return None

    for paragraph in paragraphs:
        for sentence, _offset in split_sentences(paragraph.body):
            body = normalized(sentence)
            if len(body.split()) < MIN_KEPT_WORDS + MIN_DROPPED_WORDS:
                continue
            # Runs of the *court's* sentence that appear in the brief. Asked the other way round the
            # answer would include the brief's own framing and the citation, which are not quotation.
            kept = longest_shared_run(sentence, proposition)
            if kept.words < MIN_KEPT_WORDS:
                continue
            position = body.find(kept.text)
            if position < 0:
                continue
            dropped = body[position + len(kept.text) :].strip()
            if len(dropped.split()) < MIN_DROPPED_WORDS:
                continue
            match = QUALIFIER.search(dropped)
            # The qualifier has to be missing from the brief as well as present in the judgment: a
            # brief that kept it and merely reordered the sentence has dropped nothing.
            if match and match.group(0) not in claim:
                return Truncation(
                    paragraph_label=paragraph.printed_label,
                    kept=kept.text,
                    dropped=dropped,
                    qualifier=match.group(0),
                )
    return None
