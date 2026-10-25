"""The ``openpipeline`` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from openpipeline import __version__
from openpipeline.ai import AIError, AIService, default_client
from openpipeline.security import BearerTokenMiddleware, browser_url, resolve_write_mode
from openpipeline_core import (
    ColumnLineage,
    ModelGraph,
    Project,
    ProjectLoadError,
    Rule,
    diff_projects,
    explain_model,
    load_project,
    load_rules,
    render_diff_markdown,
)

app = typer.Typer(
    name="openpipeline",
    help="Explain and review dbt projects.",
    no_args_is_help=True,
    add_completion=False,
)

ProjectDir = Annotated[
    Path,
    typer.Argument(envvar="OPENPIPELINE_PROJECT_DIR", help="Path to a dbt project."),
]

SampleDataOpt = Annotated[
    Path | None,
    typer.Option(
        "--sample-data",
        envvar="OPENPIPELINE_SAMPLE_DATA",
        help="Folder of sample CSV or Parquet files, or a .duckdb file, for row previews.",
    ),
]
DialectOpt = Annotated[
    str | None,
    typer.Option(
        "--dialect",
        envvar="OPENPIPELINE_DIALECT",
        help="SQL dialect of the project, such as snowflake or bigquery.",
    ),
]
TokenOpt = Annotated[
    str | None,
    typer.Option(
        "--token",
        envvar="OPENPIPELINE_TOKEN",
        help="Require this Bearer token for writes (and for MCP over HTTP). "
        "Made up and printed when you listen on a non-loopback address without one.",
    ),
]
ReadOnlyOpt = Annotated[
    bool,
    typer.Option(
        "--read-only",
        envvar="OPENPIPELINE_READ_ONLY",
        help="Refuse every write: no editing docs, accepting proposals, comments, or AI calls.",
    ),
]


def _load(path: Path) -> Project:
    try:
        return load_project(path)
    except ProjectLoadError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(__version__)


@app.command()
def serve(
    project_dir: ProjectDir = Path("."),
    host: Annotated[str, typer.Option(envvar="OPENPIPELINE_HOST")] = "127.0.0.1",
    port: Annotated[int, typer.Option(envvar="OPENPIPELINE_PORT")] = 8484,
    reload: Annotated[bool, typer.Option(help="Restart on code changes (dev only).")] = False,
    sample_data: SampleDataOpt = None,
    dialect: DialectOpt = None,
    token: TokenOpt = None,
    read_only: ReadOnlyOpt = False,
) -> None:
    """Start the web UI and API.

    Writes are open on a loopback address, need a token on any other address, and are
    refused with --read-only.
    """
    import uvicorn

    from openpipeline.api import create_app

    _load(project_dir)  # Fail fast with a clear message.
    settings = resolve_write_mode(host, token, read_only)
    typer.echo(
        f"OpenPipeline {__version__} serving {project_dir.resolve()} on http://{host}:{port}"
    )
    if settings.mode == "off":
        typer.echo("Read-only: edits, proposal decisions, comments and AI calls are refused.")
    elif settings.mode == "token":
        if settings.generated:
            typer.echo(f"Listening on {host}, so writes need a token. Generated for this run:")
            typer.echo(f"  {settings.token}")
            typer.echo("Open this link to use it in the browser:")
            typer.echo(f"  {browser_url(host, port, settings.token)}")
            typer.echo("Pass --token or OPENPIPELINE_TOKEN to choose your own.")
        else:
            typer.echo(f"Writes need the token you gave. Open {browser_url(host, port)}?token=...")
    if reload:
        import os

        os.environ["OPENPIPELINE_PROJECT_DIR"] = str(project_dir.resolve())
        os.environ["OPENPIPELINE_HOST"] = host
        os.environ["OPENPIPELINE_PORT"] = str(port)
        if settings.token:
            os.environ["OPENPIPELINE_TOKEN"] = settings.token
        if settings.mode == "off":
            os.environ["OPENPIPELINE_READ_ONLY"] = "1"
        if sample_data:
            os.environ["OPENPIPELINE_SAMPLE_DATA"] = str(sample_data.resolve())
        if dialect:
            os.environ["OPENPIPELINE_DIALECT"] = dialect
        uvicorn.run("openpipeline.app:app", host=host, port=port, reload=True)
    else:
        api = create_app(
            project_dir,
            sample_data=sample_data,
            dialect=dialect,
            writes=settings.mode,
            write_token=settings.token,
            host=host,
            port=port,
        )
        uvicorn.run(api, host=host, port=port)


@app.command()
def mcp(
    project_dir: ProjectDir = Path("."),
    transport: Annotated[
        str, typer.Option(help="stdio for local agents, streamable-http to run as a service.")
    ] = "stdio",
    host: Annotated[str, typer.Option(envvar="OPENPIPELINE_HOST")] = "127.0.0.1",
    port: Annotated[int, typer.Option(envvar="OPENPIPELINE_MCP_PORT")] = 8485,
    sample_data: SampleDataOpt = None,
    dialect: DialectOpt = None,
    token: TokenOpt = None,
) -> None:
    """Run the MCP server for AI agents.

    stdio is local to the agent that starts it. streamable-http needs a Bearer token
    unless it listens on a loopback address.
    """
    from openpipeline.mcp_server import create_mcp_server

    _load(project_dir)
    server = create_mcp_server(project_dir, sample_data=sample_data, dialect=dialect)
    if transport == "stdio":
        server.run("stdio")
    elif transport == "streamable-http":
        import uvicorn
        from starlette.types import ASGIApp

        settings = resolve_write_mode(host, token, read_only=False)
        mcp_app: ASGIApp = server.streamable_http_app(host=host)
        if settings.token:
            if settings.generated:
                typer.echo(f"Listening on {host}, so agents need a token. Generated for this run:")
                typer.echo(f"  {settings.token}")
                typer.echo("Clients send it as 'Authorization: Bearer <token>'.")
            mcp_app = BearerTokenMiddleware(mcp_app, settings.token)
        uvicorn.run(mcp_app, host=host, port=port)
    else:
        raise typer.BadParameter("transport must be stdio or streamable-http")


@app.command()
def explain(
    model: Annotated[str, typer.Argument(help="Model name.")],
    project_dir: ProjectDir = Path("."),
    as_json: Annotated[bool, typer.Option("--json")] = False,
    ai: Annotated[
        bool, typer.Option("--ai", help="Also ask Claude to explain it (needs openpipeline\\[ai]).")
    ] = False,
) -> None:
    """Explain a model in plain English."""
    project = _load(project_dir)
    try:
        story = explain_model(project, model)
    except KeyError as exc:
        typer.secho(str(exc.args[0]), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    explanation = None
    if ai:
        node = project.get(model)
        assert node is not None  # explain_model found it.
        try:
            explanation = AIService(project.root, default_client()).explain(
                project, ModelGraph(project), node
            )
        except AIError as exc:
            typer.secho(f"AI explanation not available: {exc}", fg=typer.colors.YELLOW, err=True)
    if as_json:
        data = story.model_dump(mode="json")
        if explanation is not None:
            data["ai"] = explanation.model_dump(mode="json")
        typer.echo(json.dumps(data, indent=2))
        return
    typer.secho(story.model, bold=True)
    if story.description:
        typer.echo(story.description)
    typer.echo(story.summary)
    for i, step in enumerate(story.steps, 1):
        typer.echo(f"  {i}. {step}")
    if story.columns:
        typer.echo()
        typer.secho("Columns", bold=True)
        for column in story.columns:
            typer.echo(f"  {column.name}: {column.how}")
    if explanation is not None:
        typer.echo()
        typer.secho(f"In plain words (written by {explanation.ai_model})", bold=True)
        typer.echo(explanation.summary)
        for note in explanation.columns:
            typer.echo(f"  {note.name}: {note.description}")
        for caveat in explanation.caveats:
            typer.echo(f"  Check: {caveat}")


@app.command()
def graph(project_dir: ProjectDir = Path(".")) -> None:
    """Print the model graph as JSON."""
    typer.echo(json.dumps(ModelGraph(_load(project_dir)).to_dict(), indent=2))


@app.command()
def review(
    base: Annotated[Path, typer.Argument(help="The project before the change.")],
    head: Annotated[Path, typer.Argument(help="The project after the change.")],
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
    ai: Annotated[
        bool, typer.Option("--ai", help="Add a plain-words overview written by Claude.")
    ] = False,
) -> None:
    """Summarise what changed between two versions of a project, for a PR comment."""
    base_project, head_project = _load(base), _load(head)
    diff = diff_projects(
        base_project,
        head_project,
        base_rules=load_rules(base, base_project),
        head_rules=load_rules(head, head_project),
        base_lineage=ColumnLineage(base_project),
    )
    md = render_diff_markdown(diff)
    if ai and not diff.is_empty:
        try:
            overview = AIService(head_project.root, default_client()).review_overview(diff)
        except AIError as exc:
            typer.secho(
                f"Warning: skipping the AI overview. {exc}", fg=typer.colors.YELLOW, err=True
            )
        else:
            heading, _, rest = md.partition("\n")
            md = f"{heading}\n\n**In plain words.** {overview.strip()}\n{rest}"
    if output:
        output.write_text(md, encoding="utf-8")
    else:
        typer.echo(md)


@app.command()
def rules(
    project_dir: ProjectDir = Path("."),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List business rules, grouped by owner."""
    project = _load(project_dir)
    registry = load_rules(project_dir, project)
    if as_json:
        typer.echo(registry.model_dump_json(indent=2))
        return
    if not registry.rules:
        typer.echo("No business rules found. Add them to openpipeline.yml.")
    by_owner: dict[str, list[Rule]] = {}
    for rule in registry.rules:
        by_owner.setdefault(rule.owner or "No owner", []).append(rule)
    for owner in sorted(by_owner, key=lambda o: (o == "No owner", o)):
        typer.secho(owner, bold=True)
        for rule in sorted(by_owner[owner], key=lambda r: r.name.lower()):
            typer.echo(f"  {rule.name} ({rule.id})")
            if rule.description:
                typer.echo(f"    {' '.join(rule.description.split())}")
            for link in rule.applies_to:
                cols = f" [{', '.join(link.columns)}]" if link.columns else ""
                typer.echo(f"    applies to {link.model}{cols}")
    for warning in registry.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)


@app.command()
def sample(
    model: Annotated[str, typer.Argument(help="Model name.")],
    project_dir: ProjectDir = Path("."),
    limit: Annotated[int, typer.Option(help="Rows to show (1 to 200).")] = 10,
    sample_data: SampleDataOpt = None,
    dialect: DialectOpt = None,
) -> None:
    """Show a few rows of a model, run on local sample data with DuckDB."""
    from openpipeline.sample import SampleEngine
    from openpipeline.state import ProjectState

    _load(project_dir)
    engine = SampleEngine(ProjectState(project_dir), sample_data=sample_data, dialect=dialect)
    try:
        result = engine.sample(model, limit)
    except KeyError as exc:
        typer.secho(str(exc.args[0]), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if result.error:
        typer.secho(result.error.message, fg=typer.colors.RED, err=True)
        if result.error.missing_table:
            typer.echo(
                f"Add sample_data/{result.error.missing_table}.csv to preview this model.",
                err=True,
            )
        raise typer.Exit(code=1)
    cells = [[("" if v is None else str(v)) for v in row] for row in result.rows]
    widths = [
        max(len(col), *(len(r[i]) for r in cells)) if cells else len(col)
        for i, col in enumerate(result.columns)
    ]
    typer.echo("  ".join(c.ljust(w) for c, w in zip(result.columns, widths, strict=True)).rstrip())
    typer.echo("  ".join("-" * w for w in widths))
    for r in cells:
        typer.echo("  ".join(v.ljust(w) for v, w in zip(r, widths, strict=True)).rstrip())
    typer.echo(f"({len(cells)} rows, limit {result.row_limit})")


@app.command()
def lineage(
    model: Annotated[str, typer.Argument(help="Model name.")],
    column: Annotated[str, typer.Argument(help="Column name.")],
    project_dir: ProjectDir = Path("."),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show where a column comes from and where it is used."""
    from openpipeline.lineage_views import column_lineage_view

    project = _load(project_dir)
    node = project.get(model)
    if node is None:
        typer.secho(f"No model named {model!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    try:
        view = column_lineage_view(project, ColumnLineage(project), node, column)
    except KeyError as exc:
        typer.secho(str(exc.args[0]), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(view.model_dump_json(indent=2))
        return
    typer.secho(f"{view.model}.{view.column}", bold=True)
    for title, refs in (("Comes from", view.upstream), ("Used by", view.downstream)):
        typer.echo(f"{title}:")
        if not refs:
            typer.echo("  nothing found")
        for ref in refs:
            typer.echo(f"  {ref.node}.{ref.column}")


@app.command()
def demo(
    directory: Annotated[
        Path | None,
        typer.Option("--dir", help="Copy the example here instead of a temporary folder."),
    ] = None,
    host: Annotated[str, typer.Option(envvar="OPENPIPELINE_HOST")] = "127.0.0.1",
    port: Annotated[int, typer.Option(envvar="OPENPIPELINE_PORT")] = 8484,
    serve_it: Annotated[
        bool,
        typer.Option("--serve/--no-serve", help="Start the server, or just prepare the folder."),
    ] = True,
    token: TokenOpt = None,
    read_only: ReadOnlyOpt = False,
) -> None:
    """Try everything: the example project plus a proposal waiting for your review."""
    from openpipeline.demo import prepare_demo

    try:
        root, _ = prepare_demo(directory)
    except FileExistsError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if not serve_it:
        typer.echo(str(root))
        return
    typer.echo(f"Demo project: {root}")
    typer.echo("An agent proposal is waiting for you in the Proposals tab.")
    serve(root, host=host, port=port, reload=False, token=token, read_only=read_only)
