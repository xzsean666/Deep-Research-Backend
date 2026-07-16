# Next Session — Context Handoff

> Read this file first in any new session before touching code.

## Current Progress

Repository is freshly initialized, zero commits before this session.
Steps 1–3 of the protocol in [AGENT.md](../AGENT.md) are complete:
architecture design, specification docs, and this handoff file. **No
implementation code exists yet.** Step 4 (implementation) has not been
authorized.

## Architecture Summary

Deep Research Backend = one API (`POST /v1/research`) that turns a keyword
into a complete, AI-analyzable result set by transparently combining
SearXNG search, a PostgreSQL-backed document cache, bounded-time Crawl4AI
crawling, and pgvector semantic search. Single infrastructure dependency:
PostgreSQL (queue, FTS, vector, metadata all in one place). Full detail in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Completed Parts

- [x] `docs/ARCHITECTURE.md` — system design, data flow, module boundaries
- [x] `docs/SPEC.md` — API contracts, data models, config reference
- [x] `docs/BUILD.md` — build/run/deploy instructions
- [x] `docs/INTEGRATIONS.md` — external project docs registry
- [x] `AGENT.md` — AI operating instructions for this repo
- [ ] Any code under `app/`
- [ ] `docker-compose.yml`
- [ ] `migrations/`

## Pending Tasks (Step 4, only on explicit request)

Implement in this order — each step should be independently testable
before moving to the next, per the Incremental Buildability principle:

1. **Config** — `app/config/` (`Settings` from pydantic-settings, per SPEC §9)
2. **Database bootstrap** — `app/database/`, initial Alembic migration
   creating `documents`, `document_chunks`, `crawl_jobs`, `api_keys` +
   `CREATE EXTENSION vector`
3. **Models** — `app/models/` (SQLAlchemy ORM matching SPEC §8)
4. **Repositories** — `app/repositories/` (CRUD + the normalized-URL lookup
   query + the `FOR UPDATE SKIP LOCKED` job-claim query)
5. **URL normalization utility** — `app/services/document/normalize.py`
   (ARCHITECTURE §6.1) — pure function, easiest to unit test first
6. **URL guard (SSRF)** — `app/services/crawl/url_guard.py`
   (ARCHITECTURE §7) — pure function, unit test with known private ranges
7. **Search service** — SearXNG client + local FTS + semantic search
8. **Crawl service** — Crawl4AI client wired through the URL guard
9. **Worker** — job claim loop, retry/backoff, dead-letter transition
10. **Research service** — orchestrates §5 of ARCHITECTURE.md (the wait
    budget logic is the trickiest part — needs its own focused test)
11. **API routers** — thin FastAPI routes per SPEC.md, wired to services
12. **docker-compose.yml** + `.env.example`
13. **Tests**: unit tests alongside each of the above; integration tests
    last, once the compose stack exists

## Next Actions

1. User reviews `docs/ARCHITECTURE.md` and `docs/SPEC.md` and either
   approves or requests changes.
2. Once approved, user explicitly requests Step 4 to begin — start at item
   1 above, one commit per completed item (`feat: <item>`), no push.

## Risks / Unknowns

- **Embedding provider not chosen.** `EMBEDDING_PROVIDER` / `EMBEDDING_DIM`
  in SPEC §9 are placeholders. Needs a decision (local model vs hosted API)
  before item 3 above, since `document_chunks.embedding` dimension is fixed
  at migration time and is not free to change later.
- **SearXNG hosting** — assumed self-hosted per ARCHITECTURE §3; confirm no
  public-instance rate-limit dependency is intended.
- **Auth model** — SPEC §8 assumes a single-tenant `api_keys` table with
  per-key rate limits. Confirm this is sufficient (vs. full multi-tenant
  isolation) before implementing item 11.
- **Crawl4AI deployment mode** — as a library import inside the worker
  process, or as a separate service reached over HTTP (as ARCHITECTURE §4
  diagrams it)? Confirm before item 8; changes the worker's dependency
  footprint.
