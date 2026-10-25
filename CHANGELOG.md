# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## Unreleased

### Stories

- Stories and column lineage use dbt's compiled SQL from the manifest when it is
  there (run `dbt compile`). `Node` has `compiled_sql` and `relation_name`, and
  `Project` has `adapter`.
- Columns are followed through CTEs and `select *`, so every story lists the real
  columns with how each was worked out and the step (`from_step`) it came from.
- Expressions are described in plain English (`case`, `coalesce`, casts, arithmetic,
  aggregates, window functions, dates, strings) instead of shown as SQL.
- Plain-file reading is better: macro calls are shown by name instead of `NULL`, and
  only the first branch of an `if` is read, so far fewer models fail to parse.
- `group by 1` is shown as the column it means.

### Website

- A landing page, the docs, and a read-only live demo of the web UI, hosted on Vercel
  at <https://openpipeline.vercel.app/>. It replaces the GitHub Pages docs site.
- `make site` builds it into `build/site` with `scripts/build_site.sh`.

## 1.0.0 - 2026-10-24

The first stable release. OpenPipeline reads a dbt project and explains it in plain
English, with a graph, stories, column lineage, search, sample rows, and business
rules. It lets people review changes before they land, whether a teammate or an AI
agent proposed them: a pull request summary on GitHub, and an MCP server whose
proposals a person accepts or rejects in the UI. It still never runs dbt and never
connects to a warehouse. A docs site, a one-command demo, and a Docker image come
with it.

### Explain

- Read dbt projects from `target/manifest.json` or straight from files.
- Model graph with upstream and downstream impact.
- Plain-English story for each model, built from its SQL.
- Search across models, sources, seeds, and columns: `GET /api/search`, the
  `search` MCP tool, and a search box in the web UI (press `/` or Ctrl/Cmd+K).
- Column-level lineage built with sqlglot: `GET /api/models/{name}/columns`,
  `GET /api/models/{name}/columns/{column}/lineage`, the `column_lineage` MCP
  tool, `openpipeline lineage MODEL COLUMN`, and a column lineage section in the
  model panel that fits the column's whole path on the graph.
- Business rules: name them in `openpipeline.yml`, link them from `meta.rules`,
  see them in the Rules tab and the model panel, and get them flagged in PR
  summaries. Adds `openpipeline rules`, `GET /api/rules`,
  `GET /api/models/{name}/rules`, and the `list_rules` MCP tool.
- Edit a model's description and column descriptions in the UI. Saving writes to the
  model's YAML file and keeps its comments (`PUT /api/models/{name}/docs`).
- Optional AI explanations (`pip install 'openpipeline[ai]'`): an "Explain with AI"
  button, `openpipeline explain --ai`, `GET /api/ai`, and
  `POST /api/models/{name}/ai-explanation`. Answers are cached in
  `.openpipeline/cache`.

### Review

- Review of agent proposals: a plain-English summary, readable diffs, and a
  "Show on graph" mode that colors new, changed, removed, and affected models.
- Comments on proposals, a reason when rejecting, and a "superseded" status when
  an agent revises a proposal.
- Accepting a proposal stops with a clear message if files changed since it was
  made. "Accept anyway" overrides it.
- PR summaries and proposal previews say which downstream columns read a column
  that was removed or renamed, such as "Removed column `amount` is used by
  `customers.lifetime_value`".
- `openpipeline review` and a GitHub Action for PR summaries. The action takes
  optional `ai` and `anthropic-api-key` inputs, and `openpipeline review --ai`
  adds an "In plain words" paragraph.

### Agents

- MCP server so AI agents can read the project and propose changes. Agents can
  only propose; a person accepts.
- MCP tools `preview_change` (dry run), `get_proposal`, `propose_docs`, and a
  `revises` option on `propose_change`, so agents can check their work and answer
  feedback.

### Preview

- Preview sample rows of a model with an in-memory DuckDB, from seeds, a
  `sample_data/` folder, or a `.duckdb` file. Available in the UI, as
  `openpipeline sample`, and as the `sample_rows` MCP tool. Install with
  `openpipeline[preview]`; the Docker image includes it. The sample data folder
  and SQL dialect can also be set in a `preview:` section of `openpipeline.yml`.

### Docs and tooling

- `openpipeline demo`: the example project plus a proposal waiting for review, in
  one command.
- Docs site built with MkDocs and published to GitHub Pages, with guides, a
  command line, HTTP API, and configuration reference, and screenshots made by
  `scripts/screenshots.mjs`.
- A shorter README that leads with what OpenPipeline is and how to try it.
- Docker image (with the sample rows and AI extras), Compose file, CI, and a release workflow that publishes to PyPI
  and GHCR.
- Fixed: `openpipeline explain --help` no longer drops `openpipeline[ai]` from
  the `--ai` description.
- Fixed: picking a column in the Column lineage section now brings the whole
  lit-up path into view instead of zooming in on one model.
