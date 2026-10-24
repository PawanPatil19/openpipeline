# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Read dbt projects from `target/manifest.json` or straight from files.
- Model graph with upstream and downstream impact.
- Plain-English story for each model, built from its SQL.
- `openpipeline review` and a GitHub Action for PR summaries.
- Web UI with the graph, story panel, and proposals review.
- MCP server so AI agents can read the project and propose changes.
- Business rules: name them in `openpipeline.yml`, link them from `meta.rules`,
  see them in the Rules tab and the model panel, and get them flagged in PR
  summaries. Adds `openpipeline rules`, `GET /api/rules`,
  `GET /api/models/{name}/rules`, and the `list_rules` MCP tool.
- Docker image, Compose file, CI, and release workflow.
- Edit a model's description and column descriptions in the UI. Saving writes to the
  model's YAML file and keeps its comments.
- Optional AI explanations (`pip install 'openpipeline[ai]'`): an "Explain with AI" button,
  `openpipeline explain --ai`, `openpipeline review --ai`, and `ai` and `anthropic-api-key`
  inputs on the PR summary action. Answers are cached in `.openpipeline/cache`.
- MCP tool `propose_docs` for agents to propose description changes.
- `PUT /api/models/{name}/docs`, `GET /api/ai`, and `POST /api/models/{name}/ai-explanation`.
- Review of agent proposals: a plain-English summary, readable diffs, and a
  "Show on graph" mode that colors new, changed, removed, and affected models.
- Comments on proposals, a reason when rejecting, and a "superseded" status when
  an agent revises a proposal.
- Accepting a proposal now stops with a clear message if files changed since it
  was made. "Accept anyway" overrides it.
- MCP tools `preview_change` (dry run) and `get_proposal`, and a `revises` option
  on `propose_change`, so agents can check their work and answer feedback.
