"""Prompts, versioned.

Every verdict records the prompt version that produced it, so a change in wording is visible in the
audit trail and old verdicts can be told apart from new ones. Two rules run through all of them:

  * the model may only use the text it is given, never anything it remembers about the case
  * when the text does not contain the answer, the required answer is "not there"

The prompts ask for a verbatim quote because the quote is what gets checked. The model is told this
explicitly, since a model that knows its quote will be verified is less inclined to approximate one.
"""

from __future__ import annotations

from orderorder.engine.lexical import tokenize
from orderorder.engine.sentences import split_sentences

DECOMPOSE_VERSION = "decompose-v1"
DECOMPOSE_PROMPT = """You are helping check whether a legal brief's citations are sound.

Split the proposition below into the separate assertions it makes. An assertion is one thing that
could independently be true or false about the law.

Rules:
- Use only the words of the proposition. Do not add legal knowledge of your own.
- Do not merge two assertions into one, and do not invent assertions that are not there.
- If the proposition makes a single assertion, return exactly one.
- Record any condition the proposition itself attaches ("where the contract was induced", "in a
  commercial dispute").
- Record how strongly it is put: must, may, should, or merely observed.
- Record how broadly it is put, if it says: for example "all commercial contracts".

Proposition:
{proposition}
"""

SCOPE_VERSION = "scope-v1"
SCOPE_PROMPT = """You are opposing counsel checking whether a judgment supports a claim made in a brief.

The claim, taken from the brief:
{claim}

Numbered paragraphs from the judgment. This is the ONLY text you may rely on. You have no other
knowledge of this case, and anything you seem to remember about it must be ignored:

{candidates}

Decide how far these paragraphs support the claim.

- If a paragraph states the claim as broadly as the brief does, that is "full".
- If it states the claim but more narrowly, or only in particular circumstances, that is "partial".
  Name the conditions the court attached that the brief leaves out.
- If no paragraph states the claim, that is "none". Do not stretch a paragraph to fit.
- If a paragraph states the opposite, that is "contradicted".

If you answer "full" or "partial", you must quote the sentence that carries the claim, copied word for
word from the paragraph you name, at least six words long. The quote is checked against the judgment
automatically; a quote that is remembered, tidied or paraphrased will fail that check and the claim
will be recorded as unsupported. If you cannot copy such a sentence, answer "none".

Be exacting. A brief that overstates a holding is the specific problem this check exists to catch.
"""

VOICE_VERSION = "voice-v1"
VOICE_PROMPT = """Decide whose words this paragraph of a judgment carries.

A paragraph inside a judgment is not always the court's own view. It may summarise an advocate's
argument ("learned counsel submitted"), restate what the court below held, quote another judgment, or
be an editorial headnote written by the publisher rather than the court.

Paragraph {label}:
{paragraph}

Answer with the voice. If the paragraph quotes another source, also say whether this court adopted
that source's view or rejected it.
"""

WEIGHT_VERSION = "weight-v1"
WEIGHT_PROMPT = """Decide whether a statement in a judgment was necessary to the court's decision.

A court's reasoning binds later courts only so far as it was necessary to the outcome. Everything else
is a remark made along the way: it may be persuasive, but a brief that cites it as the holding is
overstating what the judgment decided.

The claim the brief attributes to this passage:
{claim}

Paragraph {label} of the judgment. This is the ONLY text you may rely on:
{paragraph}

{disposition}

Answer "ratio" if the court's decision would have to change without this statement. Answer "obiter" if
the decision stands without it: an aside, an observation about a question not before the court, a view
expressed while expressly declining to decide the point. Answer "unclear" if this paragraph alone does
not show which, and do not guess.

If you answer "ratio" or "obiter", quote the sentence that shows it, copied word for word from the
paragraph, at least six words long. The quote is checked against the judgment automatically, and an
answer whose quote cannot be found is recorded as unclear.
"""


APPLICABILITY_VERSION = "applicability-v1"
APPLICABILITY_PROMPT = """You are opposing counsel deciding whether a cited authority actually governs
the matter before the court.

The claim the brief makes, and the authority it cites for it:
{claim}

The facts of the matter now before the court:
{facts}

Paragraphs from the cited judgment. This is the ONLY text you may rely on for what that case decided,
and anything you seem to remember about it must be ignored:

{candidates}

A case governs a later matter through its facts. Decide how far it governs these.

- "strong" if the facts it turned on are present here.
- "moderate" if it applies with adjustment.
- "weak" if it is only analogous.
- "inapplicable" if a fact the cited case turned on is materially absent here, or is different in a
  way that mattered to the decision.

If you answer "inapplicable", you must name that fact and quote the sentence of the judgment that
states it, copied word for word from the paragraph you name, at least six words long. The quote is
checked against the judgment automatically, and an answer whose quote cannot be found will not be
recorded as inapplicable.

Be exacting in both directions. Calling a good authority inapplicable costs an advocate a case they
were entitled to win; calling a distinguishable one applicable is the mistake this check exists to
catch.
"""


def _anchor(body: str, claim: str) -> int:
    """Where in the paragraph the claim is most likely to be answered."""
    wanted = set(tokenize(claim))
    if not wanted:
        return 0
    best = (0.0, 0)
    for sentence, offset in split_sentences(body):
        terms = set(tokenize(sentence))
        if not terms:
            continue
        overlap = len(wanted & terms)
        if overlap:
            # Density, not count, so a long sentence does not win by carrying more words.
            score = overlap + overlap / len(terms)
            if score > best[0]:
                best = (score, offset)
    return best[1]


def _window(body: str, claim: str | None, max_chars: int) -> str:
    """A readable slice of a long paragraph, taken around the part that answers the claim.

    Trimming from the front is what this used to do, and it produced the worst kind of wrong answer.
    A judgment paragraph that runs past the limit — they do, when the court sets out a statute or
    quotes at length — had its tail cut off, and where the supporting sentence was in that tail the
    model reported the claim as unsupported by a judgment that supports it. It said so plainly in one
    eval run: "the provided paragraph 38 is truncated at the exact point of the charge". The model was
    right and the engine had handed it a mutilated paragraph.
    """
    if len(body) <= max_chars:
        return body
    if not claim:
        return body[:max_chars].rstrip() + " [...]"

    anchor = _anchor(body, claim)
    start = max(0, anchor - max_chars // 3)
    end = min(len(body), start + max_chars)
    start = max(0, min(start, len(body) - max_chars))
    # Whole sentences: a window that begins mid-clause reads as a different claim.
    if start:
        boundary = body.find(" ", start)
        start = boundary + 1 if 0 <= boundary < start + 120 else start
    text = body[start:end].strip()
    return ("[...] " if start else "") + text + (" [...]" if end < len(body) else "")


def format_candidates(
    candidates: list[tuple[str, str]], *, max_chars: int = 1800, claim: str | None = None
) -> str:
    """Render (label, body) pairs for a prompt, trimming very long paragraphs around the claim."""
    blocks = []
    for label, body in candidates:
        blocks.append(f"[paragraph {label}]\n{_window(body, claim, max_chars)}")
    return "\n\n".join(blocks)
