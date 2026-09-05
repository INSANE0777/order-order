# Demo

Everything here runs against the real knowledge base, so import the data first:

```bash
source scripts/dev-env.sh
uv run orderorder ingest metadata 2019 2024 2025
uv run orderorder ingest text INSC:2019:770 INSC:2024:1027 INSC:2024:1051 INSC:2025:1045
```

### 1. A brief, verified

```bash
uv run orderorder verify --file demo/brief.txt --no-model
```

Ten citations, eight of them wrong in eight different ways. See [expected.md](expected.md) for what
each one is and what the engine should say about it.

`--no-model` holds the engine to the checks that need none, so the claim below is testable even on
a machine that has a key configured. This run needs **no API key**. Eight of the twelve failure modes are settled by the record and by the
structure of the judgment — whether the case exists, whether the citation names it, who decided it
and how many judges sat, whose words a paragraph carries, what later courts did with it, whether the
pinpointed paragraph is where the words are, and whether a quotation was stopped before its
qualification. Extent of support is the one thing a key changes, and with none configured the engine
reports it as *not assessed* rather than guessing.

Watch citation 8. Every word the brief quotes is the court's, in order, exactly — and it stops before
"unless the court is satisfied that the party has not approached it with clean hands", which reverses
the proposition in the only case where the point arises. No model is asked; the sentence is compared
with the sentence.

### 2. What the other side will say

```bash
uv run orderorder verify --file demo/brief.txt --memo
```

The same verdicts written as the argument they will meet — "My friend is citing the dissent", "That
case has been overruled and my friend cites it as though it were good law" — each with the fact from
the verdict that makes it stick and the fix that closes it off. The memo is built from the verdict
object and nothing else, so it cannot claim more than was proved, and it works with no key.

It also says what *held up*, and what was **not checked**. A short list of problems reads as a clean
bill of health, and a citation nobody could assess is not a citation that passed.

### 3. The work handed back

```bash
uv run orderorder verify --file demo/brief.txt --annotate flagged.txt --report report.md
```

`flagged.txt` is the brief with a marker beside every citation — `[!D 12]` for a finding, `[?C]` where
a person has to look, `[ok]` where nothing was found — and a key at the foot. `report.md` is the board
and then every citation in full, worst first.

### 4. The third question

```bash
uv run python demo/scripted_model.py
```

Extent of support, with the model's answer scripted instead of generated, so the check runs on a
machine with no provider key. The engine is real throughout — real judgment text, real quote
verification, real grading. Four answers go in, two of them confident and wrong, and the engine
catches both by string-matching the quote against the stored judgment.

### 5. Finding an authority, with no citation to start from

```bash
uv run orderorder ingest bulk-text     # text for the whole corpus; resumable, ~0.4s a judgment
uv run orderorder index                # full-text index over every paragraph
uv run orderorder find "a misrepresentation vitiates consent only where it induced the contract"
```

The other direction: a lawyer has a proposition and needs a judgment to put behind it. Search returns
ranked authorities, each with the paragraph and the sentence to read, and refuses to offer a passage
that is not the court speaking — an advocate's submission matches a proposition's words better than a
holding does, because it is stated without the qualifications.

Also no API key. With one configured, each authority is run back through the verifier, so a candidate
whose words match is separated from one that supports the claim.

### 6. Arguing forwards: a proposition, bound to authority or refused

```bash
uv run orderorder argue demo/propositions.txt
```

The drafting half. Four propositions someone intends to argue, with no citations. For each one the
corpus is searched, the candidates are put through the same verifier that checks a brief, and a gate
decides whether any of them may be cited: the court's own words, the majority, still good law, and a
quote that verifies word for word.

Three things come back for each proposition — the pinpoint, the quote, and, where the court put it
more narrowly than the advocate did, **the proposition to argue instead**:

```
    NARROWED  The plaintiff is dominus litis and cannot be compelled to add a party
              against whom he does not want to fight.
    [2018] 1 S.C.R. 806, para 17
    KANAKLATA DAS & ORS. versus NABA KUMAR DAS & ORS.
    verified: "the plaintiff being a dominus litis cannot be compelled to make any third
               person a party to the suit ... unless such person is able to prove that he
               is a necessary party"
    argue instead: The plaintiff cannot be compelled to add a third person against his wish
                   unless that person proves he is a necessary party.
```

What was rejected is listed with the reason, which is where the next hour of research starts. Without
a key nothing can be *bound* — the gate can still check voice, opinion and treatment, and offers the
line to read, marked unchecked.

### 7. A written submission, assembled

```bash
uv run orderorder draft demo/plan.txt --docx submission.docx --markdown submission.md
```

[plan.txt](plan.txt) is the advocate's: the court, the parties, the list of dates, the issues, the
propositions they mean to argue, the prayer. Everything except the authorities, which is what this
adds — each proposition goes through the same gate as `argue`, and what comes out is a written
submission in the format it would be filed in.

What to look at is the sentences that found nothing. They are still there, in place, in red in the
Word file, because a draft that quietly drops its unsupported propositions reads as though every
sentence in it is supported, and that is the document the other half of this tool exists to catch.
The list of authorities is built from what was verified and can contain nothing else, so the two
cannot drift apart. The appendix gives the paragraph, the subsequent history and the verified words
behind every citation, plus what was considered and rejected for the ones that failed — which is where
the next hour of research starts.

The last section is the draft attacking itself. Everything in the document passed the gate, so what
is left is what the gate cannot check: a case a later court held inapplicable on its facts, a larger
or later bench on the same words that the draft does not cite, an authority nobody has cited since.
All of it from the citation graph, so it needs no key, and the section ends by saying what it did not
look at — whether any of these authorities governs *these* facts, which no amount of retrieval can
answer.

### 8. All of it, in a browser

```bash
uv run orderorder serve
```

Three tabs. Paste a brief or open one from a PDF or DOCX. The verdict board, the annotated brief and
the judgment viewer on one page — which is the point of having a page at all, since each exists as
text already. Click a citation, read the paragraph the engine actually read, and see the verified
sentence highlighted inside it. The second tab is the search direction. The third is the drafting
workspace: paste the plan, watch each proposition bind or refuse as it is decided, read the assembled
submission and the self-attack beside it, and download the .docx.

Two details worth watching. The board fills as each citation is decided rather than all at once, so a
phantom citation is on screen while the ones that need a model are still running. And a grade earned
with checks that could not run gets a hollow badge rather than a solid one: nothing was found against
it, but not everything was asked, and on a board read at a glance the badge has to say so.

### 9. The numbers

None of the three directions is worth much unmeasured, and all three are measured against ground
truth the corpus supplies rather than labels anyone wrote:

```bash
uv run orderorder eval generate --seeds 40 --rng-seed 1729 --out evals/holdout.jsonl
uv run orderorder eval run --no-model --detail --gold evals/holdout.jsonl
uv run orderorder eval search --judgments 40
uv run orderorder eval gate --judgments 40 --no-model
```

The first plants known failures in forty judgments *the detectors were not developed against* — the
set they were fixed on cannot measure them. The second scores every check that needs no model, in
seconds. The third asks the search direction: given a line, does the corpus give back the judgment,
the paragraph, and the line. The fourth asks the drafting direction, and asks it about the traffic
rather than the detector: how much of what a word search puts in front of a lawyer is something
nobody may cite, and what happens to it on the way into a draft.

Current numbers and, more importantly, what they do not say are in
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) §11.4.

---

To run the model-dependent checks for real, put any one of these in `.env`:

```
GOOGLE_API_KEY=...      # or GROQ_API_KEY, or CEREBRAS_API_KEY — all have free tiers
```

or run a local model with no key at all:

```bash
OLLAMA_MODELS=data/ollama ollama serve
ollama pull qwen3.5:4b
uv run orderorder doctor          # should now show ollama configured
uv run orderorder doctor --probe  # and that something answers, with a filled schema not prose
```

`qwen3:4b` answers correctly on a CPU-only laptop — filled schema, quote verifies — but it answers
slowly: 247 seconds a call on four cores with 16 GB of RAM, two thirds of which is the model reading
the prompt while the machine pages. Use it to prove the wiring works. Use a hosted key, or a rented
GPU, to run a brief.
