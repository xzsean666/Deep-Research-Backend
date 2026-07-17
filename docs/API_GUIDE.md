# API Integration Guide

> For callers integrating against this API (an AI Agent, a script, another
> service) — practical usage, not the formal contract. For the exact
> request/response schema of every field, see [SPEC.md](SPEC.md). For how
> the pipeline works internally, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Base URL

```
http://<your-server-host>:<API_PORT>
```

`<API_PORT>` is whatever `API_PORT` is set to in that deployment's `.env`
(default `8000` if unset — see `docs/BUILD.md`). This guide's examples use
`http://localhost:8000` for a local/dev stack; substitute your actual
host and port for a remote deployment (see `docs/DEPLOYMENT.md` for the
specifics of any deployment you're pointed at).

## Authentication

By default, every route except `/health` and `/ready` requires:

```
Authorization: Bearer <your-api-key>
```

There's no self-service key issuance yet (`docs/nextsession.md` "Known
Gaps") — get a key from whoever operates the deployment. A missing or
invalid key returns:

```json
{"error": {"code": "UNAUTHORIZED", "message": "invalid API key", "request_id": "..."}}
```

This can be turned off entirely per deployment (`REQUIRE_API_KEY=false` in
`.env` — SPEC.md §9) for one that's already network-isolated to trusted
callers. **Disabling it removes the only access control this API has** —
it's meant for a deployment firewalled to a VPN/internal network, not one
reachable from the open internet.

**The `root@ssr` deployment has `REQUIRE_API_KEY=false`** — no
`Authorization` header is needed there at all, which is why the examples
below omit it. A previously-seeded key still exists and would work if
auth gets re-enabled there later:

```
sE4CkRSdz1tVYXyh2F_4lISmh4ts8Fk8Cb_ohuaq7ZE
```
(label `e2e-test-key`, seeded during E2E testing — see `docs/DEPLOYMENT.md`.
Real, live credential, committed here only because it's test-only on a
private server with no git remote — rotate it before this repo ever gets
pushed anywhere.)

## The one call you actually need: keyword search

The examples below omit the `Authorization` header, matching the
`root@ssr` deployment (`REQUIRE_API_KEY=false`). If you're calling a
deployment with the default `REQUIRE_API_KEY=true`, add
`-H "Authorization: Bearer $API_KEY"` to every request.

```bash
curl -X POST http://localhost:8000/v1/research \
  -H "Content-Type: application/json" \
  -d '{"query": "python asyncio tutorial", "limit": 3}'
```

This is the whole point of the API: one keyword in, a complete set of
analyzable documents out. Behind the scenes it searches, checks what's
already cached, crawls whatever's missing, and merges everything into one
response — you never call search and crawl separately. Real response,
first call against a cold cache (~11s, since 3 pages had to be crawled):

```json
{
  "query": "python asyncio tutorial",
  "execution_mode": "blocking",
  "status": "complete",
  "cached": 0,
  "crawled": 3,
  "pending": 0,
  "failed": 0,
  "documents": [
    {
      "id": "2306bab8-62b2-4288-8e14-312518fa1d89",
      "url": "https://realpython.com/async-io-python/",
      "normalized_url": "https://realpython.com/async-io-python",
      "title": "Python's asyncio: A Hands-On Walkthrough – Real Python",
      "summary": "...",
      "markdown": "...",
      "markdown_truncated": false,
      "status": "crawled",
      "source_type": "blog",
      "search_rank": 1,
      "fetched_at": "2026-07-17T03:57:26Z",
      "expires_at": "2026-07-24T03:57:26Z"
    }
  ]
}
```

Ask the same question again and it's a cache hit — same request, ~0.4s,
`"cached": 3, "crawled": 0`, every document's `status` becomes `"cached"`.
You don't need to do anything differently to get this; it's automatic
based on `normalized_url` + TTL.

**Reading the response, as a caller:**
- `status: "complete"` — every document resolved, safe to use immediately.
- `status: "complete_with_failures"` — most documents are good; check
  each `documents[i].status` and skip the ones marked `"failed"` (they
  carry an `error` field explaining why — e.g. a bot-blocked page after 3
  retries).
- `markdown` is `null` with `markdown_truncated: true` for very large
  pages — fetch the full text via `GET /v1/documents/{id}` if you need it.
- `summary` is always present and short — use it for quick relevance
  triage across many documents before reading full `markdown`.

## Choosing `execution_mode`

| | `blocking` (default) | `background` |
|---|---|---|
| When to use | You want the answer now and can wait a bit | You're firing off several research calls and will collect results later |
| Response time | Until every document resolves — could be over a minute worst case if a page is slow/blocked (SPEC.md §9 defaults: up to ~1–2 min) | Near-instant — just the search + cache lookup |
| `pending` documents in response | Never | Yes, each with a `job_id` |
| How to get the rest | N/A — response is already final | Poll `GET /v1/jobs/{job_id}`, or just call `/v1/research` again with the same `query` later |

Confirmed live: calling `/v1/research` again for a query with a
still-in-flight document reuses the same `job_id` rather than starting a
redundant crawl — polling is safe and cheap.

```bash
curl -X POST http://localhost:8000/v1/research \
  -H "Content-Type: application/json" \
  -d '{"query": "rust ownership borrowing", "limit": 2, "execution_mode": "background"}'
# -> {"status": "partial", "pending": 2, "documents": [{"status": "pending", "job_id": "...", ...}, ...]}
```

If a client can't tolerate a long-held HTTP connection (some proxies/load
balancers time out well under a minute), use `background` instead of
raising timeouts everywhere — see `docs/BUILD.md §9`.

## Other endpoints

**Direct crawl of a known URL** (skips search):
```bash
curl -X POST http://localhost:8000/v1/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/some-page"}'
# -> 200 {"status": "cached", ...} if already have it, or 202 {"status": "queued", "job_id": "..."}
```
URLs resolving to private/internal addresses (SSRF guard) are rejected
immediately with `400 CRAWL_BLOCKED` — confirmed against a cloud metadata
address (`169.254.169.254`) during testing, never reaches the crawler.

**Already-cached content, no network calls:**
```bash
GET /v1/documents?limit=20&cursor=<opaque>          # browse everything crawled so far
GET /v1/documents/{id}                              # one document, full (untruncated) markdown
GET /v1/documents/search?q=asyncio&limit=5          # full-text search over cached documents
```

**Job status** (for `background` mode, or general debugging):
```bash
GET /v1/jobs/{job_id}
GET /v1/jobs?status=dead_letter        # jobs that exhausted retries — inspect what's failing
```

**Not yet implemented:** `mode: "semantic"` on `/v1/research` returns a
clean `501 NOT_IMPLEMENTED` — semantic/embedding-based search is deferred,
see `docs/nextsession.md`. Use the default `mode: "online"` (keyword
search) or `mode: "local"` (full-text search over what's already cached).

## Errors

Every error is the same envelope:
```json
{"error": {"code": "SOME_CODE", "message": "human-readable reason", "request_id": "..."}}
```
Codes you'll actually see as a caller: `UNAUTHORIZED` (bad/missing key),
`INVALID_REQUEST` (bad params), `NOT_FOUND` (unknown document/job id),
`CRAWL_BLOCKED` (SSRF guard rejected a URL), `NOT_IMPLEMENTED`
(`mode: "semantic"`), `UPSTREAM_UNAVAILABLE` (SearXNG/Crawl4AI down),
`INTERNAL_ERROR`. Full list: [SPEC.md §2](SPEC.md#2-error-format).

## Not enforced yet

`api_keys.rate_limit_per_minute` exists but nothing checks it — don't
build a client that depends on being rate-limited gracefully instead of
just being a good citizen (reasonable request volume, cache-friendly
repeated queries). See `docs/nextsession.md` Known Gaps.
