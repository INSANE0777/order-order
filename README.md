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
uv run orderorder verify --file brief.txt --facts matter.txt   # ... and whether each one applies
uv run orderorder verify --file brief.txt --memo     # ... and what the other side will say
uv run orderorder verify --file brief.txt --annotate flagged.txt --report report.md

uv run orderorder ingest bulk-text                   # text for the whole corpus; resumable
uv run orderorder ingest aliases                     # learn the SCC citations the open data omits
uv run orderorder ingest repair-trailers             # cut the reporter's own words out of stored text
uv run orderorder index                              # full-text index over every paragraph
uv run orderorder citator                            # who cited whom, and what they did with it
uv run orderorder find "a misrepresentation vitiates consent only where it induced the contract"
uv run orderorder argue propositions.txt             # bind each proposition to an authority, or refuse
uv run orderorder treatment INSC:2019:770            # is this authority still good law?

uv run orderorder eval generate --seeds 40 --rng-seed 1729   # plant known failures in real judgments
uv run orderorder eval run --no-model --detail               # score every check that needs no model
uv run orderorder eval search --judgments 40                 # score the other direction
```

The engine runs in two directions.

`verify` starts from a citation the brief already gives. It resolves it, loads the judgment, ranks the
paragraphs, asks how far they support the claim, works out whose words the relied-on paragraph carries
and whether they decided anything, and grades the result. Extent of support and ratio-versus-obiter
need a language model; the other checks do not, and the command says so rather than staying silent.

`find` starts from a proposition and no citation, which is where a lawyer preparing arguments actually
starts. It searches every paragraph of every judgment held, drops anything that is not the court
speaking, weighs bench strength and recency beside relevance, and names the sentence to read. With a
model configured it then runs each authority back through `verify`, because retrieval proposes and
only the verifier confirms.

`argue` is the two of them composed, and is the drafting surface's gate. For each proposition a
lawyer intends to advance it searches, verifies, and then refuses everything that is not the court's
own words, from the majority, still good law, and quoted verbatim. Where the court put the point more
narrowly than the advocate did, it returns the authority *and the proposition to argue instead*.

`uv run pytest` runs the suite; it uses an in-memory database and never touches the network.

### What it scores

The engine is measured in both directions, against ground truth the corpus supplies rather than labels
anyone wrote, on **forty judgments the detectors were not developed against**. The set they were fixed
on cannot measure them, so every number here is from a held-out draw.

Verification, 270 planted items, **no model configured**:

| mode | | recall |
|---|---|---|
| 1 | phantom | 40/40 |
| 2 | mis-cite | 40/40 |
| 3 | wrong court or bench | 39/39 |
| 5 | wrong voice | 34/34 |
| 9 | selective quotation | 20/20 |
| 10 | dead or wounded law | 14/14 |
| 12 | wrong pinpoint | 40/40 |
| | **false positives on clean citations** | **0/40** |

With a model, over the modes that need one and 25 clean citations: obiter as ratio 3/3, false
positives 0/25, **quote grounding 100%**, abstention 68%, six seconds a citation.

Search, 148 queries over all 409,499 paragraphs:

| query | case@1 | case@5 | para@5 | line |
|---|---|---|---|---|
| the line, verbatim | 91% | 99% | 99% | 100% |
| a remembered fragment | 81% | 91% | 85% | 100% |

Once the right paragraph is found, the sentence named as the line is the one the proposition came from
every time. What these numbers do not say — and the limits matter more than the figures — is set out
in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §11.4.

### What works today

All three questions the product asks about a citation: **does the case exist**, **which paragraph is
being relied on**, and **does that paragraph support the claim to the extent claimed** — and, once a
paragraph is fixed, **whose words they are** and **whether they carried the decision**. Between them
these detect **all twelve** failure modes in the taxonomy in [docs/PRD.md](docs/PRD.md). Eight of the
twelve are decided without a language model at all, which is why the whole of the demo above runs on a
laptop with no key configured.

And the same machinery run backwards: **given a proposition and no citation, which judgment backs it,
and which line**. Search drops any passage that is not the court speaking before it ever reaches the
lawyer, so the tool cannot suggest as authority the kind of passage the verifier exists to catch.

**The model is never believed, only checked.** It is asked to name a paragraph and copy a sentence
from it. That sentence is then string-matched against the stored judgment. A quote that does not match
downgrades the claim to unsupported and flags it, however confident the model was. Born-digital text
never fuzzy-matches, so a near-miss paraphrase fails too. This is ordinary Python and it runs whatever
model produced the answer, which is why the tests can exercise it with a stub and no API key.

Three states are kept apart, because collapsing them is how tools overclaim: **supported**,
**checked and not supported**, and **not checked**. A missing API key, a provider outage or a
retrieval miss produces the third, never the second.

**A passage inside a judgment is not automatically the court's holding.** It may be counsel's
submission recited by the bench, the court below being quoted, an earlier judgment quoted, the
publisher's headnote, or the dissent. Whose words they are is decided from the judgment's own
structure and from attributing cues in the text — never from a model — and the cue that governs is the
last one before the sentence actually relied on, because a paragraph routinely sets out an argument
and then rejects it. The finding names the cue, so a reader can check it against the judgment. This
check needs no API key: a brief pinpointing a dissent is caught with nothing configured at all.

Ratio and obiter are told apart the same way where the court says so in terms ("it is not necessary
for us to decide"), and otherwise by a model whose answer must quote the sentence that shows it. An
answer that cannot be grounded becomes `unclear`, which costs a citation nothing. Calling a holding a
passing remark is as damaging as the reverse, so the classifier abstains rather than guesses.

**And a citation can be sound in every one of those respects and still be dead law.** The citator
reads every judgment's citations of every other, and what the citing court did with each: followed,
distinguished, doubted, overruled. One rule there is arithmetic rather than language — a bench cannot
overrule one at least as large as itself, so two judges saying a three-judge decision "does not lay
down the correct law" are recorded as having doubted it, with the claim attached. Reporting an
overruling that did not happen would have an advocate drop a binding authority.

The treatment report always states how many judgments it searched, because "no negative treatment
found" over nine thousand judgments means something different from the same words over the full
seventy-five years — and 56% of the citations these judgments make are to cases decided before 2013,
which the corpus does not yet hold.

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
| Voice and opinion: counsel's argument, the court below, a quoted precedent, the headnote, the dissent | `engine/voice.py` |
| Weight: ratio versus obiter, with abstention as the default | `engine/weight.py` |
| Sentence boundaries that survive "Kasturi v. Iyyamperumal" and "[2019] 9 S.C.R. 593" | `engine/sentences.py` |
| Corpus-wide authority search: which judgment backs a proposition, and which line | `engine/search.py` |
| The citator: treatment of one judgment by later ones, and the bench-strength rule | `engine/citator.py` |
| Court and bench attribution: what the brief claims against what the record says | `engine/hierarchy.py` |
| Applicability: whether the cited case governs the facts of this matter | `engine/facts.py` |
| Resumable bulk text ingestion for the whole corpus | `ingest/bulk.py` |
| Learning the reporter citations the open data omits, from how judgments cite each other | `ingest/aliases.py` |
| Model providers with fallbacks across free tiers | `engine/providers.py` |
| Selective quotation: the sentence cut before its qualification, by string comparison | `engine/truncation.py` |
| The opposing-counsel memo, written from the verdict object and nothing else | `engine/memo.py` |
| The annotated brief and the verification report | `engine/report.py` |
| The drafting gate: bind a proposition to an authority, or refuse to | `engine/authority.py` |
| Verdict assembly and the grading rubric | `engine/verdict.py` |
| The engine as a LangGraph state graph | `engine/graph.py` |
| The evaluation harness: plant known failures, score both directions | `evaluation/` |
| Repairs to stored text when extraction is corrected after the fact | `ingest/repair.py` |

Measured on the real corpus, which is now the whole of it:

| | |
|---|---|
| Judgments (2013-2025) | 9,429 |
| Citation aliases | 20,778, of which 1,870 learned from the corpus itself |
| Judgments with full text | 9,424 (99.95%) |
| Paragraphs indexed | 409,499 |
| Citation edges | 8,716 |
| Separate opinions | 109: 47 dissents and 62 concurrences |

- Importing metadata takes about 15 seconds a year and parses every citation in the source.
- Ingesting the text of the whole corpus takes about 0.4 seconds a judgment on a CPU-only laptop with
  eight worker processes. Of 9,381 judgments, 194 failed on the first pass; 189 of those were transient
  network failures and recovered on the retry, leaving 5 genuine losses: two PDFs the bucket does not
  have and three that yield no text after cleaning.
- Building the full-text index over 409,499 paragraphs takes 87 seconds. A search across all of them
  answers in about 8 seconds.
- The citator extracts 8,716 edges. Negative treatment is rare, as it should be: 25 across the whole
  corpus. Each was read against the judgment that produced it over four rounds of auditing, and every
  false positive that reading found is pinned as a test. The precision bar is asymmetric: a missed
  overruling costs an advocate nothing they did not already lack, while a false one has them drop a
  binding authority.
- `orderorder treatment INSC:2014:53` reports Pune Municipal Corporation as **overruled**, by Indore
  Development Authority v Manoharlal (five judges, 2020) at its paragraph 362, among 118 judgments
  citing it — and shows two later two-judge benches whose words claim to overrule it downgraded to
  doubt, because they could not.

A judgment is wounded not only by what was said about it but by what happened to the cases it stood
on, and the Constitution Bench said exactly that: "all other decisions in which Pune Municipal Corpn.
has been followed, are also overruled." So a judgment that relied on or followed a case since
overruled is reported as **undermined**, with the chain named: Indore Development Authority v
Shailendra (2018) relied on Pune Municipal, which was overruled in 2020. Only reliance carries the
wound, only judgments decided before the overruling, and only one hop — and the report says in terms
that this is an inference from the citation graph rather than a holding of any court.

**The court, and the facts.** Two checks close the taxonomy. A brief that calls a two-judge decision
"a Constitution Bench", or attributes a High Court judgment to the Supreme Court, is claiming an
authority binds when it does not; the record settles that without reading the judgment, and only
overstatement is a finding. And `verify --facts` compares the facts the cited case turned on with the
facts of the matter now before the court — the one question the judgment cannot answer by itself,
since the present matter is not in it. Calling an authority inapplicable is the strong claim there, so
the model must quote the judgment's own statement of the fact said to distinguish it, and a fact that
cannot be found in the text is not recorded as distinguishing.

**What the citator cannot see.** A judgment the corpus does not hold, which is 56% of the citations
these judgments make. And a judgment whose text arrived truncated: Vijay Latka (2016) is held as nine
paragraphs, so the authority it rests on is not in the text at all and nothing can be inferred about
it.
- Fetching and parsing a judgment's official PDF takes two to three seconds; a 51-page judgment
  segments into 118 paragraphs.
- A citation to a paragraph the judgment does not have is reported as such, which is the Delhi High
  Court failure of September 2025.
- Across eleven ingested judgments, the voice rules attribute 8 to 15 per cent of paragraphs to
  someone other than the deciding court — counsel, the court below, or a quoted precedent — and the
  disposition paragraph is found in all eleven. On the demo judgment, a brief pinpointing paragraph 3
  is told that the paragraph is the appellant's advocate speaking, with the cue quoted, and no API key
  is involved.

Two things the corpus does not tell you, which the PDF does. The metadata's judge column names only
the **presiding** judge, so bench strength arrives under-counted; the coram printed on the judgment is
read instead, because bench strength decides which precedents bind which. And the Reports open with an
**editorial headnote**, which is the publisher's summary rather than the court's words; it is stored
separately and never used as the text a pinpoint resolves against.

**The reporter's own words are not the court's.** The Reports open with an editorial headnote and
close with the editors' sign-off — the disposition restated, the name of whoever wrote the headnote —
which extraction ran together with the court's last paragraph in two thirds of the corpus. A quote
verified against that would be reported as the court's, so both ends are now cut, and 424,000
characters of publisher's text came out of judgments already stored.

### Not built yet

Embeddings and hybrid retrieval, so search is lexical and finds a quoted line far better than a
paraphrase. Document assembly for the drafting surface (PRD B7) and its DOCX export (B9) — the gate
that decides what may enter a draft is built, and `argue` is it. The web app. See
[docs/ROADMAP.md](docs/ROADMAP.md).

## Status

Documents complete. Both directions of the engine work end to end on the whole corpus, all twelve
failure modes are implemented, and both directions are measured on a held-out set. Started
4 September 2026.

## Attribution

Judgment data from the [Indian Supreme Court Judgments](https://registry.opendata.aws/indian-supreme-court-judgments/) and [Indian High Court Judgments](https://registry.opendata.aws/indian-high-court-judgments/) datasets on AWS Open Data (CC-BY-4.0). Lookups powered by [IKanoon](https://api.indiankanoon.org/) where indicated.

*OrderOrder is a research aid. The advocate remains responsible for every citation filed.*
