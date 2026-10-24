# OpenPipeline

**See what your dbt project does, in plain English. Review every change before it lands.**

OpenPipeline opens an existing dbt project and gives everyone, not just the
people who wrote the SQL, a way to understand and review it:

- **Model graph.** Every model and source as an interactive map. Click one to
  light up everything it reads from and everything that depends on it.
- **Story view.** Each model explained step by step in plain words: where the
  data comes from, how it is joined and filtered, what one row means, and how
  each column is worked out.
- **PR summaries.** A GitHub Action that comments on pull requests with what
  changed in business terms, which other models are affected, and which owners
  to loop in.
- **MCP server for AI agents.** Agents such as Claude can read the project and
  *propose* changes. Proposals show up in the UI, and nothing is written to your
  dbt files until a person accepts them.

Your dbt project stays the source of truth. OpenPipeline reads plain dbt files
and writes plain dbt files, so you can stop using it at any time.

> **Status:** early alpha. The foundation is in place; expect rough edges.

## Quick start

With [uv](https://docs.astral.sh/uv/) or pip:

```bash
pip install openpipeline
openpipeline serve path/to/your/dbt/project
# open http://127.0.0.1:8484
```

With Docker:

```bash
docker run --rm -p 8484:8484 -v "$PWD:/project" ghcr.io/pawanpatil19/openpipeline
```

Or run the UI and the MCP server together:

```bash
DBT_PROJECT_DIR=~/code/my-dbt-project docker compose up
```

You do **not** need dbt installed or warehouse credentials. OpenPipeline reads
`target/manifest.json` when it exists (run `dbt parse` for the most accurate
results) and otherwise reads your SQL and YAML files directly.

## Command line

```bash
openpipeline serve [PROJECT]            # web UI and API on :8484
openpipeline explain customers [PROJECT] # explain one model in the terminal
openpipeline graph [PROJECT]            # print the model graph as JSON
openpipeline review BASE HEAD           # Markdown summary of the change between two versions
openpipeline mcp [PROJECT]              # MCP server over stdio for local agents
openpipeline mcp --transport streamable-http   # MCP over HTTP on :8485
```

`PROJECT` defaults to the current directory or `$OPENPIPELINE_PROJECT_DIR`.

## Connect an AI agent

Add OpenPipeline to your agent's MCP config. For Claude Code:

```bash
claude mcp add openpipeline -- openpipeline mcp /path/to/dbt/project
```

The agent gets these tools: `list_models`, `get_model`, `explain`, `impact_of`,
`propose_change`, and `list_proposals`. It can look at everything, but it can
only propose edits. You accept or reject them in the **Proposals** tab.

## PR summaries on GitHub

See [actions/pr-summary](actions/pr-summary/README.md).

## How it is built

| Part | Path | Stack |
| --- | --- | --- |
| Engine | [`packages/core`](packages/core) | Python, sqlglot, pydantic |
| App (CLI, API, MCP) | [`apps/server`](apps/server) | FastAPI, Typer, MCP Python SDK |
| Web UI | [`apps/web`](apps/web) | React, TypeScript, Vite, React Flow |
| PR summary action | [`actions/pr-summary`](actions/pr-summary) | GitHub composite action |
| Example project | [`examples/jaffle_shop`](examples/jaffle_shop) | dbt |

Read [docs/architecture.md](docs/architecture.md) for how the parts fit and why
each choice was made.

## Contributing

Contributions are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) explains how to
set up the project and run the checks. In short:

```bash
make install   # Python and web dependencies, plus git hooks
make dev       # API with reload on :8484, web dev server on :5173
make lint typecheck test
```

## License

[Apache 2.0](LICENSE)
