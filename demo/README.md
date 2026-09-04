# Demo

Two runs. Both use the real knowledge base, so import the data first:

```bash
source scripts/dev-env.sh
uv run orderorder ingest metadata 2019 2024 2025
uv run orderorder ingest text INSC:2019:770 INSC:2024:1027 INSC:2024:1051 INSC:2025:1045
```

### 1. A brief, verified

```bash
uv run orderorder verify --file demo/brief.txt
```

Eight citations, six of them wrong in six different ways. See [expected.md](expected.md) for what each
one is and what the engine should say about it.

This run needs **no API key**: existence, mis-citation, pinpoint, voice and opinion are all decided
from the corpus and from the judgment's own text. Extent of support is the one question that needs a
language model, and with none configured the engine reports it as *not assessed* rather than guessing.

### 2. The third question

```bash
uv run python demo/scripted_model.py
```

Extent of support, with the model's answer scripted instead of generated, so the check runs on a
machine with no provider key. The engine is real throughout — real judgment text, real quote
verification, real grading. Four answers go in, two of them confident and wrong, and the engine
catches both by string-matching the quote against the stored judgment.

### 3. Finding an authority, with no citation to start from

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

To run the model-dependent checks for real, put any one of these in `.env`:

```
GOOGLE_API_KEY=...      # or GROQ_API_KEY, or CEREBRAS_API_KEY — all have free tiers
```

or run a local model with no key at all:

```bash
OLLAMA_MODELS=data/ollama ollama serve
ollama pull qwen3.5:4b
uv run orderorder doctor          # should now show ollama usable
```
