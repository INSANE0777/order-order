# OrderOrder — Tech Stack

| | |
|---|---|
| **Version** | 0.1, draft |
| **Date** | 4 September 2026 |
| **Companion documents** | [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [ROADMAP.md](ROADMAP.md) |

Constraints this stack satisfies: **fully self-hosted** (no mandatory external API), **open and official data only**, **permissive licences only in the product path**, a **CPU-only Windows laptop for development** and a **rented India-resident GPU** for demo and production, and a team of two.

---

## 1. Principles

1. **Boring infrastructure.** One database (PostgreSQL) for records, vectors and full-text; one queue (Redis); one object store; Docker Compose. Add a dedicated vector database only when measurements say so.
2. **Deterministic pipeline, model at the leaves.** The engine is plain Python with typed stages. Language-model calls are schema-constrained and logged. No autonomous agent loops in the verification path.
3. **Permissive licences.** MIT, Apache-2.0, BSD and CC-BY only. AGPL, non-commercial and revenue-capped components are excluded (§3).
4. **Same code, two profiles.** The laptop runs small models on CPU for development; the GPU box runs the real models. Nothing in the code knows which.
5. **Cloud is a toggle, not a dependency.** A per-matter switch, off by default, can route model calls to a cloud provider for users who consent; the engine's quote verification runs regardless.

---

## 2. Stack at a glance

| Layer | Choice | Why | Considered and rejected |
|---|---|---|---|
| Frontend | Next.js (App Router), TypeScript, Tailwind, shadcn/ui, react-pdf for the judgment viewer | Fast to build, good PDF rendering with highlight overlays | Streamlit (fine for a demo, poor for the annotated-brief UI) |
| API | Python 3.12 via `uv`, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | ML ecosystem; typed; async | Django (heavier for an API-first app) |
| LLM calls | Pydantic AI (V2, stable June 2026) for typed structured outputs over OpenAI-compatible and Anthropic endpoints | Typed outputs, provider abstraction, small surface | LangChain / LangGraph (agentic; heavier; only needed for durable human-in-the-loop later), LlamaIndex (fine for retrieval, not needed) |
| Jobs | Redis + arq | Async, tiny, fits FastAPI | Celery (fine, heavier), Dramatiq (good alternative), Temporal (only if runs must survive restarts across hours) |
| Parsing (born-digital) | Docling (MIT) | Layout blocks, reading order, tables, footnotes; permissive | PyMuPDF / pymupdf4llm (AGPL), Marker (weights revenue-capped) |
| OCR (scanned) | PaddleOCR 3.7: PP-OCRv6 on CPU; PaddleOCR-VL-1.6 on GPU (Apache-2.0, 109 languages incl. Hindi/Devanagari) | Best accuracy per parameter; Devanagari; free at any volume when self-hosted | MinerU (AGPL), Surya (revenue-capped weights), Tesseract (baseline fallback only), paid OCR APIs (opt-in burst only) |
| Structure | Custom paragraph segmenter and opinion-boundary rules; rhetorical roles by local LLM now, fine-tuned InLegalBERT later | OpenNyAI label set fits the ratio/voice checks; the `opennyai` package is unmaintained so we retrain rather than depend | — |
| Citation parsing | Custom grammar + OpenNyAI legal NER (Apache-2.0) + rapidfuzz | No open Indian citation parser exists; eyecite is US-only | — |
| Embeddings | BGE-M3 (dev, CPU) → Qwen3-Embedding-8B (GPU), both Apache-2.0, served by Text Embeddings Inference | Multilingual, long inputs, self-hostable; decided on the gold set | Closed legal embedders (Voyage, Kanon 2): strong but not self-hostable; kept as optional toggles |
| Reranker | bge-reranker-v2-m3 (Apache-2.0) or Qwen3-Reranker | Permissive, strong | Jina rerankers (weights non-commercial) |
| NLI first pass | MiniCheck-style entailment model | Cheap filter before the LLM adjudicator | — |
| Vector + full-text | PostgreSQL 17 + pgvector 0.8 (`halfvec`, HNSW) + `tsvector`, fused with reciprocal rank fusion | One system of record; exact citation lookup in SQL | Qdrant (add when past ~10M chunks or when sparse+dense hybrid is needed), Elasticsearch/OpenSearch (BM25 quality, but a second system) |
| LLM serving (dev) | Ollama (already installed) or llama.cpp server on Windows | Native Windows, JSON-schema output | vLLM / SGLang (no native Windows) |
| LLM serving (prod) | SGLang on Linux GPU, vLLM as fallback; both OpenAI-compatible with JSON-schema constrained decoding | Prefix caching fits "one judgment, many claims"; batching | TGI (archived March 2026) |
| Object storage | Local disk → MinIO | S3-compatible, self-hosted | — |
| Auth | Auth.js (hackathon) → Keycloak or Ory for firm deployments | Fast now, enterprise later | — |
| Observability | Langfuse (self-hosted) for LLM traces; DeepEval assertions in CI over the gold set | Replay any verdict's calls; regression gates | Arize Phoenix (fine), RAGAS (dataset-first, later) |
| Deployment | Docker Compose with `dev` and `prod` profiles; Caddy for TLS | Two people, one box | Kubernetes (not yet) |
| GPU hosting | E2E Networks (Delhi/Mumbai) or AWS Mumbai (ap-south-1) | India residency; E2E is the cheapest India-resident option found | RunPod/Lambda (India region unconfirmed or absent) |

---

## 3. Licence audit

| Component | Licence | Verdict |
|---|---|---|
| Next.js, FastAPI, Pydantic, SQLAlchemy, arq, Docling, rapidfuzz | MIT / BSD | Use |
| PaddleOCR, PaddleOCR-VL weights, pgvector, TEI, Qwen3.5, Qwen3-Embedding, bge models, gpt-oss, OpenNyAI code and NER | Apache-2.0 (pgvector: PostgreSQL licence) | Use |
| AWS Open Data SC and HC judgment datasets | CC-BY-4.0 | Use with attribution |
| OpenNyAI rhetorical-role data | CC-BY-SA-4.0 | Use for training; share-alike applies to derived datasets, not to the trained model's outputs; confirm before redistributing labels |
| Indian Kanoon API data | Contract terms: mandatory "powered by IKanoon" attribution incl. RAG and fine-tuning; silent on caching | Lookup only until caching is confirmed in writing |
| Gemma 4 | Reported open licence permitting commercial use | Re-verify the licence text before shipping on it |
| PyMuPDF / pymupdf4llm, MinerU | AGPL-3.0 | **Exclude** (or buy a commercial licence) |
| Marker, Surya weights | OpenRAIL-M with a $5M revenue/funding cap | **Exclude** |
| Jina reranker weights | CC-BY-NC-4.0 | **Exclude** |
| IL-TUR | CC-BY-NC-SA-4.0 | **Exclude** |
| Llama 4 | Llama Community Licence | Exclude (restrictive; better Apache-2.0 options exist) |
| Kimi K3 | Modified MIT with a revenue trigger | Exclude |
| NVIDIA Nemotron | NVIDIA Open Model Licence (commercial allowed, not Apache) | Optional; read before use |

---

## 4. Language-model layer

### 4.1 Model matrix by hardware tier

| Tier | Hardware | Model | Quantisation and VRAM | Working context | Role |
|---|---|---|---|---|---|
| CPU-only development machine (4 cores, 16 GB RAM, no GPU) | — | Qwen3.5-4B | Q4, ~3 GB RAM | 8-16K | Development and smoke tests only; not trusted for verdict quality |
| 8 GB VRAM | RTX 3060/4060 | Qwen3.5-9B | Q4, ~6 GB | 24-32K | Small-office development |
| **16-24 GB VRAM** | RTX 4090/5090; cloud L4 (24 GB) or A10G (24 GB) | **Qwen3.5-27B** (Apache-2.0, 262K native context) or **Gemma 4 31B** (256K, strong long-context); alternative **gpt-oss-20b** (MXFP4, ~16 GB, 128K, very reliable JSON) | AWQ / Int4, ~16-18 GB, ~6 GB left for KV cache | 30-60K | **Demo and first production tier** |
| 48-80 GB | A100-40/80, H100 | **Qwen3.5-122B-A10B** (Int4) or **gpt-oss-120b** (MXFP4, ~63 GB) or Mistral Small 4 (119B-A6B) | Fits one 80 GB card | 100-200K | Production quality; whole-judgment digests in one pass for most judgments |

Notes from the September 2026 research pass: Qwen3.5-27B is the best sub-40B open model on LongBench v2 (60.6%); Gemma 4 31B posts the strongest Gemma long-context score (MRCR 8-needle at 128K, 66.4%); the small Gemma 4 variants are weak on long context and are not used. Legal fine-tunes (INLegalLlama, SaulLM) lose to 2026 general models on long-context reading and structured output; InLegalBERT is used only as a cheap tagger. Model choice is finalised on the gold set ([ARCHITECTURE.md](ARCHITECTURE.md) §11).

### 4.2 Serving

- **Development (Windows).** Ollama is installed; it exposes an OpenAI-compatible endpoint and accepts a JSON schema for structured output. llama.cpp's server and LM Studio are equivalent alternatives. Point `LLM_BASE_URL` at it.
- **Production (Linux GPU).** SGLang, whose RadixAttention prefix caching directly rewards the engine's access pattern (the same judgment digest and candidate paragraphs are the prefix for many claims); vLLM as the fallback. Both expose OpenAI-compatible endpoints with JSON-schema constrained decoding (xgrammar or llguidance). Neither runs natively on Windows; that is why production is Linux.
- **Do not use** Hugging Face TGI (archived and in maintenance mode since March 2026).

### 4.3 Constrained decoding and prompts

Every call carries a Pydantic schema and is executed with constrained decoding, so the model cannot return malformed JSON or invent enum values. Prompt versions are string constants stamped into every verdict. Prompts for the verification stages are short and instruct the model to answer `not_found` rather than guess; the quote fields are the only free text, and they are verified by code.

### 4.4 Prefix caching strategy

Jobs are grouped by judgment. For a judgment with N cited claims, the prompt prefix (system instructions, digest, candidate paragraphs) is identical across the N calls and only the claim suffix changes. Under SGLang this is served from cache automatically; under Ollama the same ordering keeps the KV cache warm. Whole-judgment digests are built once, batched, and cached in the database, so a 300-page judgment is read in full exactly once.

### 4.5 Throughput and cost math (from the research pass, indicative)

- A 27B-class model at 4-bit on a 24 GB card decodes at roughly 30-45 tokens/s single-stream.
- One claim verification (5-10 paragraphs, ~4K prompt tokens, ~200 output tokens): about 6-10 s single-stream on Ollama; about 1-2 s effective at batch 16-32 under SGLang.
- A full 400-paragraph judgment sweep (roles, holdings, digest): 40-70 minutes single-stream; 4-8 minutes batched with prefix reuse on one 24 GB card.
- On an E2E A100-80G at ₹189/hour that is roughly ₹15-25 of GPU time per judgment digest, paid once per judgment; per-claim verification afterwards is a few seconds of GPU time.

### 4.6 Provider abstraction and the cloud toggle

The engine talks to a single `LLMProvider` interface (Pydantic AI supplies the implementations): an OpenAI-compatible provider for Ollama, llama.cpp, SGLang and vLLM, and an Anthropic provider using the official `anthropic` SDK.

The cloud toggle is a per-matter setting, off by default. When a consenting user enables it:

- The model is `claude-opus-5` (adaptive thinking on by default, 1M-token context, PDF document input, structured outputs via `messages.parse()`).
- Claude's **citations** feature (`citations: {enabled: true}` on document blocks) returns verbatim `cited_text` with character or page locations; the engine feeds those quotes through the same string verifier as local-model quotes, so quote-or-nothing holds on both paths.
- Bulk digest builds can use the Message Batches API at half price when latency does not matter.
- Before enabling for privileged documents, confirm the organisation's data-retention configuration with the provider: Claude Fable 5.1, for example, is not available under zero data retention unless expressly authorised, so it is not used for client documents; the consent record names provider, model, retention setting and region, and is stamped on every verdict produced while the toggle is on.

---

## 5. Document parsing and OCR

- **Per-page routing** (ARCHITECTURE.md §3.2): text-layer pages go to Docling; image-only pages go to OCR. Text-layer detection uses pypdfium2 or pdfplumber (permissive licences), not PyMuPDF.
- **Docling** (MIT, v2.117 as of July 2026) produces layout blocks with reading order, tables and footnotes for born-digital PDFs and DOCX.
- **PaddleOCR 3.7** (June 2026): PP-OCRv6 pipeline on CPU for the laptop and for light scans; **PaddleOCR-VL-1.6** (0.9B parameters, 109 languages including Hindi/Devanagari, Apache-2.0) on GPU for hard scans and photographed pages. It wants 8 GB VRAM minimum, 12 GB comfortable, and compute capability 8.0 or higher for the vLLM-based path. On Windows the ONNX export is the safer route for the CPU pipeline.
- **Tesseract** remains as a last-resort fallback only.
- **Evaluate before committing**: run Docling, PaddleOCR-VL and PP-OCRv6 over ~200 Indian judgment and annexure pages (typed, scanned, photographed, Hindi) and pick per page type by measured character accuracy. Vendor benchmarks (OmniDocBench) do not include Indian court documents.
- **Paid OCR APIs** (Mistral OCR at $4 per 1,000 pages, Azure Document Intelligence Read at $1.50 per 1,000 pages) are wired as an opt-in burst path behind the same cloud-consent switch, never the default.

---

## 6. Retrieval layer

- **Chunk = paragraph** with a judgment-context prefix (title, court, year, opinion type, role) prepended before embedding.
- **Embeddings**: BGE-M3 (1024 dimensions, 8K-token inputs, dense and sparse outputs, Apache-2.0) as the baseline that runs on CPU for the hackathon subset; Qwen3-Embedding-8B (Apache-2.0, 100+ languages) on the GPU box; both served through Text Embeddings Inference. The choice is made on pinpoint hit@k over the gold set, because no public legal-retrieval benchmark covers Indian law.
- **Reranker**: bge-reranker-v2-m3 or Qwen3-Reranker, served by the same TEI instance, applied to the top 20-40 candidates.
- **Hybrid search** in SQL (dense + full-text, reciprocal rank fusion), scoped to one judgment for the locator and to the corpus for authority retrieval:

```sql
WITH dense AS (
  SELECT id, row_number() OVER (ORDER BY embedding <=> $1) AS r
  FROM paragraph
  WHERE text_version_id = $2
  ORDER BY embedding <=> $1
  LIMIT 40
),
lexical AS (
  SELECT id, row_number() OVER (ORDER BY ts_rank_cd(fts, q) DESC) AS r
  FROM paragraph, plainto_tsquery('english', $3) AS q
  WHERE text_version_id = $2 AND fts @@ q
  LIMIT 40
)
SELECT id, SUM(1.0 / (60 + r)) AS score
FROM (SELECT * FROM dense UNION ALL SELECT * FROM lexical) AS fused
GROUP BY id
ORDER BY score DESC
LIMIT 20;
```

- **Citation lookup is never vector search.** Normalised citation strings hit a unique index on `citation_alias.normalized`.
- **Claim queries** are built from the atomic claim's subject and predicate, plus the statute names it mentions; the claimed pinpoint paragraph and its neighbours are always injected into the candidate set.

---

## 7. Data layer

- **PostgreSQL 17** with **pgvector 0.8** (HNSW; `halfvec` storage; `hnsw.iterative_scan` for filtered queries so that per-judgment searches do not under-return).
- Index parameters to start: `m = 16`, `ef_construction = 128`, query-time `ef_search = 100`; tune on the gold set.
- Row-level security keyed on `matter_id` for every user-scoped table; corpus tables are shared and read-only for application roles.
- **Sizing (estimates; verify after the first ingest):**

| Corpus | Judgments | Paragraphs | Text | Vectors (halfvec, 1024-d) | Fits |
|---|---|---|---|---|---|
| Hackathon subset: SC, English, 2014-2025 | ~12-18k | ~1-1.5M | ~1.5 GB | ~2-3 GB (+ HNSW ~50%) | ~10 GB of local disk |
| Full Supreme Court 1950-2025 | ~40-50k | ~3-5M | ~4-5 GB | ~6-10 GB (+ HNSW) | A 32-64 GB RAM box |
| High Courts (all 25) | ~17.8M | hundreds of millions | ~1 TB+ | ~1 TB | Phase 3: shard by court, Qdrant or partitioned pgvector, 512-d Matryoshka embeddings |

- Backups: nightly `pg_dump` of record tables; corpus tables are reproducible from the open datasets and are excluded from backups beyond the ingest manifest.

---

## 8. Application layer

- **API surface (v0)**: `POST /matters`, `POST /matters/{id}/uploads`, `POST /briefs` (returns a job), `GET /briefs/{id}/verdicts`, `GET /jobs/{id}/events` (server-sent events), `GET /judgments/{id}` (viewer payload with paragraphs, opinions, roles, aliases), `POST /drafts`, `GET /drafts/{id}`, `POST /drafts/{id}/export`, `POST /verdicts/{id}/override`.
- **Engine as a library**: `packages/engine` exposes `verify_brief(text, facts=None) -> list[Verdict]` and `verify_citation(citation, proposition, facts=None) -> Verdict` with no web dependencies, plus a CLI (`orderorder verify`, `orderorder resolve`, `orderorder ingest`, `orderorder eval`) so that every stage can be exercised and tested without the UI.
- **Workers**: arq consumers for `ingest_document`, `build_digest`, `verify_brief`, `draft_matter`; jobs are idempotent and resumable at stage boundaries.
- **Exports**: python-docx for DOCX (draft, annotated brief with comments), WeasyPrint or the browser's print pipeline for PDF reports.

---

## 9. Developer machine setup

What the build assumes: an x86-64 machine with four cores or more, about 16 GB of RAM, and no NVIDIA GPU. The constraint worth planning around is disk: the corpus, the Postgres volume, the model weights and the build caches together want tens of gigabytes, and every tool involved defaults to putting its share on the system drive. Choose a location with room and export it as `ORDERORDER_DATA_DIR`.

Do these before the sprint (day 0):

1. **Check free space on the system drive.** A drive close to full will destabilise Windows updates and Docker, and the caches below are exactly what fills it.
2. **Move Docker's disk image off the system drive.** Docker Desktop → Settings → Resources → Advanced → Disk image location. Docker moves the existing image. Then cap WSL memory so the host keeps room: create `%UserProfile%\.wslconfig` with `[wsl2]` and `memory=8GB`.
3. **Point Ollama's model store at the data directory.** Set a user environment variable `OLLAMA_MODELS=$DATA/ollama`, restart Ollama, then pull the Qwen3.5-4B Q4 tag from the Ollama library.
4. **Model caches under the data directory.** Set `HF_HOME` (embedding, reranker and PaddleOCR models) and `UV_CACHE_DIR`.
5. **Python 3.12 via uv.** `winget install astral-sh.uv`, then `uv python install 3.12`; the project's `pyproject.toml` pins 3.12 and `uv sync` creates the environment.
6. **Project data directory.** `ORDERORDER_DATA_DIR` holds the corpus files, Postgres and MinIO volumes (bind-mounted in the dev compose profile). Keep the code wherever you like, but a path outside a downloads folder is safer against cleanup tools.
7. **Node.** Node 22, with pnpm enabled via `corepack enable`.

What the laptop can and cannot do: ingestion of the hackathon subset (CPU embeddings overnight), the whole engine end to end with the 4B model for correctness of the code paths, the web UI, and the evaluation harness. It cannot produce demo-quality verdicts or run PaddleOCR-VL; those run on the rented GPU box.

---

## 10. Docker Compose services

```yaml
services:
  postgres:   { image: pgvector/pgvector:pg17, profiles: [dev, prod] }
  redis:      { image: redis:7,               profiles: [dev, prod] }
  minio:      { image: minio/minio,           profiles: [prod] }        # dev uses a bind mount on the host
  api:        { build: apps/api,              profiles: [dev, prod] }
  worker:     { build: apps/api, command: arq orderorder.worker.Settings, profiles: [dev, prod] }
  web:        { build: apps/web,              profiles: [dev, prod] }
  tei:        { image: ghcr.io/huggingface/text-embeddings-inference, profiles: [dev, prod] }   # CPU image in dev, GPU image in prod
  ollama:     { image: ollama/ollama,         profiles: [dev] }         # or the host's Ollama on Windows
  sglang:     { image: lmsysorg/sglang,       profiles: [prod], deploy: { resources: { reservations: { devices: [{ capabilities: [gpu] }] } } } }
  paddleocr:  { build: services/paddleocr,    profiles: [prod] }        # PaddleOCR-VL service; CPU PP-OCRv6 runs inside the worker in dev
  langfuse:   { image: langfuse/langfuse,     profiles: [prod] }
  caddy:      { image: caddy:2,               profiles: [prod] }
```

Environment variables of note: `LLM_BASE_URL`, `LLM_MODEL`, `EMBEDDINGS_URL`, `RERANKER_URL`, `OCR_MODE=cpu|gpu`, `ORDERORDER_DATA_DIR`, `INDIANKANOON_TOKEN`, `INDIANKANOON_DAILY_QUOTA`, `CLOUD_TOGGLE_ALLOWED=false`.

---

## 11. Repository layout

```
order-order/
  README.md
  docs/                      PRD, architecture, tech stack, roadmap
  apps/
    web/                     Next.js app
    api/                     FastAPI app + arq worker entrypoint
  packages/
    engine/                  verification + drafting engine (pure Python, CLI)
      citations/             grammar, normaliser, alias table logic
      resolver/
      locator/               retrieval, quote verifier, pinpoint reconciliation
      attribution/           voice, opinion, weight
      scope/                 claim decomposition, NLI, adjudicator
      citator/
      facts/
      drafting/
      prompts/               versioned prompt files
      schemas/               Pydantic models (verdict, digest, gold item)
    ingest/                  parsing, OCR, segmentation, roles, embeddings, digests
  services/
    paddleocr/               OCR service container
  evals/
    gold/                    gold-set JSONL (anonymised)
    run.py                   harness
  infra/
    docker-compose.yml
    Caddyfile
  data/                      gitignored; relocatable via ORDERORDER_DATA_DIR
```

---

## 12. Cost sketch (indicative, September 2026 prices from the research pass)

| Item | Hackathon | Phase 1 (monthly) |
|---|---|---|
| Laptop development | ₹0 | ₹0 |
| GPU for demo and evaluation | E2E A100-40G at ₹179/hr or A100-80G at ₹189/hr for ~6-8 hours across rehearsals and the demo: **~₹1,100-1,500**; AWS Mumbai L4 (g6.xlarge) at ~$0.98/hr is the alternative | Business hours only (about 260 hours): ~₹50,000 on E2E A100-80G; 24×7: ~₹1.4 lakh; E2E spot at ~₹70/hr where acceptable: ~₹50,000 for 24×7; AWS Mumbai L4 24×7: ~$715 |
| CPU box for web, API, database (if separate from the GPU box) | — | ₹5,000-10,000 |
| Indian Kanoon API | ₹500 signup credit; apply for the ₹10,000/month non-commercial allowance | Pay-as-you-go: ₹0.20 per document, ₹0.05 per fragment; a 30-citation brief with 10 lookups costs under ₹5 |
| Storage and backups | Local disk | Under ₹2,000 |
| Domain, TLS, email | — | Under ₹1,000 |
| **Total** | **Under ₹2,000** | **₹60,000-1.5 lakh depending on GPU choice** |

Per-unit economics: one judgment digest costs ₹15-25 of GPU time once; each later verification of a claim against a digested judgment costs seconds of GPU time (well under ₹1 at batch), which is why the digest cache is the central cost mechanism.

---

## 13. Security and privacy implementation notes

- Secrets in `.env` files excluded from git; a `.env.example` documents every variable.
- Postgres row-level security policies generated from the schema; integration tests assert cross-matter reads fail.
- Encrypted volumes for Postgres and MinIO on the production box; TLS via Caddy with automatic certificates.
- Worker containers have no egress except allow-listed hosts (`api.indiankanoon.org`, `scr.sci.gov.in`, `api.sci.gov.in`, `judgments.ecourts.gov.in`, the AWS Open Data bucket) enforced at the Compose network level.
- Upload scanning (ClamAV container) before parsing; parsed text stored, originals retained in the object store under the matter's prefix.
- Audit log table is append-only for application roles.
- Delete-on-request: a job that removes the matter's rows, object-store prefix, Langfuse traces and cache entries, and records the deletion in the audit log.

---

## 14. Deliberately not used

| Not used | Why |
|---|---|
| Agent frameworks in the verification path | Verification must be deterministic, testable stage by stage, and cheap; models sit at the leaves |
| Hugging Face TGI | Archived March 2026 |
| PyMuPDF, MinerU | AGPL |
| Marker, Surya weights | Revenue-capped licence |
| Jina reranker weights | Non-commercial licence |
| IL-TUR | Non-commercial licence |
| Llama 4, Kimi K3 | Restrictive or trapped licences; Apache-2.0 alternatives are stronger |
| Manupatra / SCC Online scraping | Prohibited by their terms; bring-your-own-login lookups only, phase 2 |
| Model memory as a source of case law | Closed-world rule |
| Sampling temperature as a safety control | Grounding and string verification do that job |

---

## 15. Sources

PaddleOCR releases and PaddleOCR-VL: [releases](https://github.com/PaddlePaddle/PaddleOCR/releases) · [model card](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) · [deployment notes](https://paddlepaddle.github.io/FastDeploy/best_practices/PaddleOCR-VL-0.9B/). Docling: [repository](https://github.com/docling-project/docling). pgvector: [changelog](https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md). OpenNyAI: [rhetorical roles](https://github.com/Legal-NLP-EkStep/rhetorical-role-baseline) · [legal NER](https://github.com/Legal-NLP-EkStep/legal_NER) · [package status](https://snyk.io/advisor/python/opennyai). InLegalBERT: [model](https://huggingface.co/law-ai/InLegalBERT). LegalSeg: [paper](https://arxiv.org/html/2502.05836v1). Embeddings and rerankers: [Qwen3-Embedding](https://qwenlm.github.io/blog/qwen3-embedding/) · [TEI](https://github.com/huggingface/text-embeddings-inference) · [MLEB](https://huggingface.co/blog/isaacus/introducing-mleb) · [Legal RAG Bench](https://huggingface.co/blog/isaacus/legal-rag-bench). Models: [Qwen3.5 collection](https://huggingface.co/collections/Qwen/qwen35) · [Gemma 4](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/) · [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4) · [gpt-oss](https://openai.com/index/introducing-gpt-oss/) · [LongBench v2 board](https://benchlm.ai/benchmarks/longbench-v2). Serving: [vLLM structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/) · [SGLang releases](https://github.com/sgl-project/sglang/releases) · [TGI status](https://github.com/huggingface/text-generation-inference). Verification research: [Stanford RegLab](https://reglab.stanford.edu/publications/hallucination-free-assessing-the-reliability-of-leading-ai-legal-research-tools/) · [Who Checks the Citations?](https://arxiv.org/html/2606.21155) · [CLERC](https://arxiv.org/pdf/2406.17186) · [MiniCheck](https://aclanthology.org/2024.emnlp-main.499.pdf) · [Anthropic Citations](https://www.anthropic.com/news/introducing-citations-api). GPU hosting: [E2E Networks pricing](https://www.e2enetworks.com/blog/nvidia-a100-price-india). Data: [Indian Kanoon API](https://api.indiankanoon.org/documentation/) · [AWS Open Data SC](https://registry.opendata.aws/indian-supreme-court-judgments/) · [AWS Open Data HC](https://registry.opendata.aws/indian-high-court-judgments/) · [SCR portal](https://scr.sci.gov.in/scrsearch/).
