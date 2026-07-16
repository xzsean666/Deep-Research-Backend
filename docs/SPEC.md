# Specification

> Defines exact contracts: API request/response shapes, data models, config,
> and error format. This is the authoritative reference when implementing —
> if code and this file disagree, this file wins until both are updated
> together in the same change.
>
> Architectural reasoning lives in [ARCHITECTURE.md](ARCHITECTURE.md); this
> file is the contract, not the rationale.

## 1. Conventions

- All timestamps: ISO 8601 UTC (`2026-07-16T10:00:00Z`).
- All IDs: UUID v4 strings.
- All endpoints are under `/v1`.
- Auth: `Authorization: Bearer <api_key>` header, required on every route
  except `/health` and `/ready`.
- Content type: `application/json` for all request/response bodies.

## 2. Error Format

Every error response uses the same envelope:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "limit must be between 1 and 50",
    "request_id": "b3f1c2..."
  }
}
```

Standard `code` values: `INVALID_REQUEST`, `NOT_FOUND`, `UNAUTHORIZED`,
`RATE_LIMITED`, `CRAWL_BLOCKED` (URL rejected by the SSRF guard, §7 of
ARCHITECTURE.md), `UPSTREAM_UNAVAILABLE` (SearXNG/Crawl4AI down),
`INTERNAL_ERROR`.

## 3. `POST /v1/research`

The primary endpoint. Search + cache + crawl + merged result. See
[ARCHITECTURE.md §5](ARCHITECTURE.md#5-core-workflow--research) for the
full behavior of each `execution_mode`.

### Request

```json
{
  "query": "FastAPI async best practices",
  "limit": 5,
  "refresh": false,
  "execution_mode": "blocking",
  "mode": "online"
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `query` | string | required | 1–500 chars |
| `limit` | int | 5 | 1–20 |
| `refresh` | bool | false | force refresh even if cached & fresh |
| `execution_mode` | enum | `"blocking"` | `blocking` \| `background` (ARCHITECTURE §5) |
| `mode` | enum | `"online"` | retrieval strategy: `online` \| `local` \| `semantic` (§8 of ARCHITECTURE.md) — unrelated to `execution_mode` |

### Response `200` — `execution_mode: "blocking"`

Every document is in a terminal state; there is never a `pending` entry.

```json
{
  "query": "FastAPI async best practices",
  "execution_mode": "blocking",
  "status": "complete",
  "cached": 3,
  "crawled": 2,
  "failed": 0,
  "documents": [
    {
      "id": "5c1f...",
      "url": "https://fastapi.tiangolo.com/async/",
      "normalized_url": "fastapi.tiangolo.com/async",
      "title": "Concurrency and async / await",
      "summary": "Short bounded summary, always present, <= 500 chars.",
      "markdown": "Full markdown, present if under size cap else null.",
      "markdown_truncated": false,
      "status": "cached",
      "source_type": "docs",
      "search_rank": 1,
      "semantic_score": null,
      "fetched_at": "2026-07-10T08:00:00Z",
      "expires_at": "2026-08-09T08:00:00Z",
      "error": null
    }
  ]
}
```

Top-level `status` is `"complete"` when every document has `status` in
`{cached, crawled}`, or `"complete_with_failures"` when one or more
documents permanently failed (`status: "failed"`, `error` populated with
the final failure reason). Both are terminal — the response is always the
full result set, never partial.

### Response `200` — `execution_mode: "background"`

Returns immediately after the cache lookup; anything not already cached
comes back as `pending` with a `job_id` instead of content.

```json
{
  "query": "FastAPI async best practices",
  "execution_mode": "background",
  "status": "partial",
  "cached": 3,
  "crawled": 0,
  "pending": 2,
  "failed": 0,
  "documents": [
    {
      "id": null,
      "url": "https://example.com/new-article",
      "normalized_url": "example.com/new-article",
      "title": null,
      "summary": null,
      "markdown": null,
      "status": "pending",
      "job_id": "job-uuid",
      "search_rank": 2
    }
  ]
}
```

Top-level `status` is `"complete"` only if nothing needed enqueuing
(everything was already cached), otherwise `"partial"`. Resolve `pending`
entries via `GET /v1/jobs/{id}` (§6) or by calling `/v1/research` again
later with the same `query`.

## 4. `POST /v1/crawl`

Direct crawl of a specific URL. Same cache-first, same SSRF guard as
research, but for a single known URL rather than a search.

### Request

```json
{ "url": "https://example.com/article", "refresh": false }
```

### Response `202` (queued) or `200` (already cached & fresh)

```json
{ "document_id": "5c1f...", "status": "cached", "job_id": null }
```

`400 CRAWL_BLOCKED` if the URL fails the guard in §7 of ARCHITECTURE.md.

## 5. Documents

### `GET /v1/documents`
Query params: `limit` (default 20, max 100), `cursor` (opaque, from
`next_cursor` in the previous response), `source_type`.

```json
{ "items": [ { "id": "...", "url": "...", "title": "...", "fetched_at": "..." } ], "next_cursor": "eyJ..." }
```

### `GET /v1/documents/{id}`
Full document including full `markdown` (no truncation on this route).
`404 NOT_FOUND` if missing.

### `GET /v1/documents/search`
Local full text search (§8.2). Query params: `q` (required), `limit`.
Response shape matches `/v1/research` document objects, `source_type`
always present, no `search_rank`/`semantic_score` unless `mode=semantic`.

### `POST /v1/documents/{id}/refresh`
Force a refresh job regardless of TTL. Returns `202` with `job_id`.

## 6. Jobs

### `GET /v1/jobs/{id}`

```json
{
  "id": "job-uuid",
  "type": "crawl",
  "status": "running",
  "attempts": 1,
  "max_attempts": 3,
  "created_at": "...",
  "updated_at": "...",
  "error": null,
  "document_id": null
}
```

`status`: `pending | running | completed | failed | dead_letter`.
When `completed`, `document_id` is populated.

### `GET /v1/jobs?status=dead_letter`
Operator-facing list of jobs that exhausted retries, for manual inspection.

## 7. Health

`GET /health` — liveness, no dependencies checked, always `200 {"ok": true}`.
`GET /ready` — checks DB connectivity, `200` or `503`.

## 8. Data Models

### `documents`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `url` | text | original, as first seen |
| `normalized_url` | text | **unique**, the cache key (§6.1 ARCHITECTURE.md) |
| `title` | text | nullable |
| `markdown` | text | full extracted content |
| `summary` | text | bounded, generated at store time |
| `source_type` | text | `docs \| github \| blog \| news \| other` |
| `metadata` | jsonb | extraction metadata (author, published_at, etc.) |
| `fetched_at` | timestamptz | |
| `expires_at` | timestamptz | derived from TTL policy §6.2 |
| `search_vector` | tsvector | generated column, indexed (GIN) |
| `created_at` / `updated_at` | timestamptz | |

### `document_chunks`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `document_id` | uuid FK → documents | cascade delete |
| `chunk_index` | int | order within document |
| `content` | text | chunk text |
| `embedding` | vector(N) | pgvector, N from `EMBEDDING_DIM` config; HNSW index |

### `crawl_jobs`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `type` | text | `crawl \| refresh` |
| `url` | text | target |
| `status` | text | `pending \| running \| completed \| failed \| dead_letter` |
| `attempts` | int | default 0 |
| `max_attempts` | int | default 3 |
| `next_attempt_at` | timestamptz | for backoff scheduling |
| `error` | text | nullable, last failure reason |
| `document_id` | uuid FK, nullable | set on completion |
| `created_at` / `updated_at` | timestamptz | |

### `api_keys` (settings)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `key_hash` | text | never store raw key |
| `label` | text | |
| `rate_limit_per_minute` | int | default from config |
| `created_at` | timestamptz | |

## 9. Configuration

All configuration is a single `Settings` object (pydantic-settings), loaded
from environment variables. No config is read anywhere else in the codebase.

| Env var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | required | postgres async DSN |
| `SEARCH_PROVIDER` | `"searxng"` | selects the `SearchProvider` adapter (ARCHITECTURE §10) — only value implemented initially, but the point is this is a config flip, not a code change, to add another |
| `SEARXNG_URL` | required | base URL of the vendored SearXNG service (ARCHITECTURE §13.2) |
| `CRAWL_PROVIDER` | `"crawl4ai"` | selects the `CrawlProvider` adapter (ARCHITECTURE §10) |
| `CRAWL4AI_URL` | required | base URL of the vendored Crawl4AI service (ARCHITECTURE §13.2) |
| `EMBEDDING_PROVIDER` | required | pluggable, see [INTEGRATIONS.md](INTEGRATIONS.md) |
| `EMBEDDING_DIM` | required | must match `document_chunks.embedding` column dim |
| `RESEARCH_EXECUTION_MODE_DEFAULT` | `"blocking"` | default for `/v1/research` when the request omits `execution_mode` |
| `CRAWL_MAX_RESPONSE_BYTES` | `5_000_000` | per-page cap |
| `CRAWL_FETCH_TIMEOUT_SECONDS` | `20` | per-page fetch timeout |
| `CRAWL_PER_DOMAIN_CONCURRENCY` | `2` | politeness limit |
| `JOB_MAX_ATTEMPTS` | `3` | before `dead_letter` |
| `WORKER_POLL_INTERVAL_SECONDS` | `1` | job claim poll interval |
| `TTL_DOCS_DAYS` / `TTL_GITHUB_DAYS` / `TTL_BLOG_DAYS` / `TTL_NEWS_HOURS` | `30 / 7 / 7 / 6` | §6.2 ARCHITECTURE.md |
