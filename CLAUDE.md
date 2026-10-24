# OpenPipeline

Explain-and-review layer for dbt projects. See README.md and docs/architecture.md.

## Layout

- `packages/core` — `openpipeline_core`: loader, graph, story, diff. No web deps; keep it that way.
- `apps/server` — `openpipeline`: Typer CLI, FastAPI API (`api.py`), MCP server (`mcp_server.py`), proposals.
- `apps/web` — React + Vite + React Flow. Builds into `apps/server/src/openpipeline/static` (gitignored).
- `actions/pr-summary` — composite GitHub Action that runs `openpipeline review`.
- `examples/jaffle_shop` — fixture for all tests and the Docker demo.

## Commands

- `make install`, `make dev`, `make lint typecheck test`, `make build`, `make docker`.
- Python: `uv run pytest`, `uv run ruff check .`, `uv run mypy` (strict).
- Web: `pnpm lint` (biome), `pnpm typecheck`, `pnpm test` (vitest).

## Rules

- Agents only propose changes; never add a code path that writes dbt files without a person accepting.
- API types in `apps/web/src/lib/api.ts` mirror the pydantic models; update both together.
- Versions are bumped with `scripts/bump_version.py`, never by hand.
- sqlglot 30 renamed `from`/`with` args to `from_`/`with_`; use `story._arg`.
