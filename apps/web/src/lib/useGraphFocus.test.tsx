import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import type { Graph, GraphNode, SearchHit } from "./api";
import { useGraphFocus } from "./useGraphFocus";

function node(id: string, name: string): GraphNode {
  return { id, name, kind: "model", description: "", materialized: null, path: null, owner: null };
}

const graph: Graph = {
  nodes: [node("a", "a"), node("b", "b"), node("c", "c"), node("d", "d")],
  edges: [
    { source: "a", target: "b" },
    { source: "b", target: "c" },
    { source: "a", target: "d" },
  ],
};

const hit = (id: string, column: string | null): SearchHit => ({
  kind: column ? "column" : "model",
  node_id: id,
  name: id,
  column,
  snippet: "",
  score: 1,
});

function setup() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      return new Response(
        JSON.stringify({
          model: "b",
          column: "x",
          upstream: [{ node_id: "a", node: "a", kind: "model", column: "x" }],
          downstream: [{ node_id: "c", node: "c", kind: "model", column: "x" }],
        }),
        { status: 200 },
      );
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const onNodeChosen = vi.fn();
  const view = renderHook(() => useGraphFocus(graph, onNodeChosen), { wrapper });
  return { ...view, onNodeChosen };
}

afterEach(() => vi.unstubAllGlobals());

describe("useGraphFocus", () => {
  it("picking a node hit selects and centers it, without a highlight", () => {
    const { result, onNodeChosen } = setup();
    act(() => result.current.pickHit(hit("b", null)));
    expect(result.current.selected?.id).toBe("b");
    expect(result.current.focus).toEqual({ id: "b", seq: 1 });
    expect(result.current.highlightIds).toBeNull();
    expect(onNodeChosen).toHaveBeenCalled();

    act(() => result.current.pickHit(hit("b", null)));
    expect(result.current.focus?.seq).toBe(2);
  });

  it("picking a column hit selects the node and highlights only the column's lineage", async () => {
    const { result } = setup();
    act(() => result.current.pickHit(hit("b", "x")));
    expect(result.current.selected?.id).toBe("b");
    expect(result.current.columnFocus.selection).toEqual({ nodeId: "b", column: "x" });
    await waitFor(() => expect(result.current.highlightIds).not.toBeNull());
    expect([...(result.current.highlightIds ?? [])].sort()).toEqual(["a", "b", "c"]);
  });

  it("choosing another node in the graph drops the column highlight", async () => {
    const { result } = setup();
    act(() => result.current.pickHit(hit("b", "x")));
    await waitFor(() => expect(result.current.highlightIds).not.toBeNull());
    act(() => result.current.setSelected(graph.nodes[3] ?? null));
    expect(result.current.highlightIds).toBeNull();
    expect(result.current.columnFocus.selection).toBeNull();
  });

  it("following a lineage link moves to that node and column", async () => {
    const { result } = setup();
    act(() => result.current.pickHit(hit("b", "x")));
    act(() => result.current.columnFocus.select({ nodeId: "c", column: "x" }));
    expect(result.current.selected?.id).toBe("c");
    expect(result.current.focus?.id).toBe("c");
    act(() => result.current.columnFocus.select(null));
    expect(result.current.columnFocus.selection).toBeNull();
  });
});
