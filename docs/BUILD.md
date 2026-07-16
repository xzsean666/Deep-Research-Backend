# Build & Usage

## 1. Prerequisites

- Docker + Docker Compose
- Python 3.12+ (only needed for running things outside containers, e.g. tests)

## 2. Local Stack

`docker-compose.yml` (to be created in Step 4) defines five services:

| Service | Purpose |
|---|---|
| `api` | FastAPI app, `main.py` entrypoint |
| `worker` | job-claim loop, scale with `--scale worker=N` |
| `postgres` | with `pgvector` extension enabled on init |
| `searxng` | self-hosted metasearch |
| `crawl4ai` | crawl/extraction service |

Bring the stack up:

```bash
docker compose up -d
docker compose exec api alembic upgrade head
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
