from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "jaffle_shop"


@pytest.fixture
def example_dir() -> Path:
    return EXAMPLE
