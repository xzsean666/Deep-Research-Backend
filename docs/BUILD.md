# Build & Usage

## 1. Prerequisites

- Docker + Docker Compose
- Python 3.12+ (only needed for running things outside containers, e.g. tests)

## 2. Local Stack

Fully self-hosted — every service in `docker-compose.yml` runs from this
stack, no managed/external dependencies:

| Service | Built from | Purpose |
|---|---|---|
| `api` | `Dockerfile` (this repo) | FastAPI app, `main.py` entrypoint |
| `worker` | `Dockerfile` (this repo), same image as `api` | job-claim loop, scale with `--scale worker=N` |
| `postgres` | official `pgvector/pgvector:pg16` image, pinned tag | primary datastore; ships with the `vector` extension built in — see [ARCHITECTURE.md §13.1](ARCHITECTURE.md#131-database-image--official-unmodified) for why this one stays an official image |
| `searxng` | `docker/searxng/Dockerfile` (merged multi-stage build, `vendor/searxng` submodule) | self-hosted metasearch — vendored, not pulled prebuilt, so it can be patched (§13.2) |
| `crawl4ai` | `vendor/crawl4ai`'s own root Dockerfile (submodule, pinned commit) | crawl/extraction service — vendored for the same reason |

Postgres is pinned by image tag. SearXNG and Crawl4AI are pinned by the
submodule commit their build is generated from. Neither moves without a
deliberate, reviewed change — see
[ARCHITECTURE.md §13.2](ARCHITECTURE.md#132-search--crawl-images--built-from-vendored-source-not-pulled-prebuilt).

Cloning this repo needs its submodules too:

```bash
git clone --recurse-submodules <repo-url>
# or, if already cloned:
git submodule update --init --recursive
```

Bring the stack up:

```bash
docker compose up -d
docker compose exec api alembic upgrade head
```

`postgres`, `searxng`, and `crawl4ai` do not publish ports to the host —
only `api` (port 8000) is reachable from outside the compose network,
since nothing else needs to be. To inspect one of the internal services
directly (e.g. `psql` during development), run it through the container
rather than adding a host port mapping to the shared compose file:

```bash
docker compose exec postgres psql -U postgres -d deep_research
```

## 3. Environment Variables

Copy `.env.example` to `.env` and fill in values. Full reference: see
[SPEC.md §9](SPEC.md#9-configuration). Never commit a real `.env`.

## 4. Database Migrations

```bash
# create a new migration after changing app/models/
docker compose exec api alembic revision --autogenerate -m "describe change"

# apply
docker compose exec api alembic upgrade head
```

The `pgvector` extension must exist before the first migration runs:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

This is included in the init migration, not left to manual setup.

## 5. Running Tests

```bash
pytest                     # unit tests, no external services required
pytest -m integration      # requires the docker compose stack running
```

Unit tests mock `services/search` and `services/crawl` at their client
boundary. Integration tests hit a real (test) PostgreSQL and a real
SearXNG/Crawl4AI — never mock the database itself; a passing mocked test
must not be read as proof the pipeline works end to end.

## 6. Calling the API

```bash
curl -X POST http://localhost:8000/v1/research \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "FastAPI async best practices", "limit": 5}'
```

## 7. Scaling in Production

- `api`: scale horizontally behind a load balancer; stateless.
- `worker`: scale horizontally; coordination is via PostgreSQL
  `FOR UPDATE SKIP LOCKED`, no additional config needed to add instances.
- `postgres`: the only component needing backup/HA planning. Vertical
  scaling first; read replicas only if `/v1/documents/search` read load
  becomes the bottleneck.

## 8. Observability Endpoints

- `GET /health` — liveness probe
- `GET /ready` — readiness probe (checks DB connection)

Point your orchestrator's liveness/readiness checks at these, not at
`/v1/research` (which has side effects and, in blocking mode, can run
long — see §9).

## 9. Long-Lived Request Timeouts

`/v1/research` with `execution_mode: "blocking"` (the default, see
[ARCHITECTURE.md §5.1](ARCHITECTURE.md#51-execution_mode-blocking-default))
waits for every document to reach a terminal state with **no
request-level cap**. Worst case is bounded only by the per-job retry
ceiling (`CRAWL_FETCH_TIMEOUT_SECONDS × JOB_MAX_ATTEMPTS` with backoff —
roughly 1–2 minutes with SPEC §9 defaults), not by seconds.

Anything sitting in front of the API must allow for this:

| Layer | What to set |
|---|---|
| Reverse proxy (nginx) | `proxy_read_timeout` well above the worst case, e.g. `180s` |
| Load balancer (ALB/ELB) | idle timeout raised to match, e.g. `180s` |
| HTTP client used by the calling agent | request timeout raised to match, or use `execution_mode: "background"` instead (§5.2) if the caller can't tolerate a long-lived connection |

If you cannot or do not want to raise infrastructure timeouts that high,
use `execution_mode: "background"` — it returns as soon as the cache
lookup finishes and never holds a connection open on a crawl.

## 10. Upgrading Self-Hosted Dependencies

Since this is a fully self-hosted stack, upgrading SearXNG, Crawl4AI, or
Postgres/pgvector is something you do yourself on your own schedule, not
something a managed provider pushes. The procedure differs by how each is
deployed (§13.1/§13.2 of ARCHITECTURE.md).

### 10.1 Postgres/pgvector (official image)

1. Check the [pgvector releases](https://github.com/pgvector/pgvector/releases)
   page for compatibility before bumping.
2. Bump the pinned tag in `docker-compose.yml` (e.g. `pgvector/pgvector:pg16`
   → `:pg17`), never move it to `latest`.
3. Major Postgres version bumps follow standard Postgres major-upgrade
   practice (dump/restore or `pg_upgrade`) — the pgvector extension
   version is tied to the image tag, so the extension upgrades with it.

### 10.2 SearXNG / Crawl4AI (vendored, built from source)

These are git submodules under `vendor/`, so "upgrade" means pulling
upstream forward without losing any local patch committed on the
`local-patches` branch:

1. Check that project's current docs/release notes — the URL for each is
   in [INTEGRATIONS.md](INTEGRATIONS.md). Read the changelog for breaking
   API/response-shape changes before pulling.
2. Inside the submodule (`vendor/searxng` or `vendor/crawl4ai`), fetch
   upstream and rebase the local `local-patches` branch onto the new
   pinned commit/tag:
   ```bash
   cd vendor/searxng
   git fetch upstream
   git rebase upstream/<new-tag-or-commit>
   ```
   Resolve any conflicts between the local patch and upstream's changes at
   this step — this is the only place a version bump can require actual
   code changes, and it's isolated to the vendored source itself.
3. Update the submodule pointer in the parent repo to the new commit, and
   rebuild the image: `docker compose build searxng` (or `crawl4ai`).
4. Run that dependency's contract test —
   `tests/contract/test_searxng_provider.py` or
   `tests/contract/test_crawl4ai_provider.py` (see
   [ARCHITECTURE.md §10](ARCHITECTURE.md#10-provider-abstraction--decoupling-from-searxng--crawl4ai))
   — before running the full suite. It's the fastest signal that the
   upgrade changed a response shape the adapter relies on.
5. If the contract test fails on a response-shape change (as opposed to a
   patch conflict already resolved in step 2), the fix is confined to that
   one adapter file (`searxng_provider.py` or `crawl4ai_provider.py`) —
   nothing in `research/`, `worker/`, the API layer, or the database
   schema should need to change for a version bump alone.
6. Run the full test suite, then redeploy.
