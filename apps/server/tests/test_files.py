from pathlib import Path

import pytest

from openpipeline.files import safe_path, write_file


def test_writes_and_deletes_inside_project(tmp_path: Path) -> None:
    write_file(tmp_path, "models/a.sql", "select 1")
    assert (tmp_path / "models" / "a.sql").read_text() == "select 1"
    write_file(tmp_path, "models/a.sql", "")
    assert not (tmp_path / "models" / "a.sql").exists()


@pytest.mark.parametrize(
    "rel", ["../evil.sql", "/etc/passwd", ".", ".git/config", ".openpipeline/x.json", "a/.git/b"]
)
def test_refuses_unsafe_paths(tmp_path: Path, rel: str) -> None:
    with pytest.raises(ValueError, match="Path"):
        safe_path(tmp_path, rel)
    with pytest.raises(ValueError, match="Path"):
        write_file(tmp_path, rel, "x")
