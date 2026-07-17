# Next Session — Context Handoff

> Read this file first in any new session before touching code.

## Current Progress

MVP implementation (Step 4) is done, tested (41 unit/contract tests,
`uv run pytest`; `uv run ruff check .` clean), **and deployed live** to
`root@ssr:/home/apps/deep-research-backend` — see
[DEPLOYMENT.md](DEPLOYMENT.md) for the full record: what's running, every
bug the real deployment surfaced (and how each was fixed), and the E2E
test results (real SearXNG search + real Crawl4AI crawls, not mocks).
Semantic search is explicitly out of scope for this MVP — deferred until
an embedding provider is chosen (was going to use hosted API keys, per
user decision).

## Architecture Summary

Deep Research Backend = one API (`POST /v1/research`) that turns a keyword
into a complete, AI-analyzable result set by combining SearXNG search, a
PostgreSQL-backed document cache, and Crawl4AI crawling behind a
`CrawlProvider`/`SearchProvider` adapter layer. Two execution modes:
`blocking` (waits for every document to reach a terminal state, no
request-level timeout) and `background` (returns immediately with
`pending` + `job_id`). Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

## Completed Parts

- [x] Docs: `ARCHITECTURE.md`, `SPEC.md`, `BUILD.md`, `INTEGRATIONS.md`, `AGENT.md`, `DEPLOYMENT.md`
- [x] `app/config/` — `Settings` (pydantic-settings), matches SPEC §9 minus embedding config
- [x] `app/database/` — async engine/session
- [x] `app/models/` — `Document`, `CrawlJob`, `ApiKey` (no `document_chunks`/embeddings — deferred)
- [x] `migrations/versions/0001_initial.py` — applied to a real Postgres; generated tsvector column + GIN index confirmed working
- [x] `app/services/document/` — `normalize_url` (ARCHITECTURE §6.1), `classify_source_type` + `compute_expires_at` (§6.2)
- [x] `app/services/crawl/` — `url_guard.guard_url` (SSRF, §7), `CrawlProvider` protocol + `Crawl4AICrawlProvider` adapter (now sends `CRAWL4AI_API_TOKEN` as Bearer auth)
- [x] `app/services/search/` — `SearchProvider` protocol + `SearXNGSearchProvider` adapter, `local_fts.search_local`
- [x] `app/repositories/` — document/crawl_job/api_key repositories, `FOR UPDATE SKIP LOCKED` job claim, `get_active_by_url` job dedup
- [x] `app/services/worker/loop.py` + `app/worker_main.py` — claim → crawl → upsert → complete/fail(+backoff)/dead_letter; whole iteration now guarded against crashing the process
- [x] `app/services/research/research_service.py` — blocking/background orchestration (ARCHITECTURE §5), dedupes in-flight jobs per URL
- [x] `app/api/` — all routers (`research`, `crawl`, `documents`, `jobs`, `health`), auth dependency, error envelope + handlers (including `NOT_IMPLEMENTED` for semantic mode)
- [x] `main.py` — FastAPI app, request-id middleware, exception handlers, routers wired
- [x] `Dockerfile` (api/worker, same image), `docker-compose.yml` (5 services, all `restart: unless-stopped`)
- [x] `docker/searxng/Dockerfile` — merged multi-stage build (SearXNG's own build needs two cross-referencing Dockerfiles)
- [x] `deploy/searxng/settings.yml` — enables JSON output (upstream default disables it)
- [x] `vendor/searxng`, `vendor/crawl4ai` — real git submodules, pinned + `local-patches` branch
- [x] `tests/unit/` (normalize, ttl, url_guard, worker loop, research service, API wiring) + `tests/contract/` (SearXNG/Crawl4AI adapters, via `httpx.MockTransport` fixtures) — 41 total
- [x] **Live deployment** at `root@ssr:/home/apps/deep-research-backend`, E2E tested end to end (see DEPLOYMENT.md)

## Known Gaps (surfaced deliberately, not oversights)

- **SSRF redirect-hop revalidation is incomplete.** `guard_url` checks the
  initial URL before handing it to Crawl4AI, but Crawl4AI performs the
  actual fetch (including redirects) itself — we can't currently
  revalidate each hop. See the comment in `app/services/crawl/crawl4ai_provider.py`.
  Closing this needs either a Crawl4AI-side network policy/allowlist or
  fetching directly instead of delegating.
- **No rate limiting enforced.** `api_keys.rate_limit_per_minute` exists in
  the schema and SPEC.md documents `RATE_LIMITED`, but no limiter is
  wired up — auth (valid key required) works, quota enforcement doesn't.
  A real distributed limiter needs a shared store; doing this correctly
  without Redis (Postgres-counter-based) is real scope, not a quick add.
- **`markdown_truncated` threshold (200,000 bytes) is a hardcoded constant**
  in `research_service.py`, not a `Settings` field — promote it if a need
  to tune it shows up.
- **No admin endpoint for API keys** — the live deployment's one key was
  inserted directly via `psql`. Fine for one trusted caller; needs a real
  endpoint (or at least a seed script) before adding more.
- **No git remote for this repo** — the live deployment was `rsync`'d, not
  `git clone`d. See DEPLOYMENT.md's "Operating this deployment" for the
  current redeploy procedure; a git-based flow would be a real improvement.

## Next Actions

1. Decide on rate limiting approach (or explicitly punt further) before
   exposing the live deployment beyond trusted callers.
2. When ready to revisit embeddings/semantic search: pick a provider (API
   key based, per the user's decision this session), add
   `EMBEDDING_PROVIDER`/`EMBEDDING_DIM` back to `Settings`/SPEC.md, add a
   `document_chunks` table + migration, implement chunking + embedding in
   the worker pipeline, and implement `RetrievalMode.SEMANTIC` in
   `research_service.py` (currently raises `SemanticSearchNotImplementedError`,
   returns `501 NOT_IMPLEMENTED`).
3. Consider setting up a git remote so redeploys are `git pull` + rebuild
   instead of `rsync`.

## Risks / Unknowns

- **SearXNG hosting** — confirmed self-hosted and working on the live
  deployment; some upstream search engines (DuckDuckGo, Brave) intermittently
  CAPTCHA/rate-limit SearXNG itself, which SearXNG handles by skipping that
  engine for the request — seen in logs, not a bug, but means result count
  per query varies run to run.
- **Auth model** — single-tenant `api_keys` table with per-key rate limits
  (unenforced, see Known Gaps). Confirm this is sufficient before adding
  real multi-tenant isolation.
