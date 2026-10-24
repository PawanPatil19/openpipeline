# Configuration

OpenPipeline has very little to configure. Everything has a sensible default, and
your dbt project stays the source of truth.

## Environment variables

| Variable | Default | What it does |
| --- | --- | --- |
| `OPENPIPELINE_PROJECT_DIR` | the current folder | Which dbt project to open when you do not pass a path. The Docker image sets it to `/project`. |
| `OPENPIPELINE_HOST` | `127.0.0.1` | Address the web UI and the MCP HTTP transport listen on. The Docker image sets `0.0.0.0`. |
| `OPENPIPELINE_PORT` | `8484` | Port of the web UI and API. |
| `OPENPIPELINE_MCP_PORT` | `8485` | Port of the MCP server with `--transport streamable-http`. |
| `OPENPIPELINE_SAMPLE_DATA` | `sample_data/` in the project | Folder of sample files, or a `.duckdb` file, for [sample rows](../guides/sample-rows.md). |
| `OPENPIPELINE_DIALECT` | none | SQL dialect of the project, for sample rows. For example `snowflake`. |
| `OPENPIPELINE_AI` | on, if a key is present | Set to `off`, `0`, or `false` to switch [AI explanations](../guides/ai-explanations.md) off completely. |
| `OPENPIPELINE_AI_MODEL` | `claude-opus-5-5` | Which Anthropic model to use for AI explanations. |
| `ANTHROPIC_API_KEY` | none | Your Anthropic key. `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_PROFILE` also work, and so does a profile in `~/.config/anthropic` made with `ant auth login`. |

Command line options win over environment variables, and environment variables
win over `openpipeline.yml`.

## openpipeline.yml

The `openpipeline.yml` file sits next to `dbt_project.yml`. It has two optional
sections: `rules:` for your [business rules](../guides/business-rules.md) and
`preview:` for [sample rows](../guides/sample-rows.md).

```yaml
preview:
  sample_data: sample_data   # a folder or a .duckdb file, relative to the project
  dialect: snowflake

rules:
  - id: shipped-revenue
    name: Revenue counts once an order is shipped
    description: >
      An order only counts as revenue after it has shipped.
    owner: finance-team
    tags: [finance, orders]
    applies_to:
      - model: orders
      - model: daily_revenue
        columns: [revenue]
```

| Key | What it does |
| --- | --- |
| `rules` | A list of business rules. The fields are explained on the [rules file format](../rules.md) page. |
| `preview.sample_data` | Where sample data lives, relative to the project folder. Same as `--sample-data`, but set once for everyone. |
| `preview.dialect` | SQL dialect of the project. Same as `--dialect`. |

Other keys in `preview:` are ignored, and so is a `preview:` section that is not a
mapping. The file is optional.

## Files OpenPipeline reads and writes

| Path | Read | Written |
| --- | --- | --- |
| `dbt_project.yml`, `models/**`, `seeds/**` | yes | only YAML description edits you save, or proposals you accept |
| `target/manifest.json` | yes, when it exists | never |
| `openpipeline.yml` | yes | only when you accept a proposal that changes it |
| `sample_data/` | yes | never |
| `.openpipeline/proposals/` | yes | when an agent files a proposal, or you comment, accept, or reject |
| `.openpipeline/cache/ai/` | yes | when you ask for an AI explanation |

Add `.openpipeline/` to your `.gitignore`, unless you want to commit proposals.

OpenPipeline never connects to your warehouse and never runs dbt.
