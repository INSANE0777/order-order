# OrderOrder — Tech Stack

| | |
|---|---|
| **Version** | 0.2, draft (zero-cost hackathon build; LangChain adopted) |
| **Date** | 4 September 2026 |
| **Companion documents** | [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [ROADMAP.md](ROADMAP.md) |

Constraints this stack satisfies: **₹0 for the hackathon**, **open and official data only**, **permissive licences only in the product path**, a **CPU-only Windows laptop**, **LangChain + LangGraph** as the orchestration layer, **self-hosting as the production target** for privileged documents, and a team of two.

The version 0.1 stack assumed a rented GPU for the demo and Pydantic AI for orchestration. Both are gone. Every provider, model and service below is either free of charge within a published allowance or runs on the laptop; the paid and self-hosted pieces are kept only as the production profile, reachable by changing environment variables.

---

## 1. Principles

1. **Free first, self-hosted later.** The hackathon build spends nothing. The model behind every call is a configuration string, so moving from a free API tier to a self-hosted GPU box is not a code change.
2. **Demo data only on free tiers.** Several free tiers train on what you send them (§5.1). The hackathon processes moot memorials and synthetic matters, never client documents. The one free provider that does not train on inputs is reserved for anything sensitive; production keeps privileged text on the team's own hardware.
3. **Boring infrastructure.** One database (PostgreSQL with pgvector, which also stores LangGraph checkpoints), no queue for the hackathon, Docker only for Postgres. Add components when a measurement demands them.
4. **Deterministic pipeline, model at the leaves.** The verification engine is a LangGraph state graph whose nodes are typed Python functions. Language-model calls sit inside specific nodes with a Pydantic output schema. No node runs a ReAct-style agent loop.
5. **Permissive licences.** MIT, Apache-2.0, BSD and CC-BY only in the product path (§3).
6. **Same code, three profiles.** Laptop-offline (Ollama, small model), hackathon-free (free API tiers with fallbacks, free GPU notebooks for batch work), production-self-hosted (SGLang, TEI, PaddleOCR-VL on a rented GPU box).

---

## 2. Stack at a glance

| Layer | Hackathon profile (₹0) | Production profile | Why |
|---|---|---|---|
| Orchestration | **LangChain 1.4 + LangGraph 1.2**: `StateGraph` for the engine, `init_chat_model` + `with_fallbacks` for providers, `with_structured_output` for typed results, Postgres checkpointer | Same | Provider swapping across free tiers; the graph matches the verdict state machine; integrations for Docling, pgvector and tracing (§4) |
| LLM | Free API tiers behind ordered fallbacks: Google AI Studio Gemini Flash (bulk, demo data), Groq gpt-oss-120b (privacy-safe, small token budget), Cerebras gpt-oss-120b (short prompts); Ollama Qwen3.5-4B offline | SGLang serving Qwen3.5-27B or gpt-oss-120b on a rented India-resident GPU | §5 |
| Batch compute | Kaggle notebooks (30 GPU-hours/week, 2×T4) for corpus embeddings, digests and OCR; Modal's $30/month credit for scheduled jobs | The same GPU box | §6 |
| Frontend | Next.js + TypeScript + Tailwind + shadcn/ui, react-pdf viewer; runs locally, Vercel Hobby only if judges need a link | Same, behind Caddy | — |
| API | Python 3.12 via `uv`, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic; FastAPI background tasks with a jobs table | Same, plus arq workers on Redis | No queue needed for a two-person demo |
| Parsing | Docling (MIT) through `langchain-docling`; pypdfium2 for text-layer detection | Same | Permissive; layout and footnotes |
| OCR | PP-OCRv6 on CPU (PaddleOCR 3.7); PaddleOCR-VL-1.6 on a Kaggle GPU for scanned batches | PaddleOCR-VL service | Apache-2.0; Hindi/Devanagari |
| Embeddings | BGE-M3 (Apache-2.0): corpus embedded on Kaggle, queries on the laptop CPU; Voyage's free allowance for an embedder bake-off on the gold set | Qwen3-Embedding-8B via Text Embeddings Inference | No token cap, no data terms for local models |
| Reranker | bge-reranker-v2-m3 on CPU (top-20, about a second) | Same via TEI | Permissive |
| Vector + full-text | PostgreSQL 17 + pgvector 0.8 in Docker, hybrid search in SQL with reciprocal rank fusion, exact citation lookup by index | Same on the GPU box; Qdrant past ~10M chunks | One system of record; free hosted databases are too small for the corpus (§8) |
| Checkpoints | `langgraph-checkpoint-postgres` in the same database | Same | Resumable runs, human-in-the-loop interrupts, free |
| Tracing and eval | LangSmith Developer plan (5,000 traces/month, 14-day retention) with the gold set as a LangSmith dataset; DeepEval in CI | Langfuse self-hosted (privileged text must not leave the box) | One environment variable turns tracing on |
| Storage | Local disk under `ORDERORDER_DATA_DIR` | MinIO | — |
| Auth | Auth.js | Keycloak or Ory | — |
| Hosting | The laptop (localhost) for the demo; Vercel Hobby for the frontend and Render free or Hugging Face Spaces for the API only if a public link is required | Docker Compose on one GPU box, Caddy TLS | Free hosts spin down; the corpus lives on the laptop anyway |

---

## 3. Licence audit

| Component | Licence | Verdict |
|---|---|---|
| LangChain, LangGraph, langchain-postgres, langgraph-checkpoint-postgres, langchain-docling, langchain-huggingface, langchain-groq, langchain-google-genai, langchain-cerebras, langchain-ollama | MIT | Use |
| Next.js, FastAPI, Pydantic, SQLAlchemy, Docling, rapidfuzz, pypdfium2 | MIT / BSD / Apache-2.0 | Use |
| PaddleOCR, PaddleOCR-VL weights, pgvector, TEI, Qwen3.5, Qwen3-Embedding, bge models, gpt-oss, OpenNyAI code and NER | Apache-2.0 (pgvector: PostgreSQL licence) | Use |
| AWS Open Data SC and HC judgment datasets | CC-BY-4.0 | Use with attribution |
| OpenNyAI rhetorical-role data | CC-BY-SA-4.0 | Use for training; share-alike applies to derived datasets; confirm before redistributing labels |
| Indian Kanoon API data | Contract: mandatory "powered by IKanoon" attribution including RAG and fine-tuning; silent on caching | Lookup only until caching is confirmed in writing |
| Gemma 4 | Reported open licence permitting commercial use | Re-verify before shipping on it |
| PyMuPDF / pymupdf4llm, MinerU | AGPL-3.0 | **Exclude** (or buy a commercial licence) |
| Marker, Surya weights | OpenRAIL-M with a $5M revenue/funding cap | **Exclude** |
| Jina reranker weights (self-hosted) | CC-BY-NC-4.0 | **Exclude** as weights; the hosted API's free tokens are usable (§8) |
| IL-TUR | CC-BY-NC-SA-4.0 | **Exclude** |
| Llama 4 | Llama Community Licence | Exclude; better Apache-2.0 options exist |
| Kimi K3 | Modified MIT with a revenue trigger | Exclude |
| Vercel Hobby | Terms prohibit commercial use | Hackathon only |

---

## 4. LangChain, reconsidered

### 4.1 What changed and why

Version 0.1 chose Pydantic AI and plain Python because the engine must be deterministic and testable stage by stage. That requirement stands. What changed is the budget: a ₹0 build lives on several free API tiers with different rate limits, context caps and data terms, and it must fail over between them mid-run. That is LangChain's core competence, and LangGraph turns out to be the natural implementation of the engine that ARCHITECTURE.md already specified:

- **Provider swapping is a string.** `init_chat_model("google_genai:gemini-2.5-flash")`, `init_chat_model("groq:openai/gpt-oss-120b")`, `init_chat_model("cerebras:gpt-oss-120b")`, `init_chat_model("ollama:qwen3.5:4b")` share one interface; `.with_fallbacks([...])` chains them so a 429 from one provider silently moves to the next.
- **The engine is already a state machine.** ARCHITECTURE.md Diagram 3 (the stage flow) and Diagram 8 (the verdict state machine) map one-to-one onto a LangGraph `StateGraph`: nodes are stages, conditional edges are decisions, the state is the verdict-in-progress. A checkpointer makes every run resumable and every intermediate state inspectable. `interrupt()` implements `needs_review` as a real pause for a human decision, resumed with `Command(resume=...)`. The node map is in ARCHITECTURE.md §4.13.
- **Typed outputs survive the switch.** `with_structured_output(PydanticSchema)` gives the same Pydantic objects the 0.1 design relied on, with the method chosen per provider (§4.2).
- **Integrations we would otherwise write.** `langchain-docling` loads PDFs through Docling; `langchain-huggingface` wraps BGE-M3; `langchain-postgres` provides a pgvector store; LangSmith tracing is one environment variable.
- **Legibility.** A LangGraph graph is something judges and new contributors can read.

### 4.2 How it is used

| Concern | Choice |
|---|---|
| Graph | One `StateGraph` per surface: `verify_citation` (invoked once per citation, fanned out over a brief with `Send`) and `draft_matter`. State is a Pydantic model: the §8 verdict object plus working fields |
| Nodes | Plain Python functions in `packages/engine/nodes/`; each is unit-tested with a fake model. The resolver, quote verifier and citator never call a model |
| Models | `init_chat_model` with provider strings from environment variables; a `providers.py` module builds the primary model and its fallback chain (§5.2) |
| Structured output | `with_structured_output(schema, method=...)`: `json_schema` for Gemini and Ollama (native schema support), `function_calling` for Groq, Cerebras and Mistral (the safest method on open-weight endpoints), never `json_mode` |
| Prompts | Versioned files in `packages/engine/prompts/`; the version string is stamped into every verdict |
| Retrieval | A custom `BaseRetriever` wrapping the hybrid SQL query (§8), because the stock pgvector store does not do reciprocal-rank fusion or exact citation lookup; `PGVectorStore` from `langchain-postgres` is available if a plain vector store is ever enough (`PGVector` is deprecated) |
| Checkpointer | `PostgresSaver` from `langgraph-checkpoint-postgres` in the main database; `SqliteSaver` for tests |
| Human in the loop | `interrupt()` inside any node that sets `needs_review`; the web app resumes the thread with the reviewer's decision |
| Tracing | `LANGSMITH_TRACING=true` plus an API key during the hackathon; the Langfuse callback handler in production |
| Evaluation | The gold set mirrored as a LangSmith dataset so runs across providers compare side by side; `evals/run.py` remains the source of truth and DeepEval gates CI |

### 4.3 What is not used

- `create_agent` and any tool-calling agent loop in the verification path. LangGraph is used as a state machine, not as an agent runtime.
- The legacy chains that moved to `langchain-classic` in 1.0 (`LLMChain`, `SequentialChain`, `ConversationalRetrievalChain`, `AgentExecutor`).
- LangGraph Platform. The open-source checkpointers are all that is needed, and they are free.

### 4.4 Version pins (PyPI, 4 September 2026)

| Package | Version | Note |
|---|---|---|
| `langchain` | 1.4.0 | 1.0 was GA on 22 Oct 2025 and is a long-term-support line; Python 3.10+ |
| `langchain-core` | 1.6.1 | |
| `langgraph` | 1.2.11 | |
| `langgraph-checkpoint-postgres` | current | MIT |
| `langchain-google-genai` | 4.4.0 | |
| `langchain-groq` | 1.1.x | |
| `langchain-cerebras` | 0.8.2 | Last release Nov 2025; pin and watch |
| `langchain-ollama` | current | |
| `langchain-huggingface` | 1.2.2 | |
| `langchain-postgres` | 0.0.17 | Use `PGVectorStore`, not the deprecated `PGVector` |
| `langchain-docling` | 2.0.0 | Last release Nov 2025; pin |

Sources: [1.0 announcement](https://blog.langchain.com/langchain-langgraph-1dot0/) · [release policy](https://docs.langchain.com/oss/python/release-policy) · [models and `init_chat_model`](https://docs.langchain.com/oss/python/langchain/models) · [persistence and checkpointers](https://docs.langchain.com/oss/python/langgraph/persistence) · [v1 migration guide](https://docs.langchain.com/oss/python/migrate/langchain-v1).

---

## 5. Language-model layer

### 5.1 Free API tiers (checked 4 September 2026; limits change, so re-check the linked pages before the demo)

| Provider | Free models | Published limits | Context | Structured output | Data terms | Role |
|---|---|---|---|---|---|---|
| **Google AI Studio** | Gemini 2.5 Flash; Flash-Lite | Flash: 10 RPM, 250K TPM, 500-1,500 RPD (sources conflict; check the [rate-limit dashboard](https://aistudio.google.com/rate-limit)); Flash-Lite: 15 RPM, 1,500 RPD | 1M tokens | Native JSON schema | **Free-tier prompts are used to improve Google products** ([pricing](https://ai.google.dev/gemini-api/docs/pricing)) | **Bulk and demo workhorse**: whole-judgment digests in one call; per-claim verification during the live demo. Demo data only |
| **Groq** | `openai/gpt-oss-120b`, Llama 3.3 70B, gpt-oss-20b | 30 RPM, 1,000 RPD, **8K TPM, 200K TPD** ([rate limits](https://console.groq.com/docs/rate-limits)); the console labels this the Developer plan and adding a card raises limits, which is not a ₹0 option | 131K | JSON schema and tool calling | States it does not train on inputs or outputs and offers zero data retention; confirm in the console terms | **Privacy-safe path** for anything resembling real text; too little token throughput to carry a whole brief alone |
| **Cerebras** | `gpt-oss-120b`, `zai-glm-4.7` | 5-15 RPM (sources differ), 30K TPM, **1M tokens/day**; an 8,192-token context cap on the free tier is reported ([free endpoint notes](https://pricepertoken.com/endpoints/cerebras/free)) | 8K (free) | Tool calling | No-training policy claimed; one source says the larger "Experiment" allowance requires opting into training; verify in the console | Fastest fallback for short verification prompts; unusable for digests |
| **Mistral La Plateforme** | Mistral Small, Medium, Magistral | "Experiment" tier, roughly 1B tokens/month at about 1 request/s; exact numbers are no longer published (see Admin Console › Limits) | 128K | Tool calling, JSON schema | **Trains on free-tier data by default** since 12 Mar 2026; opt out under Admin › Privacy ([data controls](https://docs.mistral.ai/admin/monitor-comply/privacy-data-controls)) | Large bulk allowance once opted out; second bulk provider for eval runs |
| Ollama on the laptop | Qwen3.5-4B Q4 | Unlimited; slow on CPU | 8-16K working | Native JSON schema | Local | Offline development and last-resort fallback; not trusted for verdict quality |
| SambaNova | Llama 3.x, Llama 4 Maverick preview | 20 RPM, 200K tokens/day per model ([docs](https://docs.sambanova.ai/docs/en/models/rate-limits)) | varies | Tool calling | Free-tier data policy not documented | Optional extra fallback, demo data only |
| Not used | OpenRouter `:free` (50 requests/day and you must allow training and publishing of prompts), GitHub Models (8K input / 4K output caps), Hugging Face Inference Providers ($0.10/month credit), Cloudflare Workers AI (small models; possible embedding fallback only) | | | | | |

Anthropic's Claude API has no free tier in 2026 (new console accounts get a small one-time trial credit); it stays a paid, consented toggle for production (§5.5).

### 5.2 Routing policy

- **Primary for demo data and bulk:** Gemini Flash. It has 30 times Groq's token throughput and the only million-token context on a free tier, which is what whole-judgment digests need.
- **Fallback chain:** Gemini → Groq → Cerebras (prompts under 8K only) → Ollama. Built once in `providers.py` with `.with_fallbacks()` and `max_retries` for 429s.
- **Long-context calls** (digests, judgments over ~30K tokens): Gemini only, or a Kaggle batch job with a local model (§6).
- **Anything resembling real client text:** Groq only, or the production profile. Never Gemini, OpenRouter, SambaNova, or Mistral before opting out of training.
- **Two accounts, double the budget.** Each free tier is per account. Both team members create keys; the fallback chain alternates between them.
- **Structured output method per provider** as in §4.2. Every call still ends in the pure-Python quote verifier, so a weaker provider cannot make a claim "supported".

### 5.3 The demo's token budget

Digests are the expensive calls and they are precomputed on sprint day 9, so the live demo only pays for per-claim work.

| Step | Calls | Tokens (approx.) | Provider |
|---|---|---|---|
| Digests for the 8 demo judgments, precomputed | 8 | 400K | Gemini Flash (one call per judgment) |
| Stress-test: 8 citations × 5 calls (decompose, locate and quote, adjudicate, treatment memo, opposing-counsel memo) | 40 | 120K | Gemini primary, Groq and Cerebras as fallbacks |
| Draft mode: case digest, issues, ~6 propositions through the gate | 25 | 80K | Same |
| **Live total** | **65** | **200K** | Under Gemini's 250K TPM within the 7-minute run; under its RPD either way. Through Groq alone the same run would take about 25 minutes at 8K TPM, which is why Groq is the fallback, not the primary |

Sprint-day eval runs (50 gold items × 5 calls, about 750K tokens) fit inside a day on Gemini plus Mistral, and the once-per-judgment digest cache means the gold set's judgments are digested exactly once.

### 5.4 Local and self-hosted models

The laptop runs Ollama with Qwen3.5-4B at 4-bit for offline development and code-path testing; it is not used for verdict quality. The production profile serves open-weight models on a self-hosted GPU box, unchanged from version 0.1:

| Tier | Hardware | Model | Notes |
|---|---|---|---|
| 16-24 GB VRAM | RTX 4090/5090; cloud L4 or A10G | Qwen3.5-27B (Apache-2.0, 262K context) or Gemma 4 31B; gpt-oss-20b for the most reliable JSON | First production tier; ~30-60K working context after weights |
| 48-80 GB | A100, H100 | Qwen3.5-122B-A10B or gpt-oss-120b | Whole-judgment digests in one pass |

Serving: SGLang (prefix caching fits "one judgment, many claims"), vLLM as fallback, both OpenAI-compatible with JSON-schema constrained decoding, both Linux-only. Hugging Face TGI is archived and not used. Legal fine-tunes lose to 2026 general models on long-context reading; InLegalBERT is used only as a cheap tagger.

### 5.5 Paid cloud toggle (production, consented matters only)

Claude through the official `anthropic` SDK, model `claude-opus-5`; its citations feature returns verbatim `cited_text` with character offsets that feed the same quote verifier; Batches at half price for bulk digests. Enabled per matter with a consent record naming provider, model, retention setting and region, after confirming zero-data-retention eligibility for the chosen model.

---

## 6. Free GPU compute for batch work

The laptop cannot embed a million paragraphs or run PaddleOCR-VL. Free GPU notebooks can, as batch jobs whose outputs are imported into the local database.

| Service | Free allowance | Use |
|---|---|---|
| **Kaggle** | About 30 GPU-hours/week, 2×T4 (32 GB) or P100, 9-12 h sessions, internet on request, 20 GB persisted output ([Kaggle](https://www.kaggle.com/product-feedback/173129)) | Corpus embeddings with BGE-M3 (the hackathon subset in about an hour on 2×T4); digests with a local 9-14B model as an alternative to Gemini; PaddleOCR-VL over scanned annexures |
| **Modal** | $30/month compute credit, no card, no rollover (roughly 187 T4-hours) ([pricing](https://modal.com/pricing)) | Scheduled batch jobs such as a bi-monthly corpus refresh |
| **Lightning AI** | 15 credits/month, about 80 interruptible GPU-hours ([docs](https://lightning.ai/docs/team-management/academia/students)) | Spare capacity |
| Google Colab | T4, sessions not guaranteed, ~90-minute idle timeout | Backup only |
| Hugging Face ZeroGPU | 5 minutes/day on a free account | Not useful |

**Pattern.** A notebook reads the AWS Open Data subset directly from S3 (anonymous access), runs the model, writes parquet (paragraph id, embedding) or JSONL (digests) to its persisted output, and `orderorder ingest --embeddings <file>` imports it. Notebooks live in `notebooks/` and are versioned.

**Not for the live demo.** A Kaggle or Colab notebook can expose an OpenAI-compatible endpoint through a cloudflared or ngrok tunnel, but idle timeouts kill the kernel, the URL changes on restart, GPU allocation is not guaranteed, and both platforms' terms discourage serving. The live path is the free API tiers in §5.

---

## 7. Document parsing and OCR

- **Per-page routing** (ARCHITECTURE.md §3.2): text-layer pages go to Docling, image-only pages to OCR. Text-layer detection uses pypdfium2, not PyMuPDF.
- **Docling** (MIT) through `langchain-docling` for born-digital PDFs and DOCX; its layout models run on CPU.
- **PaddleOCR 3.7**: PP-OCRv6 on the laptop CPU for light scans; **PaddleOCR-VL-1.6** (0.9B parameters, 109 languages including Hindi/Devanagari, Apache-2.0) on a Kaggle GPU for batches and as a production container. It wants 8 GB VRAM minimum and compute capability 8.0 for the vLLM-based path, which a T4 lacks; use the standard PaddlePaddle inference path on Kaggle.
- **Tesseract** as a last resort only.
- **Evaluate before committing**: run Docling, PP-OCRv6 and PaddleOCR-VL over ~200 Indian judgment and annexure pages and pick per page type by measured character accuracy; vendor benchmarks do not include Indian court documents.
- Paid OCR APIs are not part of the hackathon build.

---

## 8. Retrieval and data layer

**Chunk = paragraph** with a judgment-context prefix (title, court, year, opinion type, role) prepended before embedding.

**Embeddings.**
- Corpus: BGE-M3 (1024 dimensions, Apache-2.0) on a Kaggle GPU (§6), no token cap and no data terms. Queries: the same model on the laptop CPU through `langchain-huggingface`, fast enough for single claims.
- Bake-off on the gold set, free of charge: Voyage gives 200M free tokens for the voyage-4 family and 50M for `voyage-law-2` ([pricing](https://docs.voyageai.com/docs/pricing)); Jina gives 10M shared tokens; Cohere's trial key allows 1,000 calls/month. Enough to compare embedders on pinpoint hit@k, not enough to embed the corpus (1-1.5M paragraphs is roughly 250-375M tokens), and the corpus embedder decides the query embedder.

**Reranker.** bge-reranker-v2-m3 on CPU over the top 20-40 candidates, about a second per citation. Jina's hosted reranker (within the same 10M free tokens, 100 RPM) is a drop-in alternative if CPU latency bites during the demo.

**Hybrid search** in SQL, scoped to one judgment for the locator and to the corpus for authority retrieval, exposed to LangGraph as a custom retriever:

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

Citation lookup is never vector search: normalised citation strings hit a unique index on `citation_alias.normalized`.

**Database.** PostgreSQL 17 + pgvector 0.8 in Docker on the development machine, volume under `ORDERORDER_DATA_DIR`; `halfvec` storage, HNSW with `m = 16`, `ef_construction = 128`, `ef_search = 100`; `hnsw.iterative_scan` for filtered queries. LangGraph checkpoints live in the same database. Row-level security keyed on `matter_id` for user-scoped tables.

| Corpus | Judgments | Paragraphs | Text | Vectors (halfvec, 1024-d) | Fits |
|---|---|---|---|---|---|
| Hackathon subset: SC, English, 2014-2025 | ~12-18k | ~1-1.5M | ~1.5 GB | ~2-3 GB (+ HNSW ~50%) | ~10 GB of local disk |
| Full Supreme Court 1950-2025 | ~40-50k | ~3-5M | ~4-5 GB | ~6-10 GB (+ HNSW) | A 32-64 GB RAM box |
| High Courts (all 25) | ~17.8M | hundreds of millions | ~1 TB+ | ~1 TB | Phase 3: shard by court |

**Why not a free hosted database.** Neon's free plan is 0.5 GB and Supabase's is 500 MB (and pauses after a week without requests); Qdrant Cloud's free cluster has 1 GB of RAM. None holds the hackathon subset's vectors. If judges need a public link, either the corpus is shrunk to a few hundred judgments for a Neon or Qdrant demo instance, or the API stays on the laptop.

---

## 9. Developer machine setup

What the build assumes: an x86-64 machine with four cores or more, about 16 GB of RAM, and no NVIDIA GPU. The constraint worth planning around is disk: the corpus, the Postgres volume, the model weights and the build caches together want tens of gigabytes, and every tool involved defaults to putting its share on the system drive. Choose a location with room and export it as `ORDERORDER_DATA_DIR`.

Do these before the sprint (day 0):

1. **Check free space on the system drive.** A drive close to full will destabilise Windows updates and Docker, and the caches below are exactly what fills it.
2. **Move Docker's disk image off the system drive.** Docker Desktop → Settings → Resources → Advanced → Disk image location. Cap WSL memory in `%UserProfile%\.wslconfig` with `[wsl2]` and `memory=8GB`.
3. **Point Ollama's model store at the data directory.** User environment variable `OLLAMA_MODELS=$DATA/ollama`, restart Ollama, pull the Qwen3.5-4B Q4 tag.
4. **Model caches under the data directory.** `HF_HOME` (BGE-M3, reranker, PaddleOCR models) and `UV_CACHE_DIR`.
5. **Python 3.12 via uv.** `winget install astral-sh.uv`, then `uv python install 3.12`; `uv sync` creates the environment from `pyproject.toml`.
6. **Project data directory.** `ORDERORDER_DATA_DIR` holds corpus files and the Postgres volume. Keep the code wherever you like, though a path outside a downloads folder is safer against cleanup tools.
7. **Node.** Node 22, with `corepack enable` for pnpm.
8. **Free accounts and keys** (both team members, one key each per provider): Google AI Studio (`GOOGLE_API_KEY`), Groq (`GROQ_API_KEY`), Cerebras (`CEREBRAS_API_KEY`), Mistral (`MISTRAL_API_KEY`, then opt out of training under Admin › Privacy), LangSmith (`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`), Kaggle (phone-verify to unlock GPU and internet), Hugging Face (model downloads), Indian Kanoon (`INDIANKANOON_TOKEN`, then apply for the non-commercial allowance). Optional: Voyage and Jina for the embedder bake-off. Verify each key with one call on day 0; keys live in `.env`, never in git.

What the laptop can and cannot do: run the whole application, the database, ingestion of the subset (minus embeddings), the engine end to end against free tiers or the local 4B model, the web UI and the evaluation harness. It cannot produce demo-quality verdicts locally or run PaddleOCR-VL; those go through the free tiers and Kaggle.

---

## 10. Application layer and Docker Compose

- **API surface (v0)**: `POST /matters`, `POST /matters/{id}/uploads`, `POST /briefs` (returns a job), `GET /briefs/{id}/verdicts`, `GET /jobs/{id}/events` (server-sent events), `GET /judgments/{id}` (viewer payload), `POST /drafts`, `GET /drafts/{id}`, `POST /drafts/{id}/export`, `POST /verdicts/{id}/override` (resumes the interrupted graph thread with the reviewer's decision).
- **Engine as a library**: `packages/engine` exposes `verify_brief(text, facts=None)` and `verify_citation(citation, proposition, facts=None)` by invoking the compiled LangGraph, with no web dependencies, plus a CLI (`orderorder verify`, `orderorder resolve`, `orderorder ingest`, `orderorder eval`).
- **Jobs**: FastAPI background tasks writing progress to a `job` table; graph threads are identified by job id so a restarted process resumes from the checkpoint. arq on Redis arrives with the production profile.
- **Exports**: python-docx for DOCX; the browser's print pipeline or WeasyPrint for PDF reports.

```yaml
services:
  postgres:  { image: pgvector/pgvector:pg17, volumes: ["${ORDERORDER_DATA_DIR}/postgres:/var/lib/postgresql/data"], profiles: [hackathon, prod] }
  api:       { build: apps/api,  profiles: [hackathon, prod] }     # FastAPI + LangGraph engine + background tasks
  web:       { build: apps/web,  profiles: [hackathon, prod] }
  ollama:    { image: ollama/ollama, profiles: [offline] }         # or the host's Ollama on Windows
  redis:     { image: redis:7,       profiles: [prod] }
  worker:    { build: apps/api, command: arq orderorder.worker.Settings, profiles: [prod] }
  sglang:    { image: lmsysorg/sglang, profiles: [prod], deploy: { resources: { reservations: { devices: [{ capabilities: [gpu] }] } } } }
  tei:       { image: ghcr.io/huggingface/text-embeddings-inference, profiles: [prod] }
  paddleocr: { build: services/paddleocr, profiles: [prod] }
  minio:     { image: minio/minio,     profiles: [prod] }
  langfuse:  { image: langfuse/langfuse, profiles: [prod] }
  caddy:     { image: caddy:2,         profiles: [prod] }
```

Environment variables of note: `LLM_PRIMARY` (for example `google_genai:gemini-2.5-flash`), `LLM_FALLBACKS` (comma-separated provider strings), `LLM_LONG_CONTEXT` (the provider allowed for digests), `LLM_SENSITIVE` (the only provider allowed for non-demo text), `EMBEDDINGS_MODEL=BAAI/bge-m3`, `RERANKER_MODEL=BAAI/bge-reranker-v2-m3`, `OCR_MODE=cpu|gpu`, `ORDERORDER_DATA_DIR`, `INDIANKANOON_TOKEN`, `INDIANKANOON_DAILY_QUOTA`, `LANGSMITH_TRACING`, `CLOUD_TOGGLE_ALLOWED=false`.

---

## 11. Repository layout

```
order-order/
  README.md
  docs/                      PRD, architecture, tech stack, roadmap
  apps/
    web/                     Next.js app
    api/                     FastAPI app; arq worker entrypoint for production
  packages/
    engine/                  verification + drafting engine (LangGraph, CLI)
      graph.py               StateGraph assembly, checkpointer, fan-out
      providers.py           init_chat_model + fallback chains from env
      state.py               Pydantic state models (verdict-in-progress, draft)
      nodes/                 one module per stage (resolve, locate, verify_quotes, ...)
      citations/             grammar, normaliser, alias table logic
      citator/
      facts/
      drafting/
      prompts/               versioned prompt files
      schemas/               Pydantic output schemas (verdict, digest, gold item)
    ingest/                  parsing, OCR, segmentation, roles, embeddings import, digests
  notebooks/
    kaggle_embed.ipynb       corpus embeddings on Kaggle 2xT4 -> parquet
    kaggle_digest.ipynb      digests with a local model -> JSONL
    kaggle_ocr.ipynb         PaddleOCR-VL over scanned annexures
  services/
    paddleocr/               production OCR container
  evals/
    gold/                    gold-set JSONL (anonymised)
    run.py                   harness; also syncs the LangSmith dataset
  infra/
    docker-compose.yml
    Caddyfile
  data/                      gitignored; relocatable via ORDERORDER_DATA_DIR
```

---

## 12. Bill of materials

### 12.1 Hackathon: ₹0

| Item | Provider | Free allowance | The limit that binds | Terms |
|---|---|---|---|---|
| LLM, primary | Google AI Studio, Gemini Flash | 10 RPM, 250K TPM, 500-1,500 RPD, 1M context | RPM during a burst | Trains on free-tier data: demo data only |
| LLM, privacy-safe | Groq, gpt-oss-120b | 30 RPM, 1,000 RPD, 8K TPM, 200K TPD | TPM and TPD | No training; ZDR available |
| LLM, fallback | Cerebras, gpt-oss-120b | 5-15 RPM, 30K TPM, 1M tokens/day | 8K context | Verify training opt-in |
| LLM, bulk | Mistral Experiment tier | ~1B tokens/month, ~1 rps (unpublished) | RPS | Opt out of training first |
| LLM, offline | Ollama, Qwen3.5-4B Q4 on the laptop | Unlimited | Quality and speed | Local |
| Corpus embeddings | BGE-M3 on Kaggle 2×T4 | 30 GPU-hours/week | Session length | Local model |
| Query embeddings, reranker | BGE-M3, bge-reranker-v2-m3 on the laptop CPU | Unlimited | ~1 s per rerank | Local |
| Embedder bake-off | Voyage (200M / 50M tokens), Jina (10M), Cohere trial (1,000 calls/month) | As listed | Tokens | API; public judgment text only |
| OCR | PP-OCRv6 on CPU; PaddleOCR-VL on Kaggle | Unlimited / 30 GPU-hours | — | Local |
| Scheduled batch | Modal | $30/month credit | Credit | — |
| Database and checkpoints | PostgreSQL + pgvector in Docker | Local disk | Disk | Local |
| Tracing and eval datasets | LangSmith Developer | 5,000 traces/month, 14-day retention | Traces (a 30-citation brief is ~250) | Cloud; demo data only |
| Frontend hosting, optional | Vercel Hobby | Non-commercial use | — | Hackathon only |
| API hosting, optional | Render free or Hugging Face Spaces | Spins down after 15 minutes / 48 hours | Cold start: ping before presenting | — |
| Case-law lookups | Indian Kanoon API | ₹500 signup credit; ₹10,000/month non-commercial allowance on approval; ₹0.20 per document after | Credits | "Powered by IKanoon" attribution |
| **Total** | | **₹0** | | |

### 12.2 Production (monthly, indicative, from the September 2026 research pass)

| Item | Cost |
|---|---|
| GPU box: E2E Networks A100-80G at ₹189/hour, business hours only | ~₹50,000 |
| Same, 24×7 | ~₹1.4 lakh (E2E spot at ~₹70/hour: ~₹50,000) |
| AWS Mumbai L4 (g6.xlarge) at ~$0.98/hour, 24×7 | ~$715 |
| CPU box for web, API, database if separate | ₹5,000-10,000 |
| Indian Kanoon pay-as-you-go | Under ₹5 per 30-citation brief |
| Storage, backups, domain, TLS | Under ₹3,000 |
| **Total** | **₹60,000 to 1.5 lakh depending on GPU choice** |

Per-unit economics are unchanged: a judgment digest costs ₹15-25 of GPU time once; each later verification of a claim against a digested judgment costs seconds of GPU time.

---

## 13. Security and privacy

- **The free-tier rule.** Free tiers that train on inputs (Gemini, Mistral before opt-out, OpenRouter, SambaNova) receive demo data only: moot memorials, synthetic matters, public judgment text. `LLM_SENSITIVE` names the single provider allowed for anything else during the hackathon (Groq), and the production profile keeps privileged text on the team's own hardware.
- API keys in `.env` files excluded from git; `.env.example` documents every variable; two sets of keys are never shared in chat.
- Postgres row-level security keyed on `matter_id`; integration tests assert cross-matter reads fail.
- Uploads scanned before parsing; parsed text stored, originals retained under the matter's prefix.
- Audit log table is append-only for application roles; delete-on-request removes the matter's rows, files, LangSmith or Langfuse traces and cache entries.
- No user document is used for training or fine-tuning by the team; the free-tier rule above is what keeps that promise on the provider side.
- Production adds encrypted volumes, TLS via Caddy, and worker containers with egress limited to the allow-listed judgment sources.

---

## 14. Deliberately not used

| Not used | Why |
|---|---|
| ReAct-style agents (`create_agent`) in the verification path | Verification must be deterministic and testable stage by stage; LangGraph is used as a state machine |
| The legacy chains now in `langchain-classic` | Superseded in LangChain 1.0 |
| LangGraph Platform | The open-source checkpointers are free and sufficient |
| Redis, arq, MinIO, Langfuse, Caddy in the hackathon profile | Nothing to gain for a two-person demo; all return in production |
| A rented GPU for the demo | The build must cost nothing; free API tiers serve the same open models |
| Tunnelled notebook endpoints for the live demo | Idle timeouts, changing URLs, unguaranteed GPUs, terms that discourage serving |
| OpenRouter free models, GitHub Models, Hugging Face Inference free credit, ZeroGPU | 50 requests/day with mandatory training consent; 8K/4K token caps; $0.10/month; 5 minutes/day |
| Free hosted Postgres for the corpus | 0.5 GB does not hold the vectors |
| Hugging Face TGI | Archived March 2026 |
| PyMuPDF, MinerU; Marker and Surya weights; Jina reranker weights; IL-TUR; Llama 4; Kimi K3 | Licences (§3) |
| Manupatra / SCC Online scraping | Prohibited by their terms |
| Model memory as a source of case law; sampling temperature as a safety control | Closed-world rule; grounding and string verification do that job |

---

## 15. Sources

LangChain and LangGraph: [1.0 announcement](https://blog.langchain.com/langchain-langgraph-1dot0/) · [release policy](https://docs.langchain.com/oss/python/release-policy) · [models](https://docs.langchain.com/oss/python/langchain/models) · [persistence](https://docs.langchain.com/oss/python/langgraph/persistence) · [v1 migration](https://docs.langchain.com/oss/python/migrate/langchain-v1) · [LangSmith pricing FAQ](https://docs.langchain.com/langsmith/pricing-faq). Free LLM tiers: [Groq rate limits](https://console.groq.com/docs/rate-limits) · [Groq models](https://console.groq.com/docs/models) · [Gemini pricing and data terms](https://ai.google.dev/gemini-api/docs/pricing) · [AI Studio rate-limit dashboard](https://aistudio.google.com/rate-limit) · [Cerebras free endpoint](https://pricepertoken.com/endpoints/cerebras/free) · [Mistral data controls](https://docs.mistral.ai/admin/monitor-comply/privacy-data-controls) · [OpenRouter limits](https://openrouter.ai/docs/api-reference/limits) · [SambaNova rate limits](https://docs.sambanova.ai/docs/en/models/rate-limits) · [Cloudflare Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/). Free compute: [Kaggle GPU quota](https://www.kaggle.com/product-feedback/173129) · [Modal pricing](https://modal.com/pricing) · [Lightning AI credits](https://lightning.ai/docs/team-management/academia/students) · [ZeroGPU](https://huggingface.co/docs/hub/en/spaces-zerogpu). Embeddings and rerank: [Voyage pricing](https://docs.voyageai.com/docs/pricing) · [Jina embeddings](https://jina.ai/embeddings/) · [Cohere rate limits](https://docs.cohere.com/docs/rate-limits). Hosting and databases: [Vercel pricing](https://vercel.com/pricing) · [Render free tier](https://render.com/docs/free) · [Supabase pricing](https://supabase.com/pricing) · [Neon free plan](https://neon.com/faqs/free-plan-limits-and-quotas) · [Qdrant pricing](https://qdrant.tech/pricing/) · [Upstash pricing](https://upstash.com/pricing). Models, OCR, retrieval and data sources are unchanged from version 0.1: [PaddleOCR releases](https://github.com/PaddlePaddle/PaddleOCR/releases) · [PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) · [Docling](https://github.com/docling-project/docling) · [pgvector](https://github.com/pgvector/pgvector/blob/master/CHANGELOG.md) · [Qwen3.5](https://huggingface.co/collections/Qwen/qwen35) · [gpt-oss](https://openai.com/index/introducing-gpt-oss/) · [SGLang](https://github.com/sgl-project/sglang/releases) · [E2E Networks pricing](https://www.e2enetworks.com/blog/nvidia-a100-price-india) · [Indian Kanoon API](https://api.indiankanoon.org/documentation/) · [AWS Open Data SC](https://registry.opendata.aws/indian-supreme-court-judgments/).
