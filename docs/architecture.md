# Architecture

OpenPipeline is an "explain and review" layer that sits beside an existing dbt
project. It reads the project, never runs it, and writes back only plain dbt
files that a person has approved.

```
             ┌─────────────────────────── apps/server (openpipeline) ──────────────────────────┐
 dbt project │                                                                                 │
 (files or   │   ProjectState ──► packages/core (openpipeline-core)                            │
  manifest)  │   (reloads on       load_project · ModelGraph · explain_model · diff_projects     │
     ▲       │    file change)          ▲               ▲                  ▲                    │
     │       │                          │               │                  │                    │
     │       │                    FastAPI /api     MCP server         CLI: explain, graph,      │
     │       │                    + static UI      (stdio / HTTP)          review, serve, mcp   │
     │       │                          ▲               ▲                                       │
     │       │                          │               │                                       │
     │       │                  ProposalStore ◄─────────┘  agents can only *propose*            │
     └───────┼── accepted proposals ────┘  (.openpipeline/proposals/*.json)                     │
             └─────────────────────────────────────────────────────────────────────────────────┘
                     ▲                                              ▲
             apps/web (React UI)                         AI agents (Claude, etc.)
```

## The parts

**`packages/core`** is a pure Python library with three dependencies
(pydantic, PyYAML, sqlglot). It loads a project into `Node` objects, builds the
dependency graph, explains a model by reading its SQL structure, and diffs two
versions of a project. It knows nothing about HTTP, so the PR summary action
and any future tools can use it alone.

**`apps/server`** is the `openpipeline` package people install. It wraps the
core in a Typer CLI, a FastAPI app, and an MCP server. `ProjectState` caches the
loaded project and reloads it when any SQL, YAML, CSV, or manifest file
changes, so the UI and agents always see what is on disk.

**`apps/web`** is a React single-page app. It talks only to `/api`. In
production it is built into the Python package and served by FastAPI, so there
is one process and one port. In development Vite serves it with hot reload and
forwards `/api` to the Python server.

**`actions/pr-summary`** is a composite GitHub Action that checks out the base
branch, runs `openpipeline review base head`, and posts or updates a single PR
comment.

## Why these choices

| Choice | Why |
| --- | --- |
| **Python for the engine** | dbt, its manifest, and the best SQL parser (sqlglot, with 30+ dialects and column-level lineage) all live in Python. Users already have Python wherever they have dbt. |
| **Read files directly when there is no manifest** | Lets anyone open a repo with no dbt install, profile, or warehouse credentials. The manifest path is used when present because dbt has already resolved macros and configs. |
| **Deterministic stories first** | Built from the SQL structure, so they are instant, free, private, and testable. An optional LLM rewrite can be layered on top without changing the API. |
| **FastAPI + Typer** | Typed, fast, well known, and pydantic models flow straight from the core to JSON. |
| **Official MCP Python SDK** | Same process and same core as the API, so agents and people see identical data. |
| **Proposals as JSON files** | No database to run. Proposals are easy to inspect, commit, or delete by hand, and the review step cannot be skipped. |
| **React + React Flow + dagre** | React Flow is the standard for interactive node graphs and will also carry the future editing canvas. dagre gives a readable left-to-right layout. |
| **uv workspace + pnpm workspace** | One lockfile per language, fast installs, and each package can be released on its own. |
| **One Docker image, one port** | The UI ships inside the Python wheel, so `pip install` and `docker run` give the same product. |
| **ruff, mypy strict, biome, vitest** | Fast tools with little config, enforced the same way in pre-commit and CI. |

## Data flow for a proposal

1. An agent calls `propose_change` with full new file contents.
2. `ProposalStore` checks every path stays inside the project and away from
   `.git` and `.openpipeline`, then saves the proposal as pending.
3. The UI lists it under **Proposals** with the file contents.
4. A person accepts (files are written) or rejects it. `ProjectState` notices
   the new files and the graph updates.

## What comes next

- Column-level lineage using sqlglot's lineage module.
- Optional LLM-written stories and PR summaries, with the deterministic story
  as the fallback.
- Showing a proposal's effect on the graph before accepting it.
- A visual editing canvas that writes plain dbt SQL.
- Authentication for shared deployments.
