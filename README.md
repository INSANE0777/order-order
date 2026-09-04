# OrderOrder

*A self-hosted citation-integrity engine for Indian case law.*

OrderOrder reads a brief, moot-court memorial or written submission, finds every case-law citation, and answers three questions separately for each one: does the case exist, which paragraph is being relied on, and does that paragraph support the proposition **to the extent claimed**. It then writes what opposing counsel would say. The same engine gates a drafting assistant so that nothing enters a written submission that the verifier could not confirm.

It is built on open and official data (AWS Open Data judgments under CC-BY-4.0, the Supreme Court's SCR portal, the Indian Kanoon API with attribution). The hackathon build costs nothing and runs on free tiers with demo data only; in production everything runs on hardware the team controls.

## Documents

| Document | Read it for |
|---|---|
| [docs/PRD.md](docs/PRD.md) | The problem, the evidence that it is urgent, users, the twelve ways a citation lies, requirements for both surfaces, metrics, competition, risks, compliance |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design with nine diagrams: ingestion, the verification engine, the drafting engine, retrieval hierarchy, data model, verdict schema, deployment, evaluation |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | The zero-cost hackathon stack and the self-hosted production stack, how LangChain and LangGraph are used, free-tier limits and data terms, licence audit, dev-machine setup, bill of materials |
| [docs/ROADMAP.md](docs/ROADMAP.md) | The 10-day hackathon sprint with demo script and cut list, then the startup phases, team split, decision log |

Suggested reading order: PRD §1-6, then ARCHITECTURE §1-4, then TECH_STACK §4, §5 and §12, then ROADMAP §1.

## Running it

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12. Every cache, the interpreter and the
virtualenv are pointed at one data directory by the environment script, to keep them off the system drive.

```bash
source scripts/dev-env.sh        # PowerShell: . .\scripts\dev-env.ps1
uv sync                          # installs into data\venv
cp .env.example .env             # optional; defaults work for everything below

uv run orderorder doctor                          # check the environment
uv run orderorder init-db                         # create tables (SQLite by default)
uv run orderorder ingest metadata 2019 2020 2021  # download and import a few years
uv run orderorder stats

uv run orderorder cite parse "Kesavananda Bharati v. State of Kerala, (1973) 4 SCC 225, para 316"
uv run orderorder resolve "[2019] 9 S.C.R. 593"

uv run orderorder ingest text INSC:2019:770          # fetch the official PDF, clean and segment it
uv run orderorder locate INSC:2019:770 "the plaintiff is the dominus litis" --pinpoint 73

uv run orderorder verify --file brief.txt            # every citation in a brief
```

`verify` is the whole engine: it finds each citation, resolves it, loads the judgment, ranks the
paragraphs, asks how far they support the claim, and grades the result. Extent of support needs a
language model; the other checks do not, and the command says so rather than staying silent.

`uv run pytest` runs the suite; it uses an in-memory database and never touches the network.

### What works today

All three questions the product asks about a citation: **does the case exist**, **which paragraph is
being relied on**, and **does that paragraph support the claim to the extent claimed**. Between them
these detect failure modes 1, 2, 4, 8, 9 and 12 from the taxonomy in [docs/PRD.md](docs/PRD.md), with
a first signal on 5. Only the third needs a language model.

**The model is never believed, only checked.** It is asked to name a paragraph and copy a sentence
from it. That sentence is then string-matched against the stored judgment. A quote that does not match
downgrades the claim to unsupported and flags it, however confident the model was. Born-digital text
never fuzzy-matches, so a near-miss paraphrase fails too. This is ordinary Python and it runs whatever
model produced the answer, which is why the tests can exercise it with a stub and no API key.

Three states are kept apart, because collapsing them is how tools overclaim: **supported**,
**checked and not supported**, and **not checked**. A missing API key, a provider outage or a
retrieval miss produces the third, never the second.

| Piece | Module |
|---|---|
| Citation grammar for SCC, SCC OnLine, AIR, SCR, SCALE, JT, INSC, High Court neutral citations and Indian Kanoon IDs, with pinpoints and party names | `citations/grammar.py` |
| Corpus client for the AWS Open Data bucket (anonymous HTTP, no AWS account) | `ingest/corpus.py` |
| Metadata import into `judgment` and `citation_alias` | `ingest/metadata.py` |
| Resolver: exact alias match, then fuzzy party names | `resolver.py` |
| Reports PDF cleaning: margin letters, running headers, the editorial headnote, the coram and the authoring judge | `ingest/pdf.py` |
| Paragraph segmentation with printed labels, sub-labels and offsets | `ingest/segment.py` |
| Persistence of text versions, opinions and paragraphs | `ingest/store.py` |
| BM25 ranking inside a judgment, and the fusion seam for embeddings | `engine/lexical.py` |
| Locator and pinpoint checking | `engine/locator.py` |
| Quote verifier, the quote-or-nothing rule | `engine/quotes.py` |
| Scope comparator: extent of support, dropped conditions, a narrowed proposition | `engine/scope.py` |
| Model providers with fallbacks across free tiers | `engine/providers.py` |
| Verdict assembly and the grading rubric | `engine/verdict.py` |
| The engine as a LangGraph state graph | `engine/graph.py` |

Measured on the real corpus:

- Importing 2019 to 2024 takes about 15 seconds and yields roughly 5,000 judgments and 9,900 citation
  aliases, with every citation in the source parsed by the grammar.
- Fetching and parsing a judgment's official PDF takes two to three seconds; a 51-page judgment
  segments into 118 paragraphs.
- A citation to a paragraph the judgment does not have is reported as such, which is the Delhi High
  Court failure of September 2025.

Two things the corpus does not tell you, which the PDF does. The metadata's judge column names only
the **presiding** judge, so bench strength arrives under-counted; the coram printed on the judgment is
read instead, because bench strength decides which precedents bind which. And the Reports open with an
**editorial headnote**, which is the publisher's summary rather than the court's words; it is stored
separately and never used as the text a pinpoint resolves against.

### Not built yet

Embeddings and hybrid retrieval, voice and weight classification (ratio versus obiter), the citator
for overruled judgments, the fact comparator, the drafting surface and the web app. See
[docs/ROADMAP.md](docs/ROADMAP.md).

## Status

Documents complete; the data spine and resolver are working. Started 4 September 2026.

## Attribution

Judgment data from the [Indian Supreme Court Judgments](https://registry.opendata.aws/indian-supreme-court-judgments/) and [Indian High Court Judgments](https://registry.opendata.aws/indian-high-court-judgments/) datasets on AWS Open Data (CC-BY-4.0). Lookups powered by [IKanoon](https://api.indiankanoon.org/) where indicated.

*OrderOrder is a research aid. The advocate remains responsible for every citation filed.*
