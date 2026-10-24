import dagre from "@dagrejs/dagre";
import type { Graph } from "./api";

export const NODE_WIDTH = 200;
export const NODE_HEIGHT = 56;

export interface Positioned {
  id: string;
  x: number;
  y: number;
}

/** Lay the graph out left to right, sources first, using dagre. */
export function layoutGraph(graph: Graph): Map<string, Positioned> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 24, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of graph.nodes) g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  for (const e of graph.edges) g.setEdge(e.source, e.target);
  dagre.layout(g);

  const out = new Map<string, Positioned>();
  for (const n of graph.nodes) {
    const p = g.node(n.id);
    // dagre gives centre points; React Flow wants the top-left corner.
    out.set(n.id, { id: n.id, x: p.x - NODE_WIDTH / 2, y: p.y - NODE_HEIGHT / 2 });
  }
  return out;
}

/** Ids of everything connected to `id`, in either direction. Used for highlighting. */
export function lineage(graph: Graph, id: string): Set<string> {
  const up = new Map<string, string[]>();
  const down = new Map<string, string[]>();
  for (const e of graph.edges) {
    up.set(e.target, [...(up.get(e.target) ?? []), e.source]);
    down.set(e.source, [...(down.get(e.source) ?? []), e.target]);
  }
  const seen = new Set<string>([id]);
  for (const adj of [up, down]) {
    const stack = [id];
    while (stack.length) {
      const cur = stack.pop() as string;
      for (const next of adj.get(cur) ?? []) {
        if (!seen.has(next)) {
          seen.add(next);
          stack.push(next);
        }
      }
    }
  }
  return seen;
}
