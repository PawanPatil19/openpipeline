// Demo mode: the hosted demo is a static build with no server behind it. Reads come
// from JSON files written by scripts/export_demo.py, and every write is refused.

import type { Graph, SearchHit } from "./api";

export const DEMO_COMMAND = "pip install openpipeline && openpipeline demo";

export const DEMO_READ_ONLY_MESSAGE = `This is a read-only demo. Run \`${DEMO_COMMAND}\` to try it for real.`;

/** True in a build made with VITE_DEMO=1. */
export function isDemo(): boolean {
  return import.meta.env.VITE_DEMO === "1";
}

/**
 * Where the exported JSON for an API path lives, for example
 * `/api/models/a/story?x=1` -> `/demo/data/api/models/a/story.json`. The query string
 * is dropped; the export holds one answer per path (the UI's default limit for samples).
 */
export function demoUrl(path: string): string {
  const [pathname = ""] = path.split("?", 1);
  return `${import.meta.env.BASE_URL}data${pathname}.json`;
}

/** The same search the server does, in the browser, over the graph's nodes. */
export function searchGraph(graph: Graph, query: string, limit: number): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const hits: SearchHit[] = [];
  for (const node of graph.nodes) {
    const name = node.name.toLowerCase();
    let score = 0;
    if (name === q) score = 100;
    else if (name.startsWith(q)) score = 80;
    else if (name.includes(q)) score = 60;
    else if (node.description.toLowerCase().includes(q)) score = 30;
    if (score === 0) continue;
    hits.push({
      kind: node.kind,
      node_id: node.id,
      name: node.name,
      column: null,
      snippet: node.description,
      score,
    });
  }
  return hits.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name)).slice(0, limit);
}
