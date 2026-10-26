# OpenPipeline

**From SELECT * to plain English.**

OpenPipeline turns every dbt model into a story anyone can read. Every change, from a teammate or an AI agent, goes to the data's owner before it lands.

Live demo: <https://openpipeline.vercel.app/demo/>

**Agents propose, owners approve.** AI agents are starting to write SQL. OpenPipeline
lets them, safely: an agent reads your project, checks its idea on sample rows, and
files a proposal. The owner sees it on the graph, in plain words and business terms,
and accepts or rejects it. Nothing touches your dbt files until a person says yes.

It opens a dbt project you already have. It never runs dbt, never connects to your
warehouse, and reads and writes plain dbt files, so you can stop using it at any time.

### How a change lands

1. **Propose.** A teammate opens a pull request, or an agent calls `propose_change`
   through the MCP server.
2. **Understand.** OpenPipeline shows what the change does in plain English (or in
   your own business words), which models and columns it touches downstream, and
   which business rules and owners are involved.
3. **Approve.** The owner accepts or rejects it, with comments. Only then is a file
   written.

![A model open in OpenPipeline: its plain-English story, columns, and rules next to the graph](docs/assets/story.png)

## Try it in one minute

```bash
pip install openpipeline
openpipeline demo
```

This copies the bundled jaffle_shop example to a temporary folder, files one
pending proposal from an imaginary agent, and starts the server at
<http://127.0.0.1:8484>. Open the **Proposals** tab and press **Show on graph** to
see a review.

## What you get

- **Model graph.** Every model and source as an interactive map. Click one to
  light up everything it reads from and everything that depends on it.
- **Story view.** Each model explained step by step in plain words: where the data
  comes from, how it is joined and filtered, what one row means, and how each
  column is worked out.
- **AI explanations (optional).** Bring your own Anthropic key to get a friendlier
  write-up and suggested descriptions. Nothing is sent unless you click the button.
- **Editable docs.** Fix descriptions in the UI. They are saved into your own YAML
  files and the comments in them are kept.
- **Sample rows.** Run a model on small local sample data in an in-memory DuckDB and
  see real rows. No warehouse involved.
- **Search and column lineage.** Press `/` to find any model, source, or column.
  Pick a column to see where it comes from and what uses it.
- **Business rules.** Name the rules buried in your SQL, give each an owner, and link
  them to the models and columns that carry them.
- **PR summaries.** A GitHub Action comments on pull requests with what changed in
  business terms, what is affected downstream, and which owners to loop in.
- **Safe changes from AI agents.** An MCP server lets agents such as Claude read
  the project and *propose* changes. You review each proposal on the graph, comment,
  and accept or reject it. Nothing is written until a person accepts.

<p>
  <img src="docs/assets/review.png" alt="A pending proposal shown on the graph, with the new model in green" width="49%">
  <img src="docs/assets/lineage.png" alt="Column lineage lighting up one column's path on the graph" width="49%">
</p>

## Use it on your own project

```bash
openpipeline serve path/to/your/dbt/project
# open http://127.0.0.1:8484
```

With Docker:

```bash
docker run --rm -p 8484:8484 -v "$PWD:/project" ghcr.io/pawanpatil19/openpipeline
docker logs <container>   # prints the write token and a link that opens with it
```

The container listens on all interfaces, so changes (editing docs, accepting
proposals, comments, AI calls) need a token. It makes one up and prints it, or use
`-e OPENPIPELINE_TOKEN=...`. Add `-e OPENPIPELINE_READ_ONLY=1` for a server that
refuses every write. See [Write access and security](docs/reference/security.md).

You do not need dbt installed or warehouse credentials. OpenPipeline reads
`target/manifest.json` when it exists (run `dbt compile` for the most accurate
results) and otherwise reads your SQL and YAML files directly.

Optional extras:

```bash
pip install 'openpipeline[ai]'        # AI explanations, with your own Anthropic key
pip install 'openpipeline[preview]'   # sample rows, run locally with DuckDB
```

## Connect an AI agent

```bash
claude mcp add openpipeline -- openpipeline mcp /path/to/dbt/project
```

The agent can look at everything, but it can only propose edits. It reads with
`explain`, `search`, `column_lineage`, `impact_of`, and `list_rules`, checks its work
with `preview_change` and `sample_rows`, and files changes with `propose_change`
or `propose_docs`, and suggests glossary terms with `propose_glossary_term`. See [Working with AI agents](https://openpipeline.vercel.app/docs/guides/ai-agents/).

## Command line

```bash
openpipeline demo                        # the example project plus a proposal to review
openpipeline serve [PROJECT]             # web UI and API on :8484 (--token, --read-only)
openpipeline explain customers [PROJECT] # explain one model (add --ai for an AI write-up)
openpipeline lineage customers lifetime_value [PROJECT]
openpipeline sample customers [PROJECT]  # a few rows, on sample data
openpipeline rules [PROJECT]             # business rules, grouped by owner
openpipeline review BASE HEAD            # Markdown summary of a change, for a PR
openpipeline mcp [PROJECT]               # MCP server for agents
```

`PROJECT` defaults to the current folder or `$OPENPIPELINE_PROJECT_DIR`. Run any
command with `--help` for its options.

## Documentation

Guides, the command line, HTTP API, and configuration reference are at
**<https://openpipeline.vercel.app/docs/>**.

## How it is built

| Part | Path | Stack |
| --- | --- | --- |
| Engine | [`packages/core`](packages/core) | Python, sqlglot, pydantic |
| App (CLI, API, MCP) | [`apps/server`](apps/server) | FastAPI, Typer, MCP Python SDK |
| Web UI | [`apps/web`](apps/web) | React, TypeScript, Vite, React Flow |
| PR summary action | [`actions/pr-summary`](actions/pr-summary) | GitHub composite action |
| Example project | [`examples/jaffle_shop`](examples/jaffle_shop) | dbt |

Read [docs/architecture.md](docs/architecture.md) for how the parts fit.

## Status

Early (0.x). The features above work and are covered by tests, including on real
public dbt projects, but names and options may still change before 1.0. Bug reports and
ideas are welcome in the [issue tracker](https://github.com/PawanPatil19/openpipeline/issues).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to set up the project and run the
checks. In short:

```bash
make install   # Python and web dependencies, plus git hooks
make dev       # API with reload on :8484, web dev server on :5173
make lint typecheck test
```

## License

[Apache 2.0](LICENSE)
