# AGENT.md

Operating instructions for any AI agent (or human) working in this
repository. Read this file first. It tells you what to read next, what
order to work in, and what not to do.

## 0. Core Philosophy

The goal is not the most elegant system. The goal is a system that an AI
can reliably understand, modify, and extend within a limited context
window, across many separate sessions with no shared memory between them.
Optimize for that, not for human aesthetic preference.

## 1. Where Things Live

| Need | File |
|---|---|
| Why the system is shaped this way, module boundaries, data flow | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Exact API contracts, data models, config, error format | [docs/SPEC.md](docs/SPEC.md) |
| How to run, migrate, test, deploy | [docs/BUILD.md](docs/BUILD.md) |
| Official docs URLs for every external dependency | [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) |
| What's done, what's next, open risks | [docs/nextsession.md](docs/nextsession.md) |
| Live deployment record — what's running where, bugs found by deploying, how to operate it | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |

**Always start a new session by reading `docs/nextsession.md`.** It is the
handoff between sessions and is the only file guaranteed to reflect current
state rather than original intent.

**Before writing any code that talks to an external project** (FastAPI,
SearXNG, Crawl4AI, PostgreSQL, pgvector, SQLAlchemy, Alembic, or any new
dependency), open its entry in `docs/INTEGRATIONS.md` and follow the docs
URL there. Do not rely on memorized API shapes for fast-moving projects —
verify against current docs. If a dependency isn't listed there yet, add it
before using it.

## 2. Execution Protocol (Strict)

Before starting any step below, state out loud which step you're on and
what you're about to produce. Follow the order — do not skip ahead.

1. **Architecture Design** (mandatory first, whenever the architecture is
   changing) — update `docs/ARCHITECTURE.md`. No implementation code in
   this step.
2. **Documentation** — update `docs/SPEC.md` / `docs/BUILD.md` to match.
   No implementation code in this step.
3. **Context Handoff** — update `docs/nextsession.md`: progress, completed
   parts, pending tasks (step-by-step), next actions, risks/unknowns.
4. **Implementation** — only after the user explicitly asks for code to be
   written. Never jump straight to code because a task "seems simple."

### Self-Correction Rule

If you notice premature coding, a module getting hard to explain in
isolation, or complexity creeping in — **stop and refactor before
continuing**, rather than pushing forward and hoping it resolves itself.

### Git Workflow

After each completed step above, commit with a `feat:` / `docs:` message
describing that step. **Never push** — pushing is a separate, explicit
decision the user makes, not something that happens automatically at the
end of a step.

## 3. Architecture Principles

These apply to every module added to this codebase:

1. **Cognitive-based decomposition** — split modules by whether an AI can
   understand one in isolation, not by line count or file size.
2. **Single responsibility** — one job per module, explicit input/output,
   no hidden dependencies.
3. **Local understandability** — a reader should not need to open five
   other files to understand this one. Avoid logic scattered across files
   and long cross-file dependency chains.
4. **Naming is documentation** — descriptive names, no abbreviations like
   `cfg`, `tmp`, `svc`. If the name needs a comment to explain it, rename it
   instead.
5. **Explicit behavior only** — no hidden side effects, no magic, no
   implicit state changes. If it happens, it should be visible in the code
   path that triggers it.
6. **Complexity control** — simple control flow, predictable logic, no deep
   nesting, no multi-purpose functions.
7. **Composition over inheritance** — inheritance hides behavior in a
   parent class the reader may not have open; composition keeps it visible.
8. **Clear entry points** — one main entry point (`main.py`), one
   configuration entry (`app/config/`), explicit module boundaries (see
   `docs/ARCHITECTURE.md` §14's data-flow rule: `api → services →
   repositories → models`, never the reverse).
9. **Explicit dependencies** — imports must be visible and traceable to
   their origin. No global hidden state, no implicit injection magic.
10. **Incremental buildability** — every step in `docs/nextsession.md`'s
    pending-tasks list must be independently testable before the next one
    starts.

## 4. AI-Specific Constraints

- **File-level understandability** — a file should make sense read alone.
- **No hidden context** — don't require the reader to hold multiple other
  files in memory to understand this one.
- **Controlled information density** — one abstraction layer per file, no
  overloaded functions doing three unrelated things.
- **Clear data flow** — it must be obvious where data comes from and where
  it goes, from reading the function signatures alone.
- **Predictable behavior** — same input, same output, minimal side effects.

## 5. Anti-Patterns (must avoid)

- Large, hard-to-understand modules ("god" files/utilities)
- Over-abstraction for hypothetical future requirements
- Deep inheritance chains
- Hidden or scattered configuration (config lives only in `app/config/`)
- Business logic leaking into `api/` routers or `repositories/`
- Silent fallbacks/mocks that mask a real failure (e.g. mocking the
  database in a test that's supposed to prove the pipeline works)

## 6. Configuration Strategy

Config is not optional in this project — one `Settings` object
(pydantic-settings) is the single source, documented in full in
[docs/SPEC.md §9](docs/SPEC.md#9-configuration). Nothing reads
`os.environ` directly outside `app/config/`.
