# Deployment Record — root@sean-EQ59

> This documents an actual live deployment: where it runs, how to reach it,
> what broke during setup and how it was fixed, and how to operate it going
> forward. For the design, see [ARCHITECTURE.md](ARCHITECTURE.md); for the
> command reference, see [BUILD.md](BUILD.md). For the *other* live
> deployment (no vless proxy, different host), see
> [DEPLOYMENT.md](DEPLOYMENT.md) — that one predates the `vless://` outbound
> proxy feature this deployment exercises.

## Where

| | |
|---|---|
| Host | hostname `sean-EQ59`, public IP `46.8.101.219`, x86_64, Ubuntu, kernel `7.0.0-27-generic` |
| SSH | `ssh -i ~/ssh/sean -p 11022 root@46.8.101.219` — **non-default port 11022**, key-based auth only. (Local shell alias on the operator's machine: `sshhk`, but that alias is missing `-p 11022` — use the explicit command above, not the alias, until it's fixed.) |
| Path | `/home/apps/deep-research-backend` |
| Deployed as | root, via `docker compose` |
| Shared host | Yes — runs several unrelated projects: `ai-polymarket-trading`, `pay3`, `frpc` (FRP client), `homecf` (cloudflared), three standalone `postgres:18` containers on ports 15430-15432. `PROJECT_PREFIX=deep-research-backend` keeps this deployment's containers/volumes distinctly named: `docker ps \| grep deep-research-backend`. |
| Exposed | Only `api`, on `0.0.0.0:10010` (`API_PORT=10010` in `.env`; container-internal port stays `8000`). `postgres`/`searxng`/`crawl4ai`/`xray` publish no host ports. Host firewall (`ufw`) allows `10000:11000/tcp`, which covers `10010`. |
| Docker | `29.6.1`, Compose `v5.3.1` |
| Network note | This host's default routes to Docker Hub / Debian / Alpine / PyPI / GitHub-releases are slow (a plain `apt install` of 2 packages took ~8 minutes before mirrors were applied) — see "cn build variant" below. This is *separate* from the vless proxy feature; the vless server this deployment tunnels through happens to run on this same box (see below), which is a coincidence of the operator's setup, not a requirement. |

## What's running

```
docker compose ps
```

| Service | Image | Notes |
|---|---|---|
| `deep-research-backend-postgres` | `pgvector/pgvector:pg16` (official) | migrations applied (`alembic upgrade head` → revision `0002`) |
| `deep-research-backend-searxng` | built from `docker/searxng/Dockerfile.cn` + `vendor/searxng` (submodule, commit `9f9c0081`) | JSON output enabled via `deploy/searxng/settings.yml` |
| `deep-research-backend-crawl4ai` | built from `docker/crawl4ai/Dockerfile.cn` + `vendor/crawl4ai` (submodule, commit `7e801521`) | **transparent egress-proxy wrapper** (redsocks + iptables) layered on top — see "vless outbound proxy" below. `NET_ADMIN` capability added for iptables. |
| `deep-research-backend-xray` | built from `docker/xray/Dockerfile` | opt-in via the `proxy` compose profile — parses `OUTBOUND_PROXY_URL` (a `vless://` link) and runs xray-core, exposing a plain SOCKS5 proxy at `xray:1080` on the internal compose network |
| `deep-research-backend-api` | built from `Dockerfile.cn` (repo root) | host port `10010` published |
| `deep-research-backend-worker-1` | same image as `api`, `python -m app.worker_main` | scale with `docker compose up -d --scale worker=N` |

All six have `restart: unless-stopped`.

**cn build variant**: every service above builds from its `*.cn` Dockerfile
sibling (`Dockerfile.cn`, `docker/searxng/Dockerfile.cn`,
`docker/crawl4ai/Dockerfile.cn`, `docker/xray/Dockerfile.cn`) via an
override file:
```bash
docker compose -f docker-compose.yml -f docker-compose.cn.yml --profile proxy <command>
```
These are pure package-mirror swaps (Aliyun for apt/apk, Tsinghua for PyPI, a
GitHub-releases accelerator for the xray-core binary) — same image contents,
just fast to build from this host. They do **not** replace
`docker-compose.yml`/the default Dockerfiles; both variants live side by
side. See each `*.cn` file's header comment.

## vless outbound proxy (the reason this deployment differs from DEPLOYMENT.md)

`.env` has:
```
OUTBOUND_PROXY_URL="vless://<uuid>@46.8.101.219:<port>?...&type=tcp#server-sean-hk"
COMPOSE_PROFILES=proxy
```
(the real value has a live credential — not reproduced here; it's only in
`.env` on the server, which is gitignored).

- Search providers (Reddit/GitHub/Truth Social, `SEARCH_PROVIDER=composite`
  only) and the `xray` service resolve this directly:
  `app/services/proxy/get_outbound_proxy_url()` turns `vless://...` into
  `socks5://xray:1080`, which their own `httpx` clients connect to directly.
- **Crawl4AI cannot use that path.** Its own vendored server hard-refuses
  `proxy_config` from any network request, for any value —
  `UNTRUSTED_FORBIDDEN_FIELDS` in `vendor/crawl4ai/crawl4ai/async_configs.py`,
  a deliberate SSRF/secret-exfiltration guard, not a bug. So its outbound
  traffic is instead redirected *transparently* at the OS network level
  inside its own container: `docker/crawl4ai/docker-entrypoint-proxy.sh`
  runs `redsocks` + `iptables` (root, before dropping to `appuser`) to route
  all outbound TCP through `xray:1080`. `app/services/proxy/
  get_crawl4ai_proxy_url()` always returns `None` — Crawl4AI is never told
  about a proxy at all.
- Verified live (see E2E results below): a direct TCP connection from
  inside these containers to an external site fails outright (connection
  refused); the same request through the proxy succeeds. Confirmed via the
  actual `/v1/crawl` → worker → Crawl4AI path, not just a raw socket test,
  with `cache_status: miss` on repeated distinct requests (i.e. genuinely
  live, not cached).
- **Known limitation**: `redsocks` only redirects TCP; DNS (UDP) resolution
  stays direct. Fine here (confirmed: DNS resolves fine, only the TCP
  connect itself was blocked) — would not help if DNS itself were censored.

## Setup performed

1. Code synced via `rsync` from the local checkout (submodules already
   populated locally — no git-remote-based clone used for this deploy).
2. `vendor/searxng/searx/version_frozen.py` generated locally
   (`python3 searx/version.py freeze`) before syncing — missing in a fresh
   submodule checkout, needed by `docker/searxng/Dockerfile*`'s `COPY` step
   (same gotcha as the other deployment, DEPLOYMENT.md item 2).
3. `.env` created from `.env.example`: real `SEARXNG_SECRET` /
   `CRAWL4AI_API_TOKEN` generated (`python3 -c "import secrets; print(secrets.token_hex(32))"`),
   `API_PORT=10010`, `OUTBOUND_PROXY_URL`/`COMPOSE_PROFILES=proxy` set as
   above.
4. `docker compose -f docker-compose.yml -f docker-compose.cn.yml --profile proxy build`,
   then `... up -d`.
5. `docker compose exec api alembic upgrade head`.
6. One API key seeded directly via `psql` before the admin API existed:
   ```sql
   INSERT INTO api_keys (id, key_hash, label, rate_limit_per_minute)
   VALUES (gen_random_uuid(), '<sha256 of the raw key>', 'deploy-test-key', 60);
   ```
   The raw key isn't in this repo; ask the operator if you need it. Any
   *new* key should go through the admin API instead (see below) —  this
   manual-insert path is only historical for this one key.
7. **Admin API added later** (migration `0003`, `app/api/routers/admin.py`):
   `ADMIN_API_SECRET` generated and appended to `.env`
   (`python3 -c "import secrets; print(secrets.token_hex(32))"`), then
   `docker compose exec api alembic upgrade head` (`0002` → `0003`, adds
   `api_keys.status`/`expires_at`), then `api`/`worker` rebuilt+redeployed
   to pick up the new router. See "Managing API keys" below.

## Bugs found and fixed by deploying for real

Everything below only surfaced by actually building/running the stack on
this specific host — each is fixed in code/build files, not worked around.

1. **This host's default apt/apk/PyPI/GitHub-releases endpoints are very
   slow** (a 2-package `apt install` took ~8 minutes). Fixed by adding the
   `*.cn` Dockerfile variants + `docker-compose.cn.yml` (see above) —
   ~15-100x faster per step after switching mirrors.
2. **Docker's multi-stage build silently clears an inherited `CMD` when a
   later stage sets a new `ENTRYPOINT` without also redeclaring `CMD`** — a
   documented but easy-to-miss quirk. `docker/crawl4ai/Dockerfile.cn`'s
   `proxy` stage re-declares `CMD ["bash", "entrypoint.sh"]` after its own
   `ENTRYPOINT` for exactly this reason.
3. **A `# syntax=docker/dockerfile:1.4` directive (needed for `RUN <<EOF`
   heredocs) switches which BuildKit frontend parses the file, which
   invalidated the entire prior build cache** for that Dockerfile — a full
   rebuild-from-scratch happened once, unavoidable, but worth knowing before
   assuming a rebuild "should be instant."
4. **Crawl4AI's own server refuses `proxy_config` from any network
   request, for any scheme** (not vless-specific — this had been broken
   since the `OUTBOUND_PROXY_URL` feature was first added, just never
   tested end-to-end until this deployment). Fixed with the transparent
   redsocks/iptables wrapper described above.
5. **Dropping root→`appuser` via `gosu` breaks reopening `/dev/stdout` by
   path** (`EACCES`) — a real Linux kernel restriction: a pipe's
   `/proc/$PID/fd` entry can only be reopened via path by the uid that
   originally owned it (root, since the container runtime sets up stdio
   before the entrypoint runs); `ls` shows it as `appuser`-owned, but only
   root can actually reopen it (see
   [moby/moby#31243](https://github.com/moby/moby/issues/31243)). This
   broke `supervisord`'s ability to spawn `redis`/`gunicorn` inside the
   crawl4ai container once it needed to run as root (for `iptables`) and
   drop privileges. Fixed: `docker/crawl4ai/supervisord.conf` (a build-time
   override, `vendor/crawl4ai`'s own file is untouched) points
   `stdout_logfile`/`stderr_logfile` at real files instead of
   `/dev/stdout`/`/dev/stderr`; `docker-entrypoint-proxy.sh` tails those
   files back to the container's actual stdout/stderr (started while still
   root) so `docker logs` keeps showing everything.
6. **`redsocks`'s `log = stdout;` config keyword doesn't exist** in the
   packaged version (`strings` on the binary shows only `stderr` and
   `syslog:` as valid destinations) — it failed silently on every startup
   until changed to `log = stderr;`.
7. **`pip install uv` (unpinned) installed a different uv version between
   two builds a few hours apart**, and the newer version rejected the
   committed `uv.lock` under `--locked` (lockfile-format drift, not a real
   dependency change). Fixed by regenerating `uv.lock` with the newer uv
   and re-committing it. This can recur — pinning the uv version in the
   Dockerfiles would prevent it permanently but hasn't been done yet (see
   Known Limitations).

## E2E test results (this deployment)

| Check | Result |
|---|---|
| `GET /docs` | `200` |
| `POST /v1/research`, `mode=online, execution_mode=blocking` | `200`, `status: complete` |
| `POST /v1/crawl`, real public URL, default (non-cn) proxy config | `202 queued` → worker completed, real markdown stored |
| Raw `httpx` direct connection to an external site from inside `api` container, no proxy | `[Errno 111] Connection refused` |
| Same request via `proxy='socks5://xray:1080'` | `200`, correct response body |
| `Crawl4AICrawlProvider.crawl()` called directly inside `api` container (before the `get_crawl4ai_proxy_url` fix) | `200 OK` from xray path confirmed separately, but Crawl4AI's own `/crawl` API returned `400 Bad Request` — the untrusted-gate rejection (bug 4 above) |
| Crawl4AI container manually curled with `proxy_config` forwarded | `400 Bad Request` (confirms bug 4 is scheme-independent, not vless-specific) |
| Crawl4AI container's own `/crawl`, target reachable only via proxy, after the redsocks fix | `200`, `success: true`, real page content |
| Same test repeated 3x with distinct URLs, then again after `docker compose restart crawl4ai` | All 6 runs: `success: true`, `cache_status: miss`, distinct response bodies each time — confirms live (not cached) and confirms the fix survives a cold container restart |
| Full app path: `POST /v1/crawl` → worker → Crawl4AI, post-restart | `202 queued` → `status: completed`, new `document_id` |
| All 6 containers | `Up`/`healthy` for 30+ minutes across multiple restarts during this session |
| `scripts/manage_api_keys.sh create`, then the printed raw key against `/v1/documents` | `201`, then `200` |
| `manage_api_keys.sh disable <id>`, same key against `/v1/documents` | `200` → then `401 {"message": "API key is disabled"}` |
| `manage_api_keys.sh enable <id>`, same key again | `401` → back to `200` |
| `manage_api_keys.sh create` with `expires_at` already in the past | Key created `200`, then immediately `401 {"message": "API key has expired"}` when used |
| `manage_api_keys.sh delete <id>`, then `show <id>` | `204` → `404` |
| `/admin/api-keys` with a wrong `Authorization` secret | `401 {"message": "invalid admin secret"}` |

## Managing API keys

```bash
cd /home/apps/deep-research-backend
bash scripts/manage_api_keys.sh list
bash scripts/manage_api_keys.sh create <label> [rate_limit_per_minute=60] [expires_at|never]
bash scripts/manage_api_keys.sh show <id>
bash scripts/manage_api_keys.sh disable <id>   # blocks auth without deleting
bash scripts/manage_api_keys.sh enable <id>
bash scripts/manage_api_keys.sh delete <id>    # permanent
```
Reads `ADMIN_API_SECRET`/`API_PORT` straight out of `.env` in the current
directory — run it from the deployment directory, or set `ENV_FILE=`. See
SPEC.md §10 for the underlying `/admin/api-keys` endpoints.

## Known limitations (as of this deployment)

- **No git-based redeploy path used** — code was `rsync`'d, matching the
  other deployment's approach, even though this repo does have a configured
  git remote now (unlike when DEPLOYMENT.md was written). A `git pull`-based
  redeploy would work here too if preferred; not set up.
- **uv version isn't pinned** in `Dockerfile`/`Dockerfile.cn` — bug 7 above
  can recur on a future rebuild if a new uv release changes lockfile
  handling again. Pinning (`pip install uv==<version>`) would close this.
- **`http://`/`socks5://` values for `OUTBOUND_PROXY_URL` still can't reach
  Crawl4AI** — only `vless://` gets the transparent-proxy treatment
  (`get_crawl4ai_proxy_url` always returns `None`, so a plain http/socks5
  proxy configured this way silently doesn't apply to Crawl4AI's own
  fetches either, same as vless). No trusted server-side config path exists
  for those schemes yet.
- **No admin endpoint for API keys** — same as the other deployment.
- Everything else in DEPLOYMENT.md's "Known limitations" (no rate
  limiting, redirect-hop SSRF revalidation gap) applies here unchanged too.

## Operating this deployment

**Redeploy a code change:**
```bash
rsync -az --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '.ruff_cache' --exclude '.git' --exclude '.env' \
  ./ -e "ssh -i ~/ssh/sean -p 11022" root@46.8.101.219:/home/apps/deep-research-backend/

ssh -i ~/ssh/sean -p 11022 root@46.8.101.219 \
  'cd /home/apps/deep-research-backend && \
   docker compose -f docker-compose.yml -f docker-compose.cn.yml --profile proxy build api worker && \
   docker compose -f docker-compose.yml -f docker-compose.cn.yml --profile proxy up -d api worker'
```
Rebuild `searxng`/`crawl4ai`/`xray` too only if their build files or the
vendored submodules changed.

**Apply a new migration:**
```bash
ssh -i ~/ssh/sean -p 11022 root@46.8.101.219 \
  'cd /home/apps/deep-research-backend && docker compose exec api alembic upgrade head'
```

**Check logs / health:**
```bash
ssh -i ~/ssh/sean -p 11022 root@46.8.101.219 \
  'cd /home/apps/deep-research-backend && docker compose ps'
ssh -i ~/ssh/sean -p 11022 root@46.8.101.219 \
  'cd /home/apps/deep-research-backend && docker compose logs <service> --tail 50'
```

**Scale workers:**
```bash
ssh -i ~/ssh/sean -p 11022 root@46.8.101.219 \
  'cd /home/apps/deep-research-backend && docker compose up -d --scale worker=3'
```

**Back up Postgres:**
```bash
ssh -i ~/ssh/sean -p 11022 root@46.8.101.219 \
  'cd /home/apps/deep-research-backend && docker compose exec postgres pg_dump -U postgres deep_research' > backup.sql
```
