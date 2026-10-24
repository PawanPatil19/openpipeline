import shutil
from pathlib import Path

import pytest

from openpipeline_core import DocsUpdate, load_project, update_docs


def _write(root: Path, edit_path: str, content: str) -> None:
    (root / edit_path).parent.mkdir(parents=True, exist_ok=True)
    (root / edit_path).write_text(content)


def test_updates_existing_entry_and_keeps_comments(tmp_path: Path, example_dir: Path) -> None:
    root = tmp_path / "p"
    shutil.copytree(example_dir, root)
    schema = root / "models" / "marts" / "schema.yml"
    schema.write_text("# Marts docs\n" + schema.read_text())

    edit = update_docs(
        load_project(root),
        "customers",
        DocsUpdate(
            description="Everyone who has signed up.",
            columns={"lifetime_value": "Money paid.", "first_name": "Given name."},
        ),
    )
    assert edit.path == "models/marts/schema.yml"
    assert edit.content.startswith("# Marts docs\n")
    _write(root, edit.path, edit.content)

    node = load_project(root).get("customers")
    assert node is not None
    assert node.description == "Everyone who has signed up."
    cols = {c.name: c.description for c in node.columns}
    assert cols == {"lifetime_value": "Money paid.", "first_name": "Given name."}
    # Other models in the same file are untouched.
    orders = load_project(root).get("orders")
    assert orders is not None
    assert orders.description.startswith("One row per order")


def test_adds_entry_when_model_is_undocumented(tmp_path: Path, example_dir: Path) -> None:
    root = tmp_path / "p"
    shutil.copytree(example_dir, root)
    (root / "models" / "marts" / "revenue.sql").write_text("select 1 as revenue")

    edit = update_docs(load_project(root), "revenue", DocsUpdate(description="Revenue."))
    assert edit.path == "models/marts/schema.yml"
    _write(root, edit.path, edit.content)
    project = load_project(root)
    assert project.get("revenue").description == "Revenue."  # type: ignore[union-attr]
    assert project.get("customers").description.startswith("One row")  # type: ignore[union-attr]


def test_creates_schema_file_in_empty_folder(tmp_path: Path, example_dir: Path) -> None:
    root = tmp_path / "p"
    shutil.copytree(example_dir, root)
    (root / "models" / "finance").mkdir()
    (root / "models" / "finance" / "fx.sql").write_text("select 1 as rate")

    edit = update_docs(load_project(root), "fx", DocsUpdate(columns={"rate": "FX rate."}))
    assert edit.path == "models/finance/schema.yml"
    assert "version: 2" in edit.content
    _write(root, edit.path, edit.content)
    fx = load_project(root).get("fx")
    assert fx is not None
    assert [(c.name, c.description) for c in fx.columns] == [("rate", "FX rate.")]


def test_unknown_model(example_dir: Path) -> None:
    with pytest.raises(KeyError):
        update_docs(load_project(example_dir), "nope", DocsUpdate(description="x"))
