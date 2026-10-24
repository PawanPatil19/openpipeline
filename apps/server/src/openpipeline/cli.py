"""The ``openpipeline`` command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from openpipeline import __version__
from openpipeline.ai import AIError, AIService, default_client
from openpipeline_core import (
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
    ai: Annotated[
        bool, typer.Option("--ai", help="Also ask Claude to explain it (needs openpipeline[ai]).")
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
