import shutil
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from openpipeline.ai import AIError, _ReviewOutput, _StoryOutput

T = TypeVar("T", bound=BaseModel)

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "jaffle_shop"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A writable copy of the example project, so tests can change files."""
    dest = tmp_path / "jaffle_shop"
    shutil.copytree(EXAMPLE, dest)
    return dest


@pytest.fixture(autouse=True)
def _no_real_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never reach for a real API key. Tests that need AI inject a fake client."""
    monkeypatch.setenv("OPENPIPELINE_AI", "off")


# A stand-in for the Anthropic client, so AI tests need no network.#
class FakeClient:
    model = "fake-claude"

    def __init__(self, error: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error = error

    def complete(self, system: str, prompt: str, schema: type[T]) -> T:
        self.calls.append((system, prompt))
        if self.error:
            raise AIError(self.error)
        out: dict[str, Any]
        if schema is _StoryOutput:
            out = {
                "summary": "One row per customer.",
                "description": "Every customer and what they spent.",
                "columns": [
                    {"name": "customer_id", "description": "The customer's id."},
                    {"name": "lifetime_value", "description": "Total money spent."},
                ],
                "caveats": ["Customers with no orders have no spend."],
            }
        else:
            assert schema is _ReviewOutput
            out = {"overview": "A new revenue table is added for finance."}
        return schema.model_validate(out)


@pytest.fixture
def fake_ai() -> FakeClient:
    return FakeClient()
