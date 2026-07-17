# Vendored Crawl4AI

Not yet populated. This directory is meant to hold Crawl4AI as a git
submodule, pinned to a specific upstream commit, on a local branch for any
patches this project needs — see
[ARCHITECTURE.md §13.2](../../docs/ARCHITECTURE.md#132-search--crawl-images--built-from-vendored-source-not-pulled-prebuilt).

## Setup

```bash
git submodule add https://github.com/unclecode/crawl4ai vendor/crawl4ai
cd vendor/crawl4ai
git checkout -b local-patches <pinned-tag-or-commit>
cd ../..
git add .gitmodules vendor/crawl4ai
git commit -m "chore: vendor crawl4ai at <pinned-tag-or-commit>"
```

`docker-compose.yml`'s `crawl4ai` service builds directly from this
directory using Crawl4AI's own Dockerfile — no wrapper Dockerfile in this
repo to keep in sync with upstream's.

## Upgrading

See [BUILD.md §10.2](../../docs/BUILD.md#102-searxng--crawl4ai-vendored-built-from-source).

## Known gap

The `CrawlProvider` adapter (`app/services/crawl/crawl4ai_provider.py`)
guards the initial URL before submitting it (ARCHITECTURE.md §7) but
cannot currently re-validate redirects Crawl4AI follows internally. If
Crawl4AI exposes a network allow/deny-list or a redirect-hook config,
wiring it here would close that gap — check current docs
(docs/INTEGRATIONS.md) before assuming it's unavailable.
