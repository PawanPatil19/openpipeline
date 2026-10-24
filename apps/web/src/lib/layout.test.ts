import type { Graph } from "./api";
import { layoutGraph, lineage } from "./layout";

const node = (id: string) => ({
  id,
  name: id,
  kind: "model" as const,
  description: "",
  materialized: null,
  path: null,
  owner: null,
});

// a -> b -> c, and d is unrelated.
const graph: Graph = {
  nodes: ["a", "b", "c", "d"].map(node),
  edges: [
    { source: "a", target: "b" },
    { source: "b", target: "c" },
  ],
};

describe("layoutGraph", () => {
  it("places upstream nodes to the left of downstream ones", () => {
    const pos = layoutGraph(graph);
    expect(pos.size).toBe(4);
    const x = (id: string) => pos.get(id)?.x ?? Number.NaN;
    expect(x("a")).toBeLessThan(x("b"));
    expect(x("b")).toBeLessThan(x("c"));
  });
});

describe("lineage", () => {
  it("includes everything upstream and downstream, but not unrelated nodes", () => {
    expect([...lineage(graph, "b")].sort()).toEqual(["a", "b", "c"]);
    expect([...lineage(graph, "d")]).toEqual(["d"]);
  });
});
