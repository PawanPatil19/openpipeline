import gzip
import shutil
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "jaffle_shop"
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


@pytest.fixture
def example_dir() -> Path:
    return EXAMPLE


@pytest.fixture(scope="session")
def dbt_labs_jaffle_dir() -> Path:
    return FIXTURES / "jaffle_shop_dbt_labs"


@pytest.fixture(scope="session")
def tuva_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A project dir holding Tuva's dbt_project.yml and its manifest, unzipped."""
    root = tmp_path_factory.mktemp("tuva")
    shutil.copy(FIXTURES / "tuva" / "dbt_project.yml", root / "dbt_project.yml")
    (root / "target").mkdir()
    packed = (FIXTURES / "tuva" / "manifest.json.gz").read_bytes()
    (root / "target" / "manifest.json").write_bytes(gzip.decompress(packed))
    return root
