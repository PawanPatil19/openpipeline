# Command line

```bash
openpipeline [COMMAND] [OPTIONS]
```

Run `openpipeline COMMAND --help` for the same information in your terminal.

Every command that reads a project takes an optional `PROJECT` argument: the
folder that holds `dbt_project.yml`. It defaults to the current folder, or to
`OPENPIPELINE_PROJECT_DIR` if that is set.

Exit codes: `0` on success, `1` when a model or column you named does not exist or
a preview fails, and `2` when the project cannot be loaded or an option has a bad
value.

Options for sample rows and the SQL dialect can also be set once in the `preview:`
section of [`openpipeline.yml`](configuration.md#openpipelineyml). A flag wins over an
environment variable, and an environment variable wins over the file.

## openpipeline demo

Try everything with no setup.

```bash
openpipeline demo [--dir PATH] [--host HOST] [--port PORT] [--serve | --no-serve]
                  [--token TEXT] [--read-only]
```

Copies the bundled jaffle_shop example, files one realistic pending proposal from
an imaginary agent (it adds a `revenue_by_month` model and touches two business
rules, with a rationale), then starts the server.

| Option | Default | What it does |
| --- | --- | --- |
| `--dir PATH` | a temporary folder | Copy the example here instead. The folder must be empty or not exist yet. |
| `--host` | `127.0.0.1` | Address to listen on. Also `OPENPIPELINE_HOST`. |
| `--port` | `8484` | Port to listen on. Also `OPENPIPELINE_PORT`. |
| `--no-serve` | off | Only prepare the folder and print its path. |
| `--token`, `--read-only` | | Same as for `serve`. On the default loopback address the demo is open. |

## openpipeline serve

Start the web UI and the HTTP API on one port.

```bash
openpipeline serve [PROJECT] [--host HOST] [--port PORT] [--reload]
                   [--sample-data PATH] [--dialect NAME]
                   [--token TEXT] [--read-only]
```

Reads are always open. Changes (saving descriptions, accepting proposals, comments,
AI calls) depend on the write mode, which is chosen like this:

1. `--read-only`: every write is refused with `403`.
2. `--token`: writes need `Authorization: Bearer <token>`.
3. No token, and `--host` is `127.0.0.1`, `::1`, or `localhost`: writes are open.
4. No token, and any other `--host`: a random token is generated, printed once with
   a link that opens the UI with it (`http://localhost:8484/?token=...`), and used.

See [Write access and security](security.md) for the details.

| Option | Default | What it does |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Address to listen on. Also `OPENPIPELINE_HOST`. Use `0.0.0.0` in a container; writes then need a token. |
| `--port` | `8484` | Port to listen on. Also `OPENPIPELINE_PORT`. |
| `--reload` | off | Restart on code changes. For developing OpenPipeline itself. |
| `--sample-data PATH` | `sample_data/` | Folder of sample CSV or Parquet files, or a `.duckdb` file, for [sample rows](../guides/sample-rows.md). Also `OPENPIPELINE_SAMPLE_DATA`. |
| `--dialect NAME` | none | SQL dialect of the project, such as `snowflake`. Also `OPENPIPELINE_DIALECT`. |
| `--token TEXT` | none | Require this Bearer token for writes. Also `OPENPIPELINE_TOKEN`. Never printed. |
| `--read-only` | off | Refuse every write. Also `OPENPIPELINE_READ_ONLY=1`. |

## openpipeline mcp

Run the [MCP server](../guides/ai-agents.md) for AI agents.

```bash
openpipeline mcp [PROJECT] [--transport stdio|streamable-http]
                 [--host HOST] [--port PORT] [--sample-data PATH] [--dialect NAME]
                 [--token TEXT]
```

`stdio` is a local process started by the agent, with no network port. The HTTP
transport needs a Bearer token unless it listens on a loopback address; with no
`--token` on another address, one is generated and printed.

| Option | Default | What it does |
| --- | --- | --- |
| `--transport` | `stdio` | `stdio` for local agents, `streamable-http` to run as a service. |
| `--host` | `127.0.0.1` | Address for the HTTP transport. Also `OPENPIPELINE_HOST`. |
| `--port` | `8485` | Port for the HTTP transport. Also `OPENPIPELINE_MCP_PORT`. |
| `--sample-data`, `--dialect` | | Same as for `serve`. |
| `--token TEXT` | none | Bearer token for the HTTP transport. Also `OPENPIPELINE_TOKEN`. |

## openpipeline explain

Explain one model in plain English.

```bash
openpipeline explain MODEL [PROJECT] [--json] [--ai]
```

| Option | What it does |
| --- | --- |
| `--json` | Print JSON instead of text. |
| `--ai` | Also ask Claude to explain it. Needs `openpipeline[ai]` and an API key. See [AI explanations](../guides/ai-explanations.md). |

## openpipeline graph

Print the model graph as JSON.

```bash
openpipeline graph [PROJECT]
```

The output has a `nodes` list and an `edges` list.

## openpipeline lineage

Show where a column comes from and where it is used. See
[Search and column lineage](../guides/search-and-lineage.md).

```bash
openpipeline lineage MODEL COLUMN [PROJECT] [--json]
```

Prints the columns it comes from and the columns that use it, nearest first. With
`--json` it prints the same data as the HTTP API. It exits with `1` if the model or
column does not exist.

## openpipeline sample

Show a few rows of a model, run on local sample data with DuckDB. Needs
`openpipeline[preview]`. See [Sample rows](../guides/sample-rows.md).

```bash
openpipeline sample MODEL [PROJECT] [--limit N] [--sample-data PATH] [--dialect NAME]
```

| Option | Default | What it does |
| --- | --- | --- |
| `--limit N` | `10` | Rows to show, from 1 to 200. |
| `--sample-data PATH` | `sample_data/` | Where the sample data is. |
| `--dialect NAME` | none | SQL dialect of the project. |

## openpipeline rules

List [business rules](../guides/business-rules.md), grouped by owner.

```bash
openpipeline rules [PROJECT] [--json]
```

Warnings about the rules file, such as a link to a model that does not exist, are
printed to standard error.

## openpipeline review

Summarise what changed between two versions of a project, as Markdown for a pull
request comment. See [PR summaries](../guides/pr-summaries.md).

```bash
openpipeline review BASE HEAD [-o FILE] [--ai]
```

| Option | What it does |
| --- | --- |
| `BASE` | The project before the change. |
| `HEAD` | The project after the change. |
| `-o`, `--output FILE` | Write to a file instead of printing. |
| `--ai` | Add an "In plain words" paragraph written by Claude. |

## openpipeline version

Print the installed version.
