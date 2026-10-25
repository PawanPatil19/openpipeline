"""The API and MCP server on a real, large project (the Tuva fixture)."""

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from openpipeline.api import create_app
from openpipeline.mcp_server import create_mcp_server

LOCAL = "http://127.0.0.1"


def test_api_on_tuva(tuva_dir: Path) -> None:
    client = TestClient(create_app(tuva_dir, serve_ui=False), base_url=LOCAL)
    info = client.get("/api/project").json()
    assert info["model_count"] >= 300

    start = time.perf_counter()
    graph = client.get("/api/graph").json()
    elapsed = time.perf_counter() - start
    assert len(graph["nodes"]) >= info["model_count"]
    assert elapsed < 10


def test_mcp_list_models_on_tuva(tuva_dir: Path) -> None:
    server = create_mcp_server(tuva_dir)
    result = asyncio.run(server.call_tool("list_models", {}))
    assert not result.is_error
    structured = result.structured_content or {}
    assert len(structured["result"]) >= 300
