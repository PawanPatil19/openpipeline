import importlib.util
import json
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "export_demo.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_demo", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(root: Path, url: str) -> dict | list:  # type: ignore[type-arg]
    return json.loads((root / (url.lstrip("/") + ".json")).read_text(encoding="utf-8"))


def test_export_writes_every_read_endpoint(tmp_path: Path) -> None:
    script = load_script()
    assert script.export_demo(tmp_path) > 20

    project = read(tmp_path, "/api/project")
    assert project["name"] == "jaffle_shop"
    assert project["root"] == "jaffle_shop"  # No temporary path leaks into the site.

    graph = read(tmp_path, "/api/graph")
    ids = {n["id"] for n in graph["nodes"]}
    assert "model.jaffle_shop.customers" in ids
    for node_id in ids:
        base = f"/api/models/{node_id}"
        for suffix in ("", "/story", "/business-story", "/impact", "/rules", "/columns"):
            assert (tmp_path / (base.lstrip("/") + suffix + ".json")).is_file(), base + suffix

    columns = read(tmp_path, "/api/models/model.jaffle_shop.customers/columns")
    for column in columns:
        read(tmp_path, f"/api/models/model.jaffle_shop.customers/columns/{column['name']}/lineage")
    assert read(tmp_path, "/api/models/model.jaffle_shop.customers/sample")["rows"]

    assert read(tmp_path, "/api/ai")["available"] is False
    proposals = read(tmp_path, "/api/proposals")
    assert len(proposals) == 1
    preview = read(tmp_path, f"/api/proposals/{proposals[0]['id']}/preview")
    assert preview["summary"]


def test_slug_matches_encode_uri_component() -> None:
    script = load_script()
    assert script.slug("model.jaffle_shop.customers") == "model.jaffle_shop.customers"
    assert script.slug("a b/c") == "a%20b%2Fc"
    assert script.slug("it's (ok)*!") == "it's%20(ok)*!"
