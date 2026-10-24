import shutil
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "jaffle_shop"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A writable copy of the example project, so tests can change files."""
    dest = tmp_path / "jaffle_shop"
    shutil.copytree(EXAMPLE, dest)
    return dest
