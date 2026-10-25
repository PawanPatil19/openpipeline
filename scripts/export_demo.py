"""Export the demo project's read-only API as static JSON for the hosted web demo.

Usage: uv run python scripts/export_demo.py OUTDIR

Every GET endpoint the web UI uses is written under OUTDIR, mirroring the URL path
with ".json" added: ``/api/models/customers/story`` becomes
``OUTDIR/api/models/customers/story.json``. Names are percent-encoded the way the
browser's ``encodeURIComponent`` does, so the client can build the path from the
same strings it already sends to the API. Search is not exported; the demo client
searches the graph itself.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from openpipeline.ai import AIStatus
from openpipeline.api import create_app
from openpipeline.demo import prepare_demo


def slug(name: str) -> str:
    """Encode a path segment like JavaScript's ``encodeURIComponent``."""
    return quote(name, safe="!'()*-._~")


def export_demo(out_dir: Path) -> int:
    """Write the demo API under ``out_dir`` and return the number of files written."""
    out_dir = out_dir.resolve()
    count = 0

    with tempfile.TemporaryDirectory(prefix="openpipeline-export-") as tmp:
        project_dir, _ = prepare_demo(Path(tmp) / "jaffle_shop")
        app = create_app(project_dir, serve_ui=False, ai_client=None, writes="off")
        client = TestClient(app)

        def fetch(url: str) -> Any:
            res = client.get(url)
            res.raise_for_status()
            return res.json()

        def write(url: str, data: Any) -> None:
            nonlocal count
            path = out_dir / (url.lstrip("/") + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            count += 1

        def copy(url: str) -> Any:
            data = fetch(url)
            write(url, data)
            return data

        project = fetch("/api/project")
        project["root"] = project["name"]  # Not the temporary folder the export ran in.
        write("/api/project", project)
        graph = copy("/api/graph")
        copy("/api/rules")
        copy("/api/glossary")
        # Never offer AI in the hosted demo, whatever the environment has set.
        write(
            "/api/ai",
            AIStatus(
                available=False, model=None, reason="AI is off in the hosted demo."
            ).model_dump(mode="json"),
        )
        sample_status = copy("/api/sample/status")
        sample_ready = bool(sample_status["duckdb"])  # The UI only asks for rows then.

        for node in graph["nodes"]:
            base = f"/api/models/{slug(node['id'])}"
            copy(base)
            copy(f"{base}/story")
            copy(f"{base}/business-story")
            copy(f"{base}/impact")
            copy(f"{base}/rules")
            for column in copy(f"{base}/columns"):
                copy(f"{base}/columns/{slug(column['name'])}/lineage")
            if node["kind"] == "model" and sample_ready:
                copy(f"{base}/sample")  # The UI asks for its default limit.

        for proposal in copy("/api/proposals"):
            copy(f"/api/proposals/{slug(proposal['id'])}/preview")

    return count


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: export_demo.py OUTDIR", file=sys.stderr)
        return 2
    count = export_demo(Path(argv[1]))
    print(f"Wrote {count} files to {argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
