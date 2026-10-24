import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from openpipeline.ai import (
    AIError,
    AIService,
    AnthropicClient,
    _StoryOutput,
    ai_status,
    story_prompt,
)
from openpipeline_core import ModelGraph, diff_projects, load_project


def test_explain_caches_by_prompt(project_dir: Path, fake_ai: Any) -> None:
    project = load_project(project_dir)
    graph = ModelGraph(project)
    node = project.get("customers")
    assert node is not None
    client = fake_ai
    service = AIService(project_dir, client)

    first = service.explain(project, graph, node)
    assert not first.cached
    assert first.model == "customers"
    assert first.ai_model == "fake-claude"
    assert first.summary == "One row per customer."
    assert len(client.calls) == 1

    second = service.explain(project, graph, node)
    assert second.cached
    assert second.summary == first.summary
    assert len(client.calls) == 1
    assert list((project_dir / ".openpipeline" / "cache" / "ai").glob("*.json"))

    service.explain(project, graph, node, refresh=True)
    assert len(client.calls) == 2


def test_cache_misses_when_the_sql_changes(project_dir: Path, fake_ai: Any) -> None:
    client = fake_ai
    service = AIService(project_dir, client)
    for sql in ("select 1 as a", "select 2 as a"):
        (project_dir / "models" / "marts" / "customers.sql").write_text(sql)
        project = load_project(project_dir)
        node = project.get("customers")
        assert node is not None
        service.explain(project, ModelGraph(project), node)
    assert len(client.calls) == 2


def test_prompt_includes_sql_outline_and_parent_docs(project_dir: Path) -> None:
    project = load_project(project_dir)
    node = project.get("customers")
    assert node is not None
    payload = json.loads(story_prompt(project, ModelGraph(project), node))
    assert "select" in payload["sql"].lower()
    assert payload["outline"]["summary"]
    assert {p["name"] for p in payload["reads_from"]} >= {"orders"}


def test_review_overview_is_cached(project_dir: Path, tmp_path: Path, fake_ai: Any) -> None:
    head = tmp_path / "head"
    shutil.copytree(project_dir, head)
    (head / "models" / "marts" / "revenue.sql").write_text("select 1 as revenue")
    diff = diff_projects(load_project(project_dir), load_project(head))
    client = fake_ai
    service = AIService(head, client)
    assert "revenue" in service.review_overview(diff)
    assert "revenue" in service.review_overview(diff)
    assert len(client.calls) == 1


def test_unavailable_without_a_client(project_dir: Path) -> None:
    service = AIService(project_dir, None)
    assert service.status().available is False
    project = load_project(project_dir)
    with pytest.raises(AIError):
        service.review_overview(diff_projects(project, project))


def test_status_reasons(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert "OPENPIPELINE_AI" in (ai_status().reason or "")
    monkeypatch.delenv("OPENPIPELINE_AI")
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert "ANTHROPIC_API_KEY" in (ai_status().reason or "")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    status = ai_status()
    assert status.available
    assert status.model == "claude-opus-5-5"
    monkeypatch.setenv("OPENPIPELINE_AI_MODEL", "my-model")
    assert ai_status().model == "my-model"


def _anthropic_client(monkeypatch: pytest.MonkeyPatch, **response: Any) -> tuple[Any, MagicMock]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = AnthropicClient("claude-opus-5-5")
    parse = MagicMock(return_value=SimpleNamespace(**response))
    client._client = SimpleNamespace(  # type: ignore[assignment]
        beta=SimpleNamespace(messages=SimpleNamespace(parse=parse))
    )
    return client, parse


def test_anthropic_client_returns_parsed_output(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = _StoryOutput(summary="s", description="d", columns=[], caveats=[])
    client, parse = _anthropic_client(monkeypatch, stop_reason="end_turn", parsed_output=parsed)
    assert client.complete("sys", "prompt", _StoryOutput) is parsed
    kwargs = parse.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["output_format"] is _StoryOutput
    assert kwargs["fallbacks"] == "default"


def test_anthropic_client_refusal_and_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _anthropic_client(monkeypatch, stop_reason="refusal", parsed_output=None)
    with pytest.raises(AIError, match="declined"):
        client.complete("sys", "prompt", _StoryOutput)
    client, _ = _anthropic_client(monkeypatch, stop_reason="end_turn", parsed_output=None)
    with pytest.raises(AIError, match="could not be read"):
        client.complete("sys", "prompt", _StoryOutput)


def test_anthropic_client_turns_sdk_errors_into_ai_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    client, parse = _anthropic_client(monkeypatch)
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    parse.side_effect = anthropic.AuthenticationError(
        "bad key", response=httpx.Response(401, request=request), body=None
    )
    with pytest.raises(AIError, match="key was rejected"):
        client.complete("sys", "prompt", _StoryOutput)
    parse.side_effect = anthropic.APIConnectionError(request=request)
    with pytest.raises(AIError, match="Could not reach"):
        client.complete("sys", "prompt", _StoryOutput)
