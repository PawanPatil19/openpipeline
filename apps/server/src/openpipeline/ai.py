"""Optional AI-written explanations, using your own Anthropic API key.

Everything else in OpenPipeline works without this. When the ``anthropic``
package is installed (``pip install 'openpipeline[ai]'``) and a key is set, the
UI offers an "Explain with AI" button and ``review --ai`` adds a plain-English
overview to PR summaries.

The deterministic story is always sent along with the SQL, so the model starts
from facts the parser already checked. Answers are cached on disk by a hash of
everything sent, so asking again about an unchanged model is free.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

from openpipeline_core import ModelGraph, Node, NodeKind, Project, ProjectDiff, explain_model

DEFAULT_MODEL = "claude-opus-5-5"
# Models that accept server-side refusal fallbacks (``fallbacks="default"``).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

T = TypeVar("T", bound=BaseModel)


class AIError(Exception):
    """The AI call failed or was declined. The message is safe to show to users."""


class ColumnNote(BaseModel):
    name: str
    description: str


class _StoryOutput(BaseModel):
    summary: str = Field(description="2-4 sentences for a business reader.")
    description: str = Field(description="One sentence suitable as the dbt model description.")
    columns: list[ColumnNote] = Field(
        description="A short description for each output column, in plain words."
    )
    caveats: list[str] = Field(
        description="Things a reader should double-check, such as filters that drop rows. "
        "Empty if there are none."
    )


class AIExplanation(_StoryOutput):
    model: str
    """The dbt model that was explained."""
    ai_model: str
    """The Claude model that wrote the explanation."""
    cached: bool = False


class _ReviewOutput(BaseModel):
    overview: str = Field(description="A short paragraph for a business reader.")


class AIStatus(BaseModel):
    available: bool
    model: str | None = None
    reason: str | None = None
    """Why AI is unavailable, and how to turn it on."""


class AIClient(Protocol):
    model: str

    def complete(self, system: str, prompt: str, schema: type[T]) -> T: ...


class AnthropicClient:
    """Calls Claude through the official SDK, with structured output."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        import anthropic

        self.model = model
        self._anthropic = anthropic
        self._client = anthropic.Anthropic()

    def complete(self, system: str, prompt: str, schema: type[T]) -> T:
        anthropic = self._anthropic
        extra: dict[str, Any] = {}
        if self.model in _FALLBACK_MODELS:
            # On a safety decline, the API retries on a fallback model itself.
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            response = self._client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": "medium"},
                **extra,
            )
        except anthropic.AuthenticationError as exc:
            raise AIError("The Anthropic API key was rejected.") from exc
        except anthropic.RateLimitError as exc:
            raise AIError("Rate limited by the Anthropic API. Try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"The Anthropic API returned an error ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError("Could not reach the Anthropic API.") from exc
        if response.stop_reason == "refusal":
            raise AIError("The model declined to explain this model.")
        if response.parsed_output is None:
            raise AIError("The model returned an answer that could not be read.")
        return response.parsed_output


def ai_status() -> AIStatus:
    if os.environ.get("OPENPIPELINE_AI", "").lower() in {"0", "off", "false"}:
        return AIStatus(available=False, reason="Turned off with OPENPIPELINE_AI=off.")
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return AIStatus(
            available=False,
            reason="Install the AI extra: pip install 'openpipeline[ai]'.",
        )
    if not _has_credentials():
        return AIStatus(
            available=False,
            reason="Set ANTHROPIC_API_KEY (or run `ant auth login`) to turn on AI explanations.",
        )
    return AIStatus(available=True, model=_model_name())


def _model_name() -> str:
    return os.environ.get("OPENPIPELINE_AI_MODEL") or DEFAULT_MODEL


def _has_credentials() -> bool:
    if any(
        os.environ.get(k)
        for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")
    ):
        return True
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "anthropic"
    return config.is_dir()


def default_client() -> AIClient | None:
    status = ai_status()
    return AnthropicClient(_model_name()) if status.available else None


# --- Prompts -----------------------------------------------------------------

_STORY_SYSTEM = """\
You explain dbt models to people who do not read SQL: analysts, product \
managers, and business owners. You are given a model's SQL, a parser-generated \
outline of it, and documentation for the tables it reads from.

Write plainly. Say what one row of the result represents, where the data comes \
from, and what each column means for the business. Prefer business words over \
SQL words ("customers who have placed at least one order", not "inner join on \
customer_id"). Do not invent facts that the SQL and documentation do not \
support; if something is unclear, put it under caveats instead."""

_REVIEW_SYSTEM = """\
You summarise a pull request to a dbt project for business stakeholders. You \
are given a machine-generated list of model changes and the affected \
downstream models. Write one short paragraph: what changes for people who use \
these tables, and who should check the result. Do not restate every detail; \
the list is shown below your paragraph. Do not invent facts."""


def _node_brief(node: Node) -> dict[str, Any]:
    return {
        "name": node.name,
        "kind": node.kind.value,
        "description": node.description or None,
        "columns": {c.name: c.description for c in node.columns if c.description} or None,
    }


def story_prompt(project: Project, graph: ModelGraph, node: Node) -> str:
    story = explain_model(project, node.unique_id)
    payload = {
        "model": node.name,
        "current_description": node.description or None,
        "current_column_docs": {c.name: c.description for c in node.columns} or None,
        "owner": node.owner,
        "sql": node.raw_sql,
        "outline": story.model_dump(exclude={"model", "description"}),
        "reads_from": [_node_brief(project.nodes[u]) for u in graph.parents(node.unique_id)],
        "used_by": [
            project.nodes[u].name
            for u in graph.downstream(node.unique_id)
            if project.nodes[u].kind == NodeKind.MODEL
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


class AIService:
    def __init__(self, project_root: str | Path, client: AIClient | None) -> None:
        self.client = client
        self.cache_dir = Path(project_root).resolve() / ".openpipeline" / "cache" / "ai"

    def status(self) -> AIStatus:
        if self.client is None:
            return ai_status()
        return AIStatus(available=True, model=self.client.model)

    def _require(self) -> AIClient:
        if self.client is None:
            raise AIError(ai_status().reason or "AI is not available.")
        return self.client

    def explain(
        self, project: Project, graph: ModelGraph, node: Node, *, refresh: bool = False
    ) -> AIExplanation:
        client = self._require()
        prompt = story_prompt(project, graph, node)
        key = _cache_key("story", client.model, prompt)
        if not refresh and (hit := self._read(key)) is not None:
            return AIExplanation.model_validate({**hit, "cached": True})
        out = client.complete(_STORY_SYSTEM, prompt, _StoryOutput)
        result = AIExplanation(model=node.name, ai_model=client.model, **out.model_dump())
        self._write(key, result.model_dump(exclude={"cached"}))
        return result

    def review_overview(self, diff: ProjectDiff) -> str:
        client = self._require()
        prompt = diff.model_dump_json(indent=2)
        key = _cache_key("review", client.model, prompt)
        if (hit := self._read(key)) is not None:
            return str(hit["overview"])
        out = client.complete(_REVIEW_SYSTEM, prompt, _ReviewOutput)
        self._write(key, out.model_dump())
        return out.overview

    def _read(self, key: str) -> dict[str, Any] | None:
        f = self.cache_dir / f"{key}.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, key: str, data: dict[str, Any]) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass  # A read-only project still works, just without the cache.


def _cache_key(kind: str, model: str, prompt: str) -> str:
    return hashlib.sha256(f"{kind}\0{model}\0{prompt}".encode()).hexdigest()[:32]
