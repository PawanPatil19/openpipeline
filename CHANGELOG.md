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

### Security

- Writes to `openpipeline serve` are now protected. Saving descriptions
  (`PUT /api/models/{name}/docs`), accepting or rejecting proposals, comments, and
  AI explanations (which cost money) no longer work for anyone who can reach the
  port. The server picks a write mode at startup:
  - `open` on a loopback address with no token (today's local experience). In this
    mode `/api` requests must carry a loopback `Host` header, to stop DNS rebinding.
  - `token` when you pass `--token` or `OPENPIPELINE_TOKEN`, or listen on any other
    address. Without a token, one is generated, printed once with a link
    (`http://localhost:8484/?token=...`), and required as `Authorization: Bearer`.
    The Docker image, which listens on `0.0.0.0`, therefore always uses a token.
  - `off` with `--read-only` or `OPENPIPELINE_READ_ONLY=1`: every write answers `403`.
- Writes must be sent as `Content-Type: application/json` (`415` otherwise), including
  `POST /api/models/{name}/ai-explanation`. Scripts that posted it without a content
  type need to add the header.
- `GET /api/auth` reports the write mode and whether your token is valid. The web UI
  keeps the token from `?token=` for the tab only, removes it from the address bar,
  asks for it when a change is refused, and hides the edit, accept, comment, and AI
  buttons when the server is read-only.
- `openpipeline mcp --transport streamable-http` requires the same Bearer token on any
  non-loopback address. The stdio transport is local-only. Agents can still only
  propose changes.
- New page: [Write access and security](docs/reference/security.md). `docker compose`
  passes `OPENPIPELINE_TOKEN` and `OPENPIPELINE_READ_ONLY` to both services, and the
  CI image smoke test checks that an anonymous write is rejected.
- The Vite dev proxy now sets `changeOrigin`, so `make dev` keeps working with the
  `Host` check.

### Business words

- A **Business words** mode tells a story in the business's own words: a title and
  summary made of labels, columns as a label and what it means, and the SQL and
  technical names tucked behind **Show details**. It is a toggle in the story panel
  (remembered per browser), with definitions on hover and keyboard focus.
- A `glossary:` list in `openpipeline.yml` (`name`, `label`, optional `definition` and
  `aliases`), and `meta: {label, definition}` on dbt models and columns. Problems are
  warnings. Names without a term get a readable label (`stg_order_items` is "Order items",
  `is_food_order` is "Is food order"; Tuva-style `a__b` uses `b`).
- A Glossary tab in the web UI, `GET /api/glossary`, and
  `GET /api/models/{name}/business-story`.
- `openpipeline explain MODEL --business`.
- MCP: `propose_glossary_term` files a proposal that edits `openpipeline.yml` (a person
  still accepts it), `list_glossary` reads the glossary, and `explain` returns a
  `business` view.
- Core: `Glossary`, `load_glossary`, `humanize`, `add_glossary_term`, `Labeler` and
  `business_story`. `ModelStory` is unchanged.

### Website

- A landing page, the docs, and a read-only live demo of the web UI, hosted on Vercel
  at <https://openpipeline.vercel.app/>. It replaces the GitHub Pages docs site.
- `make site` builds it into `build/site` with `scripts/build_site.sh`.

## 0.1.0 - not yet released

The first public release. Everything under Unreleased above ships in it too.
This was prepared as 1.0.0 on 2026-10-24 but never published; it is labelled 0.1.0
because the project is still early and names may change before 1.0. OpenPipeline reads a dbt project and explains it in plain
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
