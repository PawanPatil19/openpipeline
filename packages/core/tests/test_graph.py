from pathlib import Path

import pytest

from openpipeline_core import ModelGraph, Node, NodeKind, Project, load_project


def test_upstream_and_downstream(example_dir: Path) -> None:
    project = load_project(example_dir)
    g = ModelGraph(project)
    names = lambda ids: {project.nodes[i].name for i in ids}  # noqa: E731

    assert names(g.downstream("model.jaffle_shop.stg_payments")) == {"orders", "customers"}
    assert names(g.upstream("model.jaffle_shop.customers")) == {
        "stg_customers",
        "orders",
        "stg_orders",
        "stg_payments",
        "raw.customers",
        "raw.orders",
        "raw.payments",
    }
    assert names(g.upstream("model.jaffle_shop.customers", depth=1)) == {"stg_customers", "orders"}


def test_topological_order_respects_dependencies(example_dir: Path) -> None:
    g = ModelGraph(load_project(example_dir))
    order = g.topological_order()
    assert order.index("model.jaffle_shop.orders") < order.index("model.jaffle_shop.customers")
    assert order.index("model.jaffle_shop.stg_orders") < order.index("model.jaffle_shop.orders")


def test_cycle_is_reported() -> None:
    project = Project(name="x", root="/", loaded_from="files")
    for a, b in (("a", "b"), ("b", "a")):
        project.nodes[a] = Node(unique_id=a, name=a, kind=NodeKind.MODEL, depends_on=[b])
    with pytest.raises(ValueError, match="Cycle"):
        ModelGraph(project).topological_order()


def test_to_dict_shape(example_dir: Path) -> None:
    data = ModelGraph(load_project(example_dir)).to_dict()
    assert len(data["nodes"]) == 8
    assert {"source": "model.jaffle_shop.orders", "target": "model.jaffle_shop.customers"} in (
        data["edges"]
    )
