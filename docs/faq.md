# FAQ and troubleshooting

## Setup

### It says it cannot find a dbt project

OpenPipeline looks for `dbt_project.yml` in the folder you give it. Check the path,
and that you pointed at the folder that holds that file, not at `models/`. With no
path it uses the current folder, then `OPENPIPELINE_PROJECT_DIR`.

### There is no `target/manifest.json`. Is that a problem?

No. When there is no manifest, OpenPipeline reads your SQL and YAML files directly.
The top bar says "read from files". Run `dbt parse` (it needs no warehouse access)
if you want the manifest, which is more accurate for projects that use macros.

### The graph is out of date

If you use the manifest, it is a snapshot from the last time dbt ran. Run
`dbt parse` again. If you use plain files, the server reads them again when they
change, and the page fetches fresh data when you switch back to its tab. Refresh
the browser tab if it still looks stale.

### Do I need dbt installed, or warehouse credentials?

No to both. OpenPipeline never runs dbt and never connects to a warehouse.

### The port is already in use

Pick another with `--port 9000`, or set `OPENPIPELINE_PORT`.

### I cannot reach it from another machine, or from outside Docker

By default it listens only on `127.0.0.1`. Use `--host 0.0.0.0`. The Docker image
already does. Anyone who can reach the port can read the project, so only do this on
a network you trust. Changes need a token: if you do not give `--token`, one is made
up and printed at startup with a link that opens the UI ready to edit. See
[Write access and security](reference/security.md).

### I get "A write token is required" or "This server is read-only"

The server is in token mode (`401`) or read-only mode (`403`). Open the link printed
at startup, or paste the token into the box the UI shows. In Docker, the token is in
`docker logs <container>`. Read-only comes from `--read-only` or
`OPENPIPELINE_READ_ONLY=1`.

## Reading models

### My story says it could not read the SQL

OpenPipeline understands `ref()`, `source()`, and `config()`, shows macro calls by
name, and reads only the first branch of an `{% if %}`. Some Jinja still produces
SQL it cannot read from plain files. Run `dbt compile` so OpenPipeline can use the
manifest and the compiled SQL in it, where dbt has already worked those out.

### Jinja macros are not supported in sample rows

Right. A sample row preview runs your SQL in DuckDB, and OpenPipeline does not run
dbt, so it cannot expand macros. Models that use them show a message instead of
rows. Models without macros preview fine. See [Sample rows](guides/sample-rows.md).

### A sample row preview says a table is missing

It names the table. Add `sample_data/<source>.<table>.csv` for it. For seeds,
check that the CSV is in your `seed-paths`.

### A sample row preview fails with a function error

DuckDB does not know every function your warehouse does. Set `--dialect` so the SQL
is translated, or simplify the expression for the preview. The preview is a
convenience, not a replacement for your warehouse.

### Column lineage is missing a column

Lineage is read from the SQL. A column that comes from a macro, or from a
`select *` over something OpenPipeline cannot see into, may not be traced.

## AI

### The Explain with AI button is missing or disabled

When AI is off, the model panel says why at the bottom. The usual reasons are: the extra is not installed
(`pip install 'openpipeline[ai]'`), no key is set (`ANTHROPIC_API_KEY`), or
`OPENPIPELINE_AI=off`.

### What does it send, and when?

The SQL and descriptions of the model you asked about and of its parents, only when
you click the button or pass `--ai`. See [AI explanations](guides/ai-explanations.md).

### The answer looks wrong

Treat it as a draft. It reads SQL and cannot see your business. Edit it before you
save, and put anything it missed in the description.

## Proposals and agents

### The agent says a path is not allowed

Paths must be inside the project, and not inside `.git` or `.openpipeline`.

### Accepting says files changed since the proposal was made

Someone edited a file the proposal touches. Look at what changed, then choose
**Accept anyway** if the proposal still makes sense, or reject it and ask the agent
to propose again.

### Where are proposals stored?

As JSON files in `.openpipeline/proposals` in your project. You can read, commit,
or delete them.

### Can an agent change my files?

No. Agents can only file proposals. A file changes only when a person accepts one,
or saves a description in the UI.

## Other

### Does it work on Windows?

It is pure Python and should. Paths are handled with `pathlib`. If you hit a
problem, please [open an issue](https://github.com/PawanPatil19/openpipeline/issues).

### Can I stop using it?

Any time. It reads and writes plain dbt files, so your project is just a dbt
project. Delete `.openpipeline/` and `openpipeline.yml` if you want to remove
everything it added.
