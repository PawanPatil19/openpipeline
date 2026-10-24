// Types mirror the Python API in apps/server/src/openpipeline/api.py.

export type NodeKind = "model" | "source" | "seed" | "snapshot";

export interface GraphNode {
  id: string;
  name: string;
  kind: NodeKind;
  description: string;
  materialized: string | null;
  path: string | null;
  owner: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ProjectInfo {
  name: string;
  root: string;
  loaded_from: "manifest" | "files";
  model_count: number;
  source_count: number;
  warnings: string[];
}

export interface ColumnStory {
  name: string;
  how: string;
}

export interface ModelStory {
  model: string;
  description: string;
  summary: string;
  steps: string[];
  reads_from: string[];
  columns: ColumnStory[];
  filters: string[];
  grain: string[];
  parse_error: string | null;
}

export interface Impact {
  model: string;
  upstream: string[];
  downstream: string[];
}

export type ProposalStatus = "pending" | "accepted" | "rejected";

export interface Proposal {
  id: string;
  title: string;
  rationale: string;
  author: string;
  created_at: string;
  status: ProposalStatus;
  changes: { path: string; content: string }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  project: () => request<ProjectInfo>("/api/project"),
  graph: () => request<Graph>("/api/graph"),
  story: (name: string) => request<ModelStory>(`/api/models/${enc(name)}/story`),
  impact: (name: string) => request<Impact>(`/api/models/${enc(name)}/impact`),
  proposals: () => request<Proposal[]>("/api/proposals"),
  decide: (id: string, status: Exclude<ProposalStatus, "pending">) =>
    request<Proposal>(`/api/proposals/${enc(id)}`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
};
