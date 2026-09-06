# OrderOrder — deployment

| | |
|---|---|
| **Version** | 0.1 |
| **Date** | 6 September 2026 |
| **Companion documents** | [ARCHITECTURE.md](ARCHITECTURE.md) §10 · [TECH_STACK.md](TECH_STACK.md) |

[ARCHITECTURE.md](ARCHITECTURE.md) §10 describes the topology this is heading for. This document is
narrower and more useful: what is actually built, what will stop you, and in what order to fix it.

---

## 1. What is ready and what is not

| | state |
|---|---|
| **Verification (Surface A)** | Deployable. Eight of twelve failure modes need no model at all, measured on held-out data, and a provider outage degrades to *not checked* rather than to a wrong answer. |
| **Search** | Deployable. Lexical, no model, 91% case@1 on a quoted line. Weak on paraphrases (33%) and that limit is documented rather than hidden. |
| **Drafting (Surface B)** | **Not for production.** The gate refuses to bind anything it has doubts about, which is a structural guarantee. Whether it *has* doubts about extent of support depends on the model, and a fast model gets that wrong. Ship it behind a flag, as an artefact to read, not a document to file. |

Deploy verification first. It is a product a lawyer can use this month, and the claim it makes is one
the numbers support.

---

## 2. The six things that will stop you

### 2.1 A model that answers — the only real blocker

Everything else on this list is an afternoon's work. This one is a decision.

| option | latency | verdict |
|---|---|---|
| Gemini free tier | 10 requests/minute | 18 minutes for a three-proposition draft. Unusable for serving. |
| `qwen3:4b`, local, CPU | **247 s per call**, measured | Proves the wiring. Not a service. |
| A routed gateway on free endpoints | 80% `429`, measured | Answers the health probe and then fails four calls in five. |
| A paid API tier | seconds | The only one that serves. |

Two things to know before choosing. The engine is schema-bound everywhere, so an endpoint that accepts
requests but will not fill a JSON schema is useless to it — `orderorder doctor --probe` makes one real
call and tells you. And with a router in front, run
`scripts/gateway-failure-rate.py --marker <file>` over a real workload: a route can pass the probe and
still be mostly rate-limited, which produces a report full of *not assessed* that looks like data.

### 2.2 Exposure

`orderorder serve` binds `127.0.0.1` and asks for nothing, because on a single-user machine there is nothing to
protect. Bound anywhere else it **requires** `ORDERORDER_API_TOKEN` and refuses to start without one:

```bash
export ORDERORDER_API_TOKEN=$(openssl rand -hex 32)
orderorder serve --host 0.0.0.0
```

The compose `serve` profile declares the same variable with no default, so a stack brought up without
one fails while compose is still interpolating. `/api/health` is the one route that answers without a
token — a load balancer needs it and it gives nothing away.

Put a reverse proxy in front for TLS. The container publishes to `127.0.0.1:8000` deliberately, so
exposure stays an explicit decision.

### 2.3 Jobs live in one process

`web/jobs.py` is a dictionary. Verdicts stream to the page from the process that started the job, so
**run exactly one worker.** With two, requests land on whichever worker answers and job lookups 404 at
random. `orderorder serve` never passes `--workers`; the trap is running uvicorn directly.

A single process is fine for a pilot — a job is worthless once the tab closes, which is why it was
built this way. It is not fine for horizontal scaling, and the jobs table in ARCHITECTURE §4.13 is the
fix when that day comes.

### 2.4 SQLite is one writer

The corpus is a 1.2 GB SQLite file. Reads are fine and concurrent; writes are not. Ingestion, the
full-text index rebuild and `orderorder embed` all write, so do not run them against a database that
is serving. `infra/docker-compose.yml` has Postgres with pgvector ready for when that matters —
`DATABASE_URL` switches it, and the corpus must be re-ingested rather than copied.

### 2.5 No migrations

`init_db()` calls `create_all()`, which creates missing tables and never alters an existing one. The
first schema change after you deploy is therefore manual. Alembic is in `pyproject.toml` and unused;
wiring it, with the current schema stamped as the baseline, is the prerequisite for a second release.

### 2.6 The resume list is held in memory, so a bigger corpus is a bigger box

Ingestion loads the judgments still needing text into a list before it fetches anything. A `Judgment`
ORM object measured **3.1 KB** on the Supreme Court corpus, so the list alone is:

| corpus | judgments | the resume list |
|---|---|---|
| Supreme Court 2013-2025, what is held today | 9,429 | 30 MB |
| Supreme Court 1950-2025 | ~50,000 | ~0.2 GB |
| One large High Court | ~1,000,000 | ~3 GB |
| All 25 High Courts | ~17,800,000 | ~56 GB |

Up to the whole Supreme Court this does not matter. Past it, ingest in batches: `--limit` now bounds
the *query* rather than slicing the list afterwards, so `--limit 20000` reads twenty thousand rows and
not the corpus, and the run is resumable, so repeating it walks the corpus a batch at a time. `--year`
does the same by year, and is the better handle when the source data arrives that way.

What is not yet fixed is that the list exists at all, and that `BulkResult` keeps one `Outcome` per
judgment for the closing report. Both are bounded by the batch rather than by the corpus once you use
`--limit`, which is why batching is the answer here rather than a rewrite. Streaming the resume list
by keyset and reporting incrementally is the change that removes the ceiling; it needs a decision
about ingestion order, which is currently newest-first and load-bearing for a demo.

The queue in front of the workers is already bounded and does not grow with the corpus: four
judgments per worker are submitted ahead, rather than one `Future` per judgment for the whole run.

**On disk**, measured on the same corpus — 9,429 judgments, 409,499 paragraphs, 1.22 GB:

| | size | share | |
|---|---|---|---|
| `paragraph` | 493 MB | 40% | the text itself |
| `paragraph_fts_content` | 468 MB | 38% | **a second copy of the same text** |
| `paragraph_fts_data` | 144 MB | 12% | the inverted index, the part that does the work |
| indexes on `paragraph` | 89 MB | 7% | |
| everything else | 28 MB | 2% | judgments, aliases, opinions, citations |

That is **2.9 KB per paragraph**, of which 1.1 KB is the duplicate. The full-text index is a standalone
FTS5 table, so it keeps its own copy of every paragraph body. An external-content table
(`content='paragraph'`) would not, at the cost of a join to read a body back and of the `judgment_id`
column the queries currently take from the index for free. It is a real 38% of the database and it is
worth doing before the corpus is large, not after; it is not done here because it changes the shape of
the search query and every index built so far would need rebuilding.

Budget **~3 KB a paragraph** until then, and remember the corpus is one SQLite file: §2.4.

---

## 3. A first deployment

```bash
# On the box, with the corpus already ingested onto a volume:
export ORDERORDER_API_TOKEN=$(openssl rand -hex 32)
export LLM_PRIMARY=... OPENAI_API_KEY=...          # or GOOGLE_API_KEY, GROQ_API_KEY

docker compose -f infra/docker-compose.yml --profile serve up -d --build
curl -s localhost:8000/api/health                   # no token needed
curl -s -H "Authorization: Bearer $ORDERORDER_API_TOKEN" \
     "localhost:8000/api/search?q=a+misrepresentation+vitiates+consent"
```

The image has never been built — see the commit that added it. Expect the first `--build` to surface
something.

**The corpus is not in the image.** It is 1.2 GB of state that outlives any version of this code, and
it mounts at `/data`. Build it on the box, or copy the SQLite file in, and check
`orderorder stats` before serving.

**Chown the volume, or nothing can write.** The image runs as uid **10001**, not root — a process
that cannot rewrite its own source is one exploit less. `/data` is created and owned by that user in
the image, so running with no volume works and a *named* volume inherits the right ownership. A
**bind** mount does not: the host directory's ownership is what the container sees, and a root-owned
one leaves the engine unable to write its own corpus. The failure arrives at the first request rather
than at boot, which makes it look like a bug in the engine.

```bash
sudo install -d -o 10001 -g 10001 /srv/orderorder-data     # before the first run
```

**Keys never enter a layer.** No `ARG`, no `COPY` of `.env`, and `.dockerignore` excludes it — a
secret baked into an image is published to whoever can pull it, and `docker history` shows it even
after a later layer deletes the file.

---

## 4. Before anyone else uses it

- **Attribution.** Judgment data is CC-BY-4.0 from AWS Open Data. The attribution is in the README and
  belongs anywhere the corpus is served.
- **The disclaimer is not decoration.** Every export carries it and every claim about a citation is
  three-state: supported, checked-and-not-supported, or *not checked*. A deployment that flattens that
  third state into either of the others is the failure this whole engine exists to prevent.
- **Uploaded briefs are privileged.** Nothing is sent anywhere except the model calls, and
  `LLM_SENSITIVE` names the provider allowed to see text that is not demo data. Honour it.
- **Rate limits are a correctness problem, not just a speed one.** When a provider fails, the engine
  records *not assessed* — correct, and it means a throttled deployment quietly checks less than it
  appears to. Watch the abstention rate.
