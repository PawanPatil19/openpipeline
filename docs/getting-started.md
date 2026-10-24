# Getting started

You need Python 3.11 or newer, or Docker. You do **not** need dbt installed or
any warehouse credentials.

## Try the demo first

```bash
pip install openpipeline
openpipeline demo
```

Open <http://127.0.0.1:8484>. The demo uses a copy of the jaffle_shop example, so
it never touches your files. It already has an agent proposal waiting in the
**Proposals** tab. See [the demo](reference/cli.md#openpipeline-demo) for options.

## Install

=== "pip"

    ```bash
    pip install openpipeline
    openpipeline serve path/to/your/dbt/project
    ```

    Optional extras:

    ```bash
    pip install 'openpipeline[ai]'        # AI explanations (your own Anthropic key)
    pip install 'openpipeline[preview]'   # sample rows, run locally with DuckDB
    ```

    [uv](https://docs.astral.sh/uv/) works too: `uvx openpipeline serve path/to/project`.

=== "Docker"

    ```bash
    docker run --rm -p 8484:8484 -v "$PWD:/project" ghcr.io/pawanpatil19/openpipeline
    ```

    Run this from your dbt project folder. The image already includes the AI and
    sample rows extras.

=== "Docker Compose"

    Runs the web UI and the MCP server together:

    ```bash
    DBT_PROJECT_DIR=~/code/my-dbt-project docker compose up
    ```

    The UI is on <http://localhost:8484> and the MCP server on
    `http://localhost:8485/mcp`. Without `DBT_PROJECT_DIR` it uses the bundled
    example.

## Point it at your dbt project

Give OpenPipeline the folder that holds `dbt_project.yml`:

```bash
openpipeline serve ~/code/my-dbt-project
```

If you leave the path out, it uses the current folder, or the folder in the
`OPENPIPELINE_PROJECT_DIR` environment variable.

The page reloads its data on its own when you edit a SQL, YAML, or CSV file, so
you can keep your editor open next to it.

## Manifest or files

OpenPipeline can read your project two ways. The top bar of the UI says which
one it used ("read from manifest" or "read from files").

| | `target/manifest.json` | Plain files |
| --- | --- | --- |
| When it is used | Whenever `target/manifest.json` exists | When there is no manifest |
| Jinja and macros | Already resolved by dbt | Only `ref()`, `source()`, and `config()` are understood |
| Setup needed | Run `dbt parse` (no warehouse needed) | None |
| Best for | Projects that use macros, packages, or `var()` | A quick look, or a repo without dbt installed |

If your project uses macros, run `dbt parse` first and OpenPipeline will pick up
the manifest on its own. Re-run it when the project changes, because the
manifest is a snapshot.

## What next

- [Read the graph and stories](guides/graph-and-stories.md)
- [Name your business rules](guides/business-rules.md)
- [Add PR summaries to GitHub](guides/pr-summaries.md)
- [Connect an AI agent](guides/ai-agents.md)
