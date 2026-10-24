# openpipeline

See what your dbt project does, in plain English, and review every change before
it lands. This package is the OpenPipeline app: a command line tool, a web server
with the graph UI, and an MCP server for AI agents.

```bash
pip install openpipeline
openpipeline demo                                   # try it on an example project
openpipeline serve path/to/your/dbt/project         # use it on yours
```

Optional extras: `openpipeline[ai]` for AI explanations with your own Anthropic key,
and `openpipeline[preview]` for sample rows run locally with DuckDB.

Documentation: <https://openpipeline.vercel.app/docs/>
Source and issues: <https://github.com/PawanPatil19/openpipeline>
