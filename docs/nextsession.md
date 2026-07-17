# Next Session — Context Handoff

> Read this file first in any new session before touching code.

## Current Progress

MVP implementation (Step 4) is done and unit/contract-tested (38 tests,
`uv run pytest`; `uv run ruff check .` clean). Semantic search is
explicitly out of scope for this MVP — deferred until an embedding
provider is chosen (was going to use hosted API keys, per user decision).
**Not yet verified**: nothing has been run against a live Postgres,
SearXNG, or Crawl4AI — see "Not Yet Verified" below before trusting this
in an actual deployment.

## Architecture Summary

Deep Research Backend = one API (`POST /v1/research`) that turns a keyword
into a complete, AI-analyzable result set by combining SearXNG search, a
PostgreSQL-backed document cache, and Crawl4AI crawling behind a
`CrawlProvider`/`SearchProvider` adapter layer. Two execution modes:
`blocking` (waits for every document to reach a terminal state, no
request-level timeout) and `background` (returns immediately with
`pending` + `job_id`). Full detail in [ARCHITECTURE.md](ARCHITECTURE.md).

## Completed Parts

- [x] Docs: `ARCHITECTURE.md`, `SPEC.md`, `BUILD.md`, `INTEGRATIONS.md`, `AGENT.md`
- [x] `app/config/` — `Settings` (pydantic-settings), matches SPEC §9 minus embedding config
- [x] `app/database/` — async engine/session
- [x] `app/models/` — `Document`, `CrawlJob`, `ApiKey` (no `document_chunks`/embeddings — deferred)
- [x] `migrations/versions/0001_initial.py` — hand-written (no live DB to autogenerate against), enables `pgvector` extension, creates all 3 tables
- [x] `app/services/document/` — `normalize_url` (ARCHITECTURE §6.1), `classify_source_type` + `compute_expires_at` (§6.2)
- [x] `app/services/crawl/` — `url_guard.guard_url` (SSRF, §7), `CrawlProvider` protocol + `Crawl4AICrawlProvider` adapter
- [x] `app/services/search/` — `SearchProvider` protocol + `SearXNGSearchProvider` adapter, `local_fts.search_local`
- [x] `app/repositories/` — document/crawl_job/api_key repositories, `FOR UPDATE SKIP LOCKED` job claim
- [x] `app/services/worker/loop.py` + `app/worker_main.py` — claim → crawl → upsert → complete/fail(+backoff)/dead_letter
- [x] `app/services/research/research_service.py` — blocking/background orchestration (ARCHITECTURE §5)
- [x] `app/api/` — all routers (`research`, `crawl`, `documents`, `jobs`, `health`), auth dependency, error envelope + handlers
- [x] `main.py` — FastAPI app, request-id middleware, exception handlers, routers wired
- [x] `Dockerfile` (api/worker, same image), `docker-compose.yml` (5 services)
- [x] `tests/unit/` (normalize, ttl, url_guard, worker loop, research service, API wiring) + `tests/contract/` (SearXNG/Crawl4AI adapters, via `httpx.MockTransport` fixtures)

## Not Yet Verified

No Docker daemon or live Postgres/SearXNG/Crawl4AI was available in the
implementation session — verify these before relying on this build:

1. **`docker compose config` parses cleanly** (checked) but **no image was
   actually built** — `docker build .` was not run against a live daemon.
   Build the `api` image and confirm the `uv sync --locked` steps succeed.
2. **The Alembic migration was never applied to a real Postgres.** Run
   `docker compose up -d postgres && alembic upgrade head` and confirm the
   generated tsvector `Computed(...)` column and GIN index actually create
   correctly — this is the one piece of the migration most likely to need
   a Postgres-version-specific tweak.
3. **`vendor/searxng` and `vendor/crawl4ai` are empty** — only a README
   with setup instructions in each. The `searxng`/`crawl4ai` services in
   `docker-compose.yml` will fail to build until the submodules are added
   (see each README). `api`, `worker`, and `postgres` don't depend on them
   to build/start.
4. **No integration test suite yet** — everything is unit/contract-level
   with mocked repositories/providers. `BUILD.md §5` describes the
   intended integration-test setup once the compose stack is real.

## Known Gaps (surfaced deliberately, not oversights)

- **SSRF redirect-hop revalidation is incomplete.** `guard_url` checks the
  initial URL before handing it to Crawl4AI, but Crawl4AI performs the
  actual fetch (including redirects) itself — we can't currently
  revalidate each hop. See the comment in `crawl4ai_provider.py` and
  `vendor/crawl4ai/README.md`. Closing this needs either a Crawl4AI-side
  network policy/allowlist or fetching directly instead of delegating.
- **No rate limiting enforced.** `api_keys.rate_limit_per_minute` exists in
  the schema and SPEC.md documents `RATE_LIMITED`, but no limiter is
  wired up — auth (valid key required) works, quota enforcement doesn't.
  A real distributed limiter needs a shared store; doing this correctly
  without Redis (Postgres-counter-based) is real scope, not a quick add.
- **`markdown_truncated` threshold (200,000 bytes) is a hardcoded constant**
  in `research_service.py`, not a `Settings` field — promote it if a need
  to tune it shows up.

## Next Actions

1. Get a real Postgres running (`docker compose up -d postgres`, or any
   local Postgres 16+ with `pgvector`) and run `alembic upgrade head` —
   this is the fastest way to catch anything wrong in the migration.
2. Populate `vendor/searxng` and `vendor/crawl4ai` (see their READMEs),
   build the full compose stack, and run one real `/v1/research` call
   end-to-end.
3. Decide on rate limiting approach (or explicitly punt further) before
   exposing this beyond trusted callers.
4. When ready to revisit embeddings/semantic search: pick a provider (API
   key based, per the user's decision this session), add
   `EMBEDDING_PROVIDER`/`EMBEDDING_DIM` back to `Settings`/SPEC.md, add a
   `document_chunks` table + migration, implement chunking + embedding in
   the worker pipeline, and implement `RetrievalMode.SEMANTIC` in
   `research_service.py` (currently raises `SemanticSearchNotImplementedError`).

## Risks / Unknowns

- **SearXNG hosting** — assumed self-hosted per ARCHITECTURE §3; confirm no
  public-instance rate-limit dependency is intended.
- **Auth model** — single-tenant `api_keys` table with per-key rate limits
  (unenforced, see Known Gaps). Confirm this is sufficient before adding
  real multi-tenant isolation.
