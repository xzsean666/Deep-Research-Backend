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

**Search and Crawl are the two rows most likely to change** — new SearXNG
or Crawl4AI versions, or a full swap to a different engine. Neither is
called directly anywhere outside one adapter file each; see §10.

## 4. High Level Architecture

```mermaid
flowchart TB
    Agent[AI Agent] -->|REST| API[Deep Research Backend API]
    API --> RS[Research Service]
    RS --> SS[Search Service]
    RS --> DR[Document Repository]
    SS -->|SearchProvider interface| SX[SearXNG adapter] --> SXE[SearXNG]
    DR --> PG[(PostgreSQL\ndocuments / chunks / jobs)]
    PG --> CW[Crawl Worker\n(N instances)]
    CW -->|CrawlProvider interface| C4[Crawl4AI adapter] --> C4E[Crawl4AI]
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
`Keyword → SearchProvider (SearXNG adapter) → URLs` — discovers new pages.
Used by `/v1/research`. See §10 for why this goes through an interface
rather than calling SearXNG directly.

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
Claim job → Guard URL (§7) → CrawlProvider (Crawl4AI adapter) → Markdown + Metadata
   → Chunk → Embed chunks → Upsert Document + Chunks (transaction)
   → mark job completed
```

The worker calls `CrawlProvider.crawl(url)`, never the Crawl4AI SDK/HTTP
client directly — see §10.

Failures (timeout, guard rejection, extraction error) are recorded on the
job row with an error reason and retried with exponential backoff up to
`max_attempts`, after which the job moves to `dead_letter` and is visible via
`GET /v1/jobs?status=dead_letter` for operator inspection.

## 10. Provider Abstraction — Decoupling from SearXNG & Crawl4AI

SearXNG and Crawl4AI are both fast-moving projects and both fully
replaceable in principle (a different metasearch engine, a different
crawler). Neither should require touching `research/`, `worker/`, the API
layer, or the `documents` schema when its version — or the project itself
— changes. This is enforced with one adapter per dependency, not by
convention.

### 10.1 The rule

No module outside `services/search/` imports anything SearXNG-specific.
No module outside `services/crawl/` imports anything Crawl4AI-specific.
Everyone else depends only on a small interface and a stable internal
result shape:

```
app/services/search/
├── provider.py            # SearchProvider Protocol + SearchResult dataclass
│                           #   (url, title, snippet, rank) — the stable shape
├── searxng_provider.py    # SearXNGSearchProvider(SearchProvider)
│                           #   the ONLY file that knows SearXNG's JSON response shape
└── __init__.py             # get_search_provider() factory, reads SEARCH_PROVIDER config

app/services/crawl/
├── provider.py            # CrawlProvider Protocol + CrawlResult dataclass
│                           #   (markdown, title, metadata) — the stable shape
├── crawl4ai_provider.py   # Crawl4AICrawlProvider(CrawlProvider)
│                           #   the ONLY file that knows Crawl4AI's API/SDK shape
├── url_guard.py            # SSRF validation (§7) — provider-agnostic, unchanged either way
└── __init__.py              # get_crawl_provider() factory, reads CRAWL_PROVIDER config
```

`services/research/` and `services/worker/` call `SearchProvider.search(...)`
and `CrawlProvider.crawl(...)` through the factory — never
`SearXNGSearchProvider` or `Crawl4AICrawlProvider` by name. Swapping either
dependency, or upgrading it across a breaking API change, means editing one
adapter file; nothing that calls through the interface needs to change.

### 10.2 What an upgrade actually touches

| Change | What you edit |
|---|---|
| SearXNG minor/patch upgrade, response shape unchanged | Nothing — bump the pinned image tag in `docker-compose.yml` |
| SearXNG version bumps its JSON response shape | `searxng_provider.py` only, until it maps back to `SearchResult` |
| Swap SearXNG for a different search engine entirely | New `*_provider.py` implementing `SearchProvider`, flip `SEARCH_PROVIDER` config |
| Crawl4AI upgrade (any of the above, same reasoning) | `crawl4ai_provider.py` only |

### 10.3 Guarding against silent breakage

An adapter that silently starts mis-mapping fields after an upstream
upgrade is worse than one that fails loudly, so each adapter has a
dedicated **contract test** (`tests/contract/test_searxng_provider.py`,
`tests/contract/test_crawl4ai_provider.py`) that asserts a real (or
recorded fixture) response from that dependency maps correctly to
`SearchResult` / `CrawlResult`. Run these first after bumping a pinned
version in `docker-compose.yml`, before running the rest of the suite —
they're the fastest signal that an upgrade changed the response shape.

Image tags for `searxng` and `crawl4ai` in `docker-compose.yml` are always
pinned to a specific version, never `latest` — an upgrade is a deliberate,
reviewable change (bump tag → run contract tests → commit), not something
that happens implicitly on a redeploy. See
[INTEGRATIONS.md](INTEGRATIONS.md) for where to check each project's
current release notes before bumping.

## 11. Result Composition for AI Consumption

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

## 12. Observability

- Structured (JSON) logs, one correlation `request_id` threaded through
  Search → Lookup → Crawl → Store for a given `/v1/research` call.
- Metrics: cache hit rate, crawl success rate, job queue depth,
  per-stage latency (search / crawl / embed), dead-letter count.
- `/health` (liveness) and `/ready` (DB connectivity) endpoints on both API
  and worker.

## 13. Deployment Topology

Fully self-hosted — every component runs from this stack's own
docker-compose, no managed/external services:

```
services: api (N replicas), worker (M replicas),
          postgres (pgvector/pgvector official image — §13.1),
          searxng (built from vendored source — §13.2),
          crawl4ai (built from vendored source — §13.2)
```

API and worker scale independently. PostgreSQL is the only stateful service
and the only thing that needs backup/HA planning. See [BUILD.md](BUILD.md).

### 13.1 Database image — official, unmodified

Postgres uses the [`pgvector/pgvector`](https://github.com/pgvector/pgvector#docker)
official image (e.g. `pgvector/pgvector:pg16`), **not** the plain
`postgres` image with the extension installed by hand — `CREATE EXTENSION
vector` in the init migration then just works, with no image-build step or
manual `apt install postgresql-XX-pgvector` in this repo to maintain.
Upgrading the Postgres major version means bumping this one tag; the
extension ships with it. There is no need to patch Postgres itself, so an
official prebuilt image is the right call here.

### 13.2 Search & Crawl images — built from vendored source, not pulled prebuilt

SearXNG and Crawl4AI are different: they may need local patches (a search
engine config tweak, a crawler extraction fix) that an official prebuilt
image can't accommodate. So instead of `image: searxng/searxng:<tag>` /
`image: unclecode/crawl4ai:<tag>`, both are built from source that this
repo controls directly:

```
vendor/
├── searxng/      # git submodule, pinned to a specific upstream commit
└── crawl4ai/     # git submodule, pinned to a specific upstream commit — has its own root Dockerfile
```

`docker-compose.yml` points the `crawl4ai` service's build context directly
at `vendor/crawl4ai`, using **that project's own Dockerfile** — it's a
single self-contained build, part of the vendored source, so a local patch
that touches it is just another commit on the `local-patches` branch.

**SearXNG needed one exception**, discovered when actually building it:
upstream splits its build across `container/builder.dockerfile` and
`container/dist.dockerfile`, where the second stage's `FROM
localhost/searxng/searxng:builder` expects the first to already exist as a
separately pre-tagged local image — something `docker compose build`
cannot express on its own. `docker/searxng/Dockerfile` merges both stages
into one multi-stage build (named stages instead of a pre-tagged image);
its header comment explains this and points at BUILD.md §10.2 for what to
re-check when the pinned commit is bumped. This is the one wrapper
Dockerfile in the repo — everything else builds straight from its
vendored/official source.

SearXNG also needs `deploy/searxng/settings.yml` (mounted read-only into
the container) to enable JSON output, which upstream disables by default —
`SearchProvider`'s SearXNG adapter depends on `?format=json`. See that
file and the `searxng` service in `docker-compose.yml`.

Crawl4AI needed one thing too, also only discovered by deploying it for
real: its own entrypoint refuses to bind beyond `127.0.0.1` unless
`CRAWL4AI_API_TOKEN` is set — which would make it unreachable from
`api`/`worker` over the docker network, not just from the host. Setting it
also turns on Bearer-token auth enforcement on every Crawl4AI request, which
`Crawl4AICrawlProvider` sends. See SPEC.md §9 and
[docs/DEPLOYMENT.md](DEPLOYMENT.md) for how this was found.

Each submodule is checked out on a local branch (e.g. `local-patches`)
based on a specific pinned upstream commit/tag. Any modification this
project needs lives as a commit on that local branch — never as an
uncommitted diff — so it survives an upgrade and is reviewable like any
other change.

This does not weaken the decoupling in §10: `SearchProvider` and
`CrawlProvider` only depend on each project's HTTP contract, which is the
same whether the running container came from an official image or a local
patched build. Vendoring source is about *being able to change the
dependency's behavior*; the provider interface is about *isolating the
rest of the app from that dependency's shape*. Both apply at once.

Upgrade procedure for a vendored dependency — see
[BUILD.md §10](BUILD.md#10-upgrading-self-hosted-dependencies).

All four self-hosted images (`postgres`/pgvector, `searxng`, `crawl4ai`,
plus this app's own `api`/`worker` image) are version-pinned, never
`latest` — for Postgres that means an image tag; for SearXNG/Crawl4AI that
means the submodule commit their Dockerfile builds from.

## 14. Project Structure

```
deep-research-backend/
├── app/
│   ├── api/                 # FastAPI routers (thin, no business logic)
│   ├── services/
│   │   ├── research/        # orchestrates search + lookup + crawl + merge
│   │   ├── search/          # SearchProvider interface + SearXNG adapter (§10), local FTS, semantic search
│   │   ├── crawl/           # CrawlProvider interface + Crawl4AI adapter (§10), url_guard (§7), chunking
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
│   └── contract/                # per-provider contract tests (§10.3)
├── vendor/                       # git submodules, pinned commit + local patch branch (§13.2)
│   ├── searxng/
│   └── crawl4ai/                 # has its own root Dockerfile — docker-compose builds this context directly
├── docker/searxng/Dockerfile      # merges searxng's split builder/dist build (§13.2) — the one wrapper Dockerfile
├── deploy/searxng/settings.yml    # mounted config enabling JSON output (§13.2)
├── docs/                          # this directory
├── Dockerfile                     # builds the api/worker image (this app's own code)
├── docker-compose.yml
├── AGENT.md
└── main.py
```

Module boundary rule: `api/` never imports `repositories/` directly, and
`repositories/` never imports `services/`. Data flows one direction:
`api → services → repositories → models`.

## 15. Future Extensions

No architectural change is required to add: PDF import, GitHub repository
ingestion, RSS, sitemap crawling, Notion, Confluence, AI summary
post-processing, multi-language support, or an MCP server front-end — each
is a new *source* that produces a `Document` through the existing pipeline.

## 16. Design Philosophy

```
Search → Document → Job → API
```

**Search** discovers. **Document** is the single model — cache and knowledge
store at once. **Job** does the background work so the API never blocks on
it longer than its wait budget. **API** is the one door an AI Agent walks
through; everything behind it is an implementation detail the agent never
needs to know about.
