# OpenPipeline

**See what your dbt project does, in plain English. Review every change before it lands.**

OpenPipeline opens an existing dbt project and gives everyone, not just the
people who wrote the SQL, a way to understand and review it:

- **Model graph.** Every model and source as an interactive map. Click one to
  light up everything it reads from and everything that depends on it.
- **Story view.** Each model explained step by step in plain words: where the
  data comes from, how it is joined and filtered, what one row means, and how
  each column is worked out.
- **Search and column lineage.** Press `/` to find any model, source, or column
  by name or description. Pick a column to see which columns it is built from
  and which ones use it, and the graph lights up only that path.
- **PR summaries.** A GitHub Action that comments on pull requests with what
  changed in business terms, which other models are affected, and which owners
  to loop in.
- **Business rules.** Name the rules buried in your SQL, give each an owner,
  and link them to the models and columns that implement them. Pull request
  summaries flag every rule a change touches.
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
openpipeline explain customers --ai     # add an AI explanation (see below)
openpipeline graph [PROJECT]            # print the model graph as JSON
openpipeline rules [PROJECT]            # business rules, grouped by owner
openpipeline lineage customers lifetime_value [PROJECT]  # where a column comes from and where it is used
openpipeline review BASE HEAD           # Markdown summary of the change between two versions
openpipeline review BASE HEAD --ai      # same, with a plain-words overview at the top
openpipeline sample customers [PROJECT] # a few rows of a model, on sample data
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
`search`, `column_lineage`, `list_rules`, `sample_rows`, `preview_change`, `propose_change`,
`propose_docs`, `get_proposal`, and `list_proposals`. Agents should call `column_lineage`
before they rename or remove a column. It can look at everything, but it can only propose
edits. Nothing is written until you accept.

The review loop works like this:

1. The agent reads the project with `explain` and checks what depends on a model
   with `impact_of`.
2. It calls `preview_change` with the new file contents. This is a dry run that
   reports new warnings and the models that would be affected, so it can fix
   mistakes before you see them.
3. It calls `propose_change`. The proposal appears in the **Proposals** tab with a
   plain-English summary and a readable diff for each file.
4. Press **Show on graph** to see the result: new models in green, changed models
   in amber, removed models as red dashed ghosts, and models whose results may
   change with an outline. Click any box to read its story.
5. Accept, or reject with a reason. You can also leave comments. The agent reads
   them with `get_proposal`.
6. If you asked for changes, the agent calls `propose_change` again with
   `revises` set to the old proposal. The old one is marked superseded.

If someone edits a file after a proposal was made, accepting shows which files
changed. You can then choose **Accept anyway**.

`propose_docs` suggests a new description for a model or its columns.

## Edit descriptions

In the model panel, click **Edit description** or **Edit column descriptions**,
change the text, and click Save. OpenPipeline writes it to the model's YAML
file (for example `schema.yml`), keeping the comments and layout of the rest of
the file. If the model has no entry yet, one is added next to its SQL file.

## AI explanations (optional)

OpenPipeline works fully without AI. If you want a written explanation that
reads more like a person wrote it, you can turn one on with your own Anthropic
API key.

```bash
pip install 'openpipeline[ai]'
export ANTHROPIC_API_KEY=sk-ant-...
```

Then click **Explain with AI** in the model panel, or run
`openpipeline explain customers --ai`. The answer includes a short summary,
things worth double-checking, and a suggested description and column notes. The
buttons **Use as description** and **Use column notes** only fill in the
editors. Nothing is saved until you click Save.

`openpipeline review BASE HEAD --ai` adds an "In plain words" paragraph to the
top of the PR summary. If the AI call fails, the normal summary is still
printed.

The default model is `claude-opus-5-5`. Set `OPENPIPELINE_AI_MODEL` to use
another, or `OPENPIPELINE_AI=off` to switch AI off completely.

**Privacy.** The SQL and documentation of the model you ask about, and of the
models it reads from, are sent to Anthropic. This happens only when you click
the button or pass `--ai`. Nothing is sent otherwise.

Answers are cached in `.openpipeline/cache/ai` inside your project, so asking
again about an unchanged model costs nothing. Add `.openpipeline/` to your
`.gitignore`.

## Business rules

Write rules in `openpipeline.yml` at the root of your dbt project:

```yaml
rules:
  - id: lifetime-value
    name: Lifetime value is what a customer has paid
    description: The total a customer has paid us, in dollars, across all orders.
    owner: growth-team
    applies_to:
      - model: customers
        columns: [lifetime_value]
```

You can also link from dbt's own YAML with `meta: {rules: [lifetime-value]}` on
a model or a column. The **Rules** tab lists every rule, the model panel shows
the rules a model carries, and PR summaries list the rules a change touches and
the owners to loop in. See [docs/rules.md](docs/rules.md).

## Preview sample rows

Seeing a few rows is the fastest way to understand a model. OpenPipeline can run
a model's SQL on small sample data, on your own machine, in an in-memory
[DuckDB](https://duckdb.org). It never connects to your warehouse and never
writes to disk. The Docker image includes it. With pip, add the extra:

```bash
pip install 'openpipeline[preview]'
```

Open a model in the UI and expand **Sample rows**, or run
`openpipeline sample customers`. Agents can call the `sample_rows` tool.

Sample data comes from these places, in this order:

1. **Seeds.** Each CSV in your `seed-paths` becomes a table named after the file.
2. **A sample data folder.** By default this is `sample_data/` in your project.
   Use `--sample-data PATH` or `$OPENPIPELINE_SAMPLE_DATA` to point somewhere
   else. Name each file `<source>.<table>.csv` or `.parquet`. For example
   `raw.orders.csv` backs `source('raw', 'orders')`.
3. **A DuckDB file.** Pass a `.duckdb` file in the same way. It is opened
   read-only. Put each source's tables in a schema named after the source.

OpenPipeline builds every model upstream of the one you pick, then shows up to 20
rows (200 at most). If a table is missing, it tells you which one to add. Pass
`--dialect` or set `$OPENPIPELINE_DIALECT` (for example `snowflake`) so the SQL is
read in your warehouse's dialect. A preview that runs longer than five seconds is
stopped. Models that use macros, `var()` or other Jinja beyond `ref()` and
`source()` cannot be previewed, because OpenPipeline does not run dbt.

To set these once for everyone, add a `preview:` section to `openpipeline.yml`.
A flag wins over an environment variable, and an environment variable wins over
the file.

```yaml
preview:
  sample_data: sample_data   # a folder or a .duckdb file, relative to the project
  dialect: snowflake
```

The [jaffle_shop example](examples/jaffle_shop/sample_data) includes sample data
for all of its models.

## PR summaries on GitHub

See [actions/pr-summary](actions/pr-summary/README.md).

When a change removes or renames a column, the summary lists the columns in other
models that read it, for example "Removed column `amount` is used by
`customers.lifetime_value`". Proposal previews say the same.

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
