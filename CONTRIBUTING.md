# Contributing to OpenPipeline

Thanks for helping. This guide gets you from a fresh clone to a passing test
run.

## Set up

You need [uv](https://docs.astral.sh/uv/) (it installs Python for you), Node 22,
and pnpm 10 (`corepack enable` gives you the right version).

```bash
git clone https://github.com/PawanPatil19/openpipeline
cd openpipeline
make install
```

## Develop

```bash
make dev                          # API on :8484 and the UI on :5173, both reloading
make dev PROJECT=~/code/my-dbt    # against your own dbt project
```

Open http://localhost:5173. The Vite dev server forwards `/api` to the Python
server.

## Check your work

```bash
make lint        # ruff and biome
make typecheck   # mypy (strict) and tsc
make test        # pytest and vitest
make format      # fix formatting automatically
```

CI runs the same commands on every pull request, plus a Docker build and smoke
test. The git hooks installed by `make install` run the formatters on commit.

## Where things live

- `packages/core` is the engine. It must not depend on web or server
  libraries, so other tools (like the PR summary action) can use it alone.
- `apps/server` is everything that runs: CLI, HTTP API, MCP server.
- `apps/web` is the React UI. `pnpm build` writes it into
  `apps/server/src/openpipeline/static`, which ships inside the Python wheel.
- `examples/jaffle_shop` is the fixture for tests and the demo in the Docker
  image. If you add a feature, add whatever it needs to this project.

## Pull requests

- Keep each pull request to one change, and add tests for it.
- Write commit messages that say what changed and why.
- Update the docs and `CHANGELOG.md` when behaviour changes.

## Releasing

See [docs/releasing.md](docs/releasing.md).
