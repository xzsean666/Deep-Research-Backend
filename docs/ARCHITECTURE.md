# Architecture

> Version: 2.0 (production revision of the original design)
> Status: Design approved, implementation not started
> See [nextsession.md](nextsession.md) for current progress.

## 1. Overview

Deep Research Backend is a Research API for AI Agents.

It is not a Search API and not a thin wrapper around Crawl4AI. It owns the
entire research pipeline and exposes exactly one primary operation:

```
POST /v1/research
```

Given a keyword, it returns a complete, structured, analyzable result set —
built from cached documents where possible and freshly crawled pages where
necessary — without the caller ever touching Search, Crawl, or Storage
directly.

The system has exactly four core concepts:

| Concept | Responsibility |
|---|---|
| **Search** | Discover candidate URLs for a keyword (online) or candidate documents (local/semantic) |
| **Document** | The single data model. Also the cache. Also the knowledge store. |
| **Job** | Background crawl/refresh/embedding work, queued in PostgreSQL |
| **API** | The only interface AI Agents talk to |

Every future data source (PDF, GitHub repo, RSS, Notion, Confluence, ...)
terminates in a `Document`. The core architecture never needs to change to
add a source.

## 2. Design Goals

- **API First** — one call in, one complete result out
- **Document First** — one data model for cache, storage, and search
- **Bounded-Wait First** — no endpoint blocks indefinitely on a crawl
- **Safety First** — the crawler fetches arbitrary URLs; SSRF and abuse
  protections are part of the architecture, not an afterthought
- **Single Infrastructure Dependency** — PostgreSQL is the only stateful
  service (queue, full text search, vector search, metadata)
- **Async First**, **Easy Deployment**, **Easy Extension**, **Production Ready**

## 3. Technology Stack

| Component | Technology | Why |
|---|---|---|
| API | FastAPI | async-native, typed request/response models |
| Search | SearXNG | self-hosted, no API key, aggregates multiple engines |
| Crawl | Crawl4AI | markdown-first extraction, LLM-friendly output |
| Database | PostgreSQL | one system for relational + FTS + vector |
| Vector | pgvector (HNSW index) | avoids a separate vector DB |
| Full Text Search | PostgreSQL `tsvector` | avoids Elasticsearch |
| Queue | PostgreSQL (`FOR UPDATE SKIP LOCKED`) | avoids Redis/RabbitMQ |
| ORM | SQLAlchemy (async) | typed models, migration-friendly |
| Migration | Alembic | schema versioning |
| Config | pydantic-settings | single typed config surface |

No Redis. No RabbitMQ. No Elasticsearch. No separate vector database.

## 4. High Level Architecture

```mermaid
flowchart TB
    Agent[AI Agent] -->|REST| API[Deep Research Backend API]
    API --> RS[Research Service]
    RS --> SS[Search Service]
    RS --> DR[Document Repository]
    SS --> SX[SearXNG]
    DR --> PG[(PostgreSQL\ndocuments / chunks / jobs)]
    PG --> CW[Crawl Worker\n(N instances)]
    CW --> C4[Crawl4AI]
    CW --> EMB[Embedding Service]
    EMB --> PG
```

Workers are stateless and horizontally scalable; all coordination happens
through PostgreSQL row locks. There is no worker-to-worker communication.

## 5. Core Workflow — Research

`/v1/research` supports two execution modes, chosen per request via
`execution_mode` (SPEC §3). Both share the same search → normalize → lookup
→ enqueue pipeline; they differ only in what happens after a job is
enqueued.

```mermaid
flowchart TD
    A[Keyword] --> B[SearXNG search]
    B --> C[Normalize result URLs]
    C --> D[Lookup Documents by normalized_url]
    D --> E{Found & not expired?}
    E -->|Yes| F[Attach as cached]
    E -->|No| G[Enqueue crawl_job]
    G --> X{execution_mode}
    X -->|blocking| I["Await job (concurrently with\nevery other job from this request)"]
    X -->|background| P["Mark document pending, attach job_id\n— do not wait"]
    I --> K{Terminal state reached}
    K -->|completed| F
    K -->|"dead_letter (max_attempts exhausted)"| J[Mark document failed, with reason]
    F --> L[Merge all documents]
    J --> L
    P --> L
    L --> M[Return ResearchResult]
```

### 5.1 `execution_mode: "blocking"` (default)

Blocks until **every** document reaches a terminal state — `cached`,
`crawled`, or `failed` (permanently, after retries are exhausted). No
request-level timeout, no `pending` status: the caller either gets a
genuinely complete result, or an explicit, final failure reason for the
specific pages that could not be retrieved.

- All jobs created by a single call are awaited **concurrently** (e.g.
  `asyncio.gather`, never a loop of sequential awaits) — wall-clock cost is
  the slowest single job, not the sum of all jobs it triggered.
- A job only stops being retried when it reaches `dead_letter`
  (`attempts >= max_attempts`, §9), itself bounded by
  `CRAWL_FETCH_TIMEOUT_SECONDS` × `JOB_MAX_ATTEMPTS` with backoff (SPEC
  §9). That per-job retry ceiling — not an arbitrary request-level clock —
  is what makes a document `failed`.
- Top-level `status` is `"complete"` (every document resolved
  successfully) or `"complete_with_failures"` (one or more pages
  permanently failed). Never `"partial"` — this mode never returns before
  every document reaches a terminal state.

> **Operational note.** Because there is no request-level cap, worst-case
> latency is bounded only by the slowest job's own retry ceiling — with
> the SPEC §9 defaults (`CRAWL_FETCH_TIMEOUT_SECONDS = 20`,
> `JOB_MAX_ATTEMPTS = 3`, exponential backoff), that's roughly one to two
> minutes worst case, not seconds. Any reverse proxy, load balancer, or
> client HTTP timeout in front of the API **must** be configured well
> above this ceiling when calling in blocking mode, or the connection will
> be cut before the backend finishes — see
> [BUILD.md §9](BUILD.md#9-long-lived-request-timeouts).

### 5.2 `execution_mode: "background"`

Returns as soon as the cache lookup finishes — never waits on a crawl.
Documents that were already cached and fresh come back immediately;
everything else is enqueued and returned as `status: "pending"` with its
`job_id`. Top-level `status` is `"complete"` if nothing needed enqueuing,
otherwise `"partial"`.

The caller resolves pending documents one of two ways:

- Poll `GET /v1/jobs/{id}` for each `job_id`, or
- Simply call `POST /v1/research` again with the same `query` later — by
  then the previously-pending documents are cached and come back
  immediately, no different from any other cache hit.

Use this mode when issuing many research calls up front and collecting
results later (batch workflows), where blocking on each one serially would
be far slower than letting the worker pool drain the queue in parallel.

## 6. Document Lifecycle & Cache Strategy

There is no separate cache layer. The `documents` table *is* the cache.

```mermaid
flowchart LR
    URL --> Normalize --> Lookup
    Lookup -->|hit, fresh| Return
    Lookup -->|miss or expired| Crawl --> Extract[Markdown + Metadata] --> Chunk --> Embed --> Store --> Return
```

### 6.1 URL Normalization (cache key)

Normalization is what makes "already-crawled pages are never re-crawled"
true. Rules, applied in order:

1. Lowercase scheme and host
2. Strip default ports (`:80`, `:443`)
3. Strip fragment (`#...`)
4. Strip known tracking query params (`utm_*`, `gclid`, `fbclid`, `ref`, ...)
5. Sort remaining query params alphabetically
6. Strip trailing slash on path (except root `/`)

The normalized form is stored in `documents.normalized_url` with a unique
constraint. This is the only lookup key the pipeline ever uses.

### 6.2 Refresh / TTL Strategy

| Document type | TTL | Detection |
|---|---|---|
| Docs / reference | 30 days | domain heuristic + content-type |
| GitHub | 7 days | host == github.com |
| Blog | 7 days | default fallback |
| News | 6 hours | domain heuristic |

On lookup, an expired document is still returned immediately (stale data is
better than a slow response for an AI agent that just needs *something* to
reason about) while a refresh job is enqueued in the background. The caller
never waits on a refresh; only on a first-time crawl.

## 7. Security — Crawl Target Validation (SSRF)

The crawler accepts URLs derived from search results and from the
`/v1/crawl` endpoint, which can be called with an arbitrary URL. Before any
URL reaches Crawl4AI it passes through a mandatory validation stage:

- Resolve DNS and reject if the resolved IP is in a private/link-local/
  loopback range (RFC1918, `127.0.0.0/8`, `169.254.0.0/16` — this blocks
  cloud metadata endpoints such as `169.254.169.254`), or is a
  multicast/reserved range.
- Reject non-`http(s)` schemes.
- Re-validate on every redirect hop (no blind redirect following into a
  private IP).
- Enforce a max response size and a hard fetch timeout per page.
- Enforce a per-domain concurrency limit (politeness) independent of global
  worker concurrency.

This validation lives in a single `services/crawl/url_guard` module — no
other module is allowed to call Crawl4AI directly.

## 8. Search Pipeline

Three distinct retrieval modes, all normalized into `Document` results.

### 8.1 Online Search
`Keyword → SearXNG → URLs` — discovers new pages. Used by `/v1/research`.

### 8.2 Local Full Text Search
`Keyword → PostgreSQL tsvector → Documents` — searches already-crawled
content, no network calls. Used by `/v1/documents/search`.

### 8.3 Semantic Search
`Question → Embedding → pgvector (HNSW) over document_chunks → Documents`
— used for RAG / deep-research follow-up queries. Embeddings are computed
**per chunk**, not per document, so retrieval granularity matches what an
LLM actually needs in its context window.

## 9. Crawl Worker & Job Queue

Workers are a pull-based pool; there is no push/dispatch. Any number of
worker processes can run against the same PostgreSQL instance safely.

```sql
-- job claim, executed inside a transaction
SELECT * FROM crawl_jobs
WHERE status = 'pending' AND next_attempt_at <= now()
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1;
```

Job state machine:

```
pending → running → completed
             │
             ├─→ failed (retryable: attempts < max_attempts)
             │     └─→ pending, next_attempt_at = now() + backoff(attempts)
             └─→ dead_letter (attempts >= max_attempts)
```

Worker pipeline per job:

```
Claim job → Guard URL (§7) → Crawl4AI → Markdown + Metadata
   → Chunk → Embed chunks → Upsert Document + Chunks (transaction)
   → mark job completed
```

Failures (timeout, guard rejection, extraction error) are recorded on the
job row with an error reason and retried with exponential backoff up to
`max_attempts`, after which the job moves to `dead_letter` and is visible via
`GET /v1/jobs?status=dead_letter` for operator inspection.

## 10. Result Composition for AI Consumption

This is the actual product: a single, analyzable payload. The response
schema (full detail in [SPEC.md](SPEC.md)) makes three things explicit for
the calling agent:

- **Per-document status** — `cached | crawled | pending | failed`, so the
  agent knows which documents are trustworthy-complete right now.
- **Ranking signal, not just order** — each document carries the score(s)
  that produced its position (`search_rank`, `semantic_score` when
  applicable), so the agent can re-weight or filter.
- **Token-budget-aware content** — every document includes a short
  `summary` (always present, bounded length) alongside the full `markdown`
  (present when within a configurable size cap; otherwise truncated with a
  pointer to `GET /v1/documents/{id}` for the full text). This keeps a
  multi-document research response usable directly in an LLM context window
  without the agent having to pre-filter.

## 11. Observability

- Structured (JSON) logs, one correlation `request_id` threaded through
  Search → Lookup → Crawl → Store for a given `/v1/research` call.
- Metrics: cache hit rate, crawl success rate, job queue depth,
  per-stage latency (search / crawl / embed), dead-letter count.
- `/health` (liveness) and `/ready` (DB connectivity) endpoints on both API
  and worker.

## 12. Deployment Topology

Single docker-compose stack for local/small production:

```
services: api (N replicas), worker (M replicas), postgres (with pgvector
extension), searxng, crawl4ai
```

API and worker scale independently. PostgreSQL is the only stateful service
and the only thing that needs backup/HA planning. See [BUILD.md](BUILD.md).

## 13. Project Structure

```
deep-research-backend/
├── app/
│   ├── api/                 # FastAPI routers (thin, no business logic)
│   ├── services/
│   │   ├── research/        # orchestrates search + lookup + crawl + merge
│   │   ├── search/          # SearXNG client, local FTS, semantic search
│   │   ├── crawl/           # Crawl4AI client, url_guard (§7), chunking
│   │   ├── document/        # normalization, TTL policy, upsert
│   │   └── worker/          # job claim loop, retry/backoff
│   ├── repositories/        # SQLAlchemy queries only, no business logic
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/               # pydantic request/response models
│   ├── database/               # engine, session, migrations entrypoint
│   ├── config/                 # pydantic-settings, single source of config
│   └── utils/
├── migrations/                 # Alembic
├── tests/
├── docs/                        # this directory
├── AGENT.md
└── main.py
```

Module boundary rule: `api/` never imports `repositories/` directly, and
`repositories/` never imports `services/`. Data flows one direction:
`api → services → repositories → models`.

## 14. Future Extensions

No architectural change is required to add: PDF import, GitHub repository
ingestion, RSS, sitemap crawling, Notion, Confluence, AI summary
post-processing, multi-language support, or an MCP server front-end — each
is a new *source* that produces a `Document` through the existing pipeline.

## 15. Design Philosophy

```
Search → Document → Job → API
```

**Search** discovers. **Document** is the single model — cache and knowledge
store at once. **Job** does the background work so the API never blocks on
it longer than its wait budget. **API** is the one door an AI Agent walks
through; everything behind it is an implementation detail the agent never
needs to know about.
