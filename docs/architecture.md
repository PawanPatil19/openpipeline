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

**`packages/core`** is a pure Python library with four dependencies
(pydantic, PyYAML, ruamel.yaml, sqlglot). It loads a project into `Node` objects, builds the
dependency graph, explains a model by reading its SQL structure, and diffs two
versions of a project. It knows nothing about HTTP, so the PR summary action
and any future tools can use it alone.

Stories and column lineage read SQL through one function, `sql_source.readable_sql`.
When the project came from a manifest and a model has dbt's `compiled_code`, that is
parsed (in the dialect of the manifest's adapter) and its physical table names, such
as `"dev"."main"."stg_orders"`, are mapped back to nodes through each node's
`relation_name` and rewritten to the short names (`stg_orders`, `ecom.raw_orders`).
Otherwise the raw file is used with `jinja.to_plain_sql`, which turns macro calls
into `__macro__name(args)` functions and keeps the first branch of each `if`. The
story (`story.py`) follows columns through CTEs, subqueries and `select *`, using
upstream columns from the column lineage when it is given, and describes each
expression with `describe.py`. Running `dbt compile` gives better stories.

Column lineage lives in the core too (`lineage.py`). For each model it points
every real table in the SQL at the node it refers to, lets sqlglot qualify the
query and trace each output column, and records which upstream
`(node, column)` pairs feed it. Models are read in dependency order, so a
`select *` can use the columns the upstream model was already found to
produce. Sources without documented columns learn their columns from the models
that read them. It never raises: SQL that cannot be read just has no known
upstream columns. `search.py` ranks nodes and columns by name, then description.

**`apps/server`** is the `openpipeline` package people install. It wraps the
core in a Typer CLI, a FastAPI app, and an MCP server. `ProjectState` caches the
loaded project, its graph, and its column lineage, and reloads them when any
SQL, YAML, CSV, or manifest file changes, so the UI and agents always see what
is on disk.

**Sample row previews** are split across both packages. Core has the parts that
need no database: `compile_sql` turns a model's SQL into plain SQL by replacing
`ref()` and `source()` with table names (and refuses other Jinja), and
`plan_preview` lists the upstream models in build order with the sources and
seeds they need. The server's `sample.py` holds the engine. It opens an
in-memory DuckDB, loads seeds and the files in `sample_data/` as tables, creates
a view for each upstream model after transpiling its SQL to DuckDB with sqlglot,
and selects a few rows from the target. External file access is switched off
before any model SQL runs, and a timer interrupts slow queries. DuckDB is an
optional extra (`openpipeline[preview]`), so core never imports it.

**`apps/web`** is a React single-page app. It talks only to `/api`. In
production it is built into the Python package and served by FastAPI, so there
is one process and one port. In development Vite serves it with hot reload and
forwards `/api` to the Python server.

**Docs write-back and AI** are two small additions. `openpipeline_core.docs`
turns a new description into the full new content of one YAML file (it never
writes), using ruamel.yaml so comments survive. `openpipeline.files` is the one
place that writes project files and refuses paths outside the project, in
`.git`, or in `.openpipeline`. A person saving in the UI writes through it
directly; the MCP `propose_docs` tool puts the same edit in a proposal instead.
`openpipeline.ai` is optional. It builds a prompt from the model's SQL, the
deterministic story, and its direct parents' docs, calls Claude with structured
output, and caches the answer under `.openpipeline/cache/ai` keyed by a hash of
everything sent. Without the `ai` extra or a key, the API reports AI as
unavailable and everything else is unchanged.

**Business words** are a second telling of the same story. `glossary.py` reads
the `glossary:` list in `openpipeline.yml` and `meta.label` from dbt's YAML into a
`Glossary` (with warnings, never errors), falls back to a humanizer for names it
does not list, and can return the new `openpipeline.yml` with a term added (again
through ruamel.yaml, never writing). `business.py` takes a finished `ModelStory`
and puts labels in by recognising identifier tokens, skipping quoted values, so the
story engine is unchanged. The MCP `propose_glossary_term` tool files the edit as
a proposal.

**`actions/pr-summary`** is a composite GitHub Action that checks out the base
branch, runs `openpipeline review base head`, and posts or updates a single PR
comment.

## Why these choices

| Choice | Why |
| --- | --- |
| **Python for the engine** | dbt, its manifest, and the best SQL parser (sqlglot, with 30+ dialects and column-level lineage) all live in Python. Users already have Python wherever they have dbt. |
| **Read files directly when there is no manifest** | Lets anyone open a repo with no dbt install, profile, or warehouse credentials. The manifest path is used when present because dbt has already resolved macros and configs. |
| **Deterministic stories first** | Built from the SQL structure, so they are instant, free, private, and testable. The optional AI explanation is layered on top, is sent the deterministic story as a starting point, and never replaces it. |
| **AI only on request** | Nothing leaves your machine unless a person clicks the button or passes `--ai`. AI output only fills editors; a person still saves. |
| **FastAPI + Typer** | Typed, fast, well known, and pydantic models flow straight from the core to JSON. |
| **Official MCP Python SDK** | Same process and same core as the API, so agents and people see identical data. |
| **Proposals as JSON files** | No database to run. Proposals are easy to inspect, commit, or delete by hand, and the review step cannot be skipped. |
| **React + React Flow + dagre** | React Flow is the standard for interactive node graphs and will also carry the future editing canvas. dagre gives a readable left-to-right layout. |
| **uv workspace + pnpm workspace** | One lockfile per language, fast installs, and each package can be released on its own. |
| **One Docker image, one port** | The UI ships inside the Python wheel, so `pip install` and `docker run` give the same product. |
| **ruff, mypy strict, biome, vitest** | Fast tools with little config, enforced the same way in pre-commit and CI. |

## Data flow for a proposal

1. An agent calls `preview_change` with full new file contents. The core's
   `preview_changes` copies the project to a temporary folder (skipping `.git`,
   `target`, and similar), applies the files there, loads both versions from
   their files, and returns a `ChangePreview`: file diffs, a status for every
   node (added, modified, removed, affected downstream), the merged graph with
   removed nodes kept as ghosts, new load warnings, and SQL that fails to parse.
   Nothing is saved. The copy costs time and disk that grow with project size,
   but it is exact and needs no dbt install.
2. The agent calls `propose_change`. `ProposalStore` checks every path stays
   inside the project and away from `.git` and `.openpipeline`, records a
   SHA-256 fingerprint of each file as it is now, and saves the proposal as
   pending. If it sets `revises`, the earlier pending proposal becomes
   `superseded`.
3. The UI lists it under **Proposals**. It calls `GET /api/proposals/{id}/preview`
   to show a summary and diffs, and **Show on graph** draws the after-graph with
   color-coded nodes. The preview always runs against the files on disk now, so
   for an accepted proposal it is stale and shows little.
4. A person comments, accepts, or rejects with an optional reason (saved as a
   comment). Accepting first compares each file with its saved fingerprint. If
   any changed, the API answers 409 with the list of files, and the UI offers
   **Accept anyway**, which resends with `force: true`.
5. Accepting writes the files. `ProjectState` notices them and the graph updates.
6. The agent polls `get_proposal` for the status and comments, and answers
   feedback with a new proposal that has `revises` set.

## What comes next

- A visual editing canvas that writes plain dbt SQL.
- Authentication for shared deployments.

## Data flow for saving docs

1. A person edits a description in the model panel and clicks Save.
2. `PUT /api/models/{name}/docs` asks `update_docs` for the new YAML file.
3. `write_file` checks the path and writes it. `ProjectState` notices the change
   and the graph and story refresh.

Agents use `propose_docs` instead, which files the same YAML as a proposal.
