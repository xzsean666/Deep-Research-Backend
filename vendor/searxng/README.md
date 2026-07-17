# Vendored SearXNG

Not yet populated. This directory is meant to hold SearXNG as a git
submodule, pinned to a specific upstream commit, on a local branch for any
patches this project needs — see
[ARCHITECTURE.md §13.2](../../docs/ARCHITECTURE.md#132-search--crawl-images--built-from-vendored-source-not-pulled-prebuilt).

## Setup

```bash
git submodule add https://github.com/searxng/searxng vendor/searxng
cd vendor/searxng
git checkout -b local-patches <pinned-tag-or-commit>
cd ../..
git add .gitmodules vendor/searxng
git commit -m "chore: vendor searxng at <pinned-tag-or-commit>"
```

`docker-compose.yml`'s `searxng` service builds directly from this
directory using SearXNG's own Dockerfile — no wrapper Dockerfile in this
repo to keep in sync with upstream's.

## Upgrading

See [BUILD.md §10.2](../../docs/BUILD.md#102-searxng--crawl4ai-vendored-built-from-source).
