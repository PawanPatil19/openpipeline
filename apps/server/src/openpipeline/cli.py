"""The ``openpipeline`` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from openpipeline import __version__
from openpipeline_core import (
    ModelGraph,
    Project,
    ProjectLoadError,
    diff_projects,
    explain_model,
    load_project,
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
) -> None:
    """Start the web UI and API."""
    import uvicorn

    from openpipeline.api import create_app

    _load(project_dir)  # Fail fast with a clear message.
    typer.echo(
        f"OpenPipeline {__version__} serving {project_dir.resolve()} on http://{host}:{port}"
    )
    if reload:
        import os

        os.environ["OPENPIPELINE_PROJECT_DIR"] = str(project_dir.resolve())
        uvicorn.run("openpipeline.app:app", host=host, port=port, reload=True)
    else:
        uvicorn.run(create_app(project_dir), host=host, port=port)


@app.command()
def mcp(
    project_dir: ProjectDir = Path("."),
    transport: Annotated[
        str, typer.Option(help="stdio for local agents, streamable-http to run as a service.")
    ] = "stdio",
    host: Annotated[str, typer.Option(envvar="OPENPIPELINE_HOST")] = "127.0.0.1",
    port: Annotated[int, typer.Option(envvar="OPENPIPELINE_MCP_PORT")] = 8485,
) -> None:
    """Run the MCP server for AI agents."""
    from openpipeline.mcp_server import create_mcp_server

    _load(project_dir)
    if transport == "stdio":
        create_mcp_server(project_dir).run("stdio")
    elif transport == "streamable-http":
        create_mcp_server(project_dir).run("streamable-http", host=host, port=port)
    else:
        raise typer.BadParameter("transport must be stdio or streamable-http")


@app.command()
def explain(
    model: Annotated[str, typer.Argument(help="Model name.")],
    project_dir: ProjectDir = Path("."),
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Explain a model in plain English."""
    project = _load(project_dir)
    try:
        story = explain_model(project, model)
    except KeyError as exc:
        typer.secho(str(exc.args[0]), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(story.model_dump_json(indent=2))
        return
    typer.secho(story.model, bold=True)
    if story.description:
        typer.echo(story.description)
    typer.echo(story.summary)
    for i, step in enumerate(story.steps, 1):
        typer.echo(f"  {i}. {step}")


@app.command()
def graph(project_dir: ProjectDir = Path(".")) -> None:
    """Print the model graph as JSON."""
    typer.echo(json.dumps(ModelGraph(_load(project_dir)).to_dict(), indent=2))


@app.command()
def review(
    base: Annotated[Path, typer.Argument(help="The project before the change.")],
    head: Annotated[Path, typer.Argument(help="The project after the change.")],
    output: Annotated[Path | None, typer.Option("-o", "--output")] = None,
) -> None:
    """Summarise what changed between two versions of a project, for a PR comment."""
    md = render_diff_markdown(diff_projects(_load(base), _load(head)))
    if output:
        output.write_text(md, encoding="utf-8")
    else:
        typer.echo(md)
