# External Integrations

Single source of truth for where to find the **current, official**
documentation of every external project this backend integrates with.

**Rule for AI agents implementing against these:** always open the docs URL
below before writing integration code against that dependency — do not rely
on training-data memory of its API, since these projects move fast. If a
URL below is dead or the project has moved, update this file in the same
change that fixes the integration code.

| Project | Role in this system | Docs URL | Notes |
|---|---|---|---|
| FastAPI | API framework | https://fastapi.tiangolo.com/ | async endpoints, pydantic v2 models |
| SearXNG | Online search backend | https://docs.searxng.org/ | self-hosted; JSON API format: https://docs.searxng.org/dev/search_api.html |
| Crawl4AI | Page crawl & markdown extraction | https://docs.crawl4ai.com/ | check extraction strategy config, respects robots.txt options |
| PostgreSQL | Primary datastore | https://www.postgresql.org/docs/current/ | pin the major version actually deployed |
| pgvector | Vector similarity extension | https://github.com/pgvector/pgvector | check HNSW vs IVFFlat index tradeoffs before changing index type |
| SQLAlchemy | ORM (async) | https://docs.sqlalchemy.org/en/latest/ | use the `asyncio` extension docs, not the sync ORM docs |
| Alembic | Schema migrations | https://alembic.sqlalchemy.org/en/latest/ | works with SQLAlchemy async engine via `run_sync` |
| Pydantic / pydantic-settings | Schemas & config | https://docs.pydantic.dev/latest/ | v2 API differs significantly from v1 |
| Embedding provider | Chunk embeddings for pgvector | *(fill in once §9 `EMBEDDING_PROVIDER` is decided, e.g. sentence-transformers: https://www.sbert.net/ or a hosted API)* | must document dimension to match `EMBEDDING_DIM` |

## When adding a new integration

1. Add a row to the table above with the official docs URL before writing
   any code against it.
2. Note the specific sub-page (e.g. an API reference or a config guide) if
   the top-level docs site is large — save future lookups.
3. If the integration requires credentials, document the required env var
   name here and the full value schema in [SPEC.md §9](SPEC.md#9-configuration)
   — never document actual secret values in this file.
