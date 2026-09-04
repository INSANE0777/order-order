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
```

`uv run pytest` runs the suite; it uses an in-memory database and never touches the network.

### What works today

The data spine and the resolver, which together detect the first two failure modes in the taxonomy:
a citation that does not exist, and a citation attached to the wrong case.

| Piece | Module |
|---|---|
| Citation grammar for SCC, SCC OnLine, AIR, SCR, SCALE, JT, INSC, High Court neutral citations and Indian Kanoon IDs, with pinpoints and party names | `src/orderorder/citations/grammar.py` |
| Corpus client for the AWS Open Data bucket (anonymous HTTP, no AWS account) | `src/orderorder/ingest/corpus.py` |
| Metadata import into `judgment` and `citation_alias` | `src/orderorder/ingest/metadata.py` |
| Resolver: exact alias match, then fuzzy party names | `src/orderorder/resolver.py` |
| Quote verifier, the quote-or-nothing rule | `src/orderorder/engine/quotes.py` |
| Paragraph segmentation with printed labels and offsets | `src/orderorder/ingest/segment.py` |

Importing 2019 to 2024 takes about 15 seconds and yields roughly 5,000 judgments and 9,900 citation
aliases, with every citation in the source parsed by the grammar.

### Not built yet

Judgment text ingestion, embeddings and hybrid retrieval, the locator, the scope comparator, the
citator, the LangGraph assembly of the engine, and both web surfaces. See
[docs/ROADMAP.md](docs/ROADMAP.md).

## Status

Documents complete; the data spine and resolver are working. Started 4 September 2026.

## Attribution

Judgment data from the [Indian Supreme Court Judgments](https://registry.opendata.aws/indian-supreme-court-judgments/) and [Indian High Court Judgments](https://registry.opendata.aws/indian-high-court-judgments/) datasets on AWS Open Data (CC-BY-4.0). Lookups powered by [IKanoon](https://api.indiankanoon.org/) where indicated.

*OrderOrder is a research aid. The advocate remains responsible for every citation filed.*
