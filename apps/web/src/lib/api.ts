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

export interface DocColumn {
  name: string;
  description: string;
  tests: string[];
}

/** A node as returned by `/api/models/{name}`. */
export interface ModelNode {
  unique_id: string;
  name: string;
  kind: NodeKind;
  description: string;
  path: string | null;
  columns: DocColumn[];
}

export interface DocsUpdate {
  description?: string;
  columns?: Record<string, string>;
}

export interface AIStatus {
  available: boolean;
  model: string | null;
  reason: string | null;
}

export interface AIExplanation {
  summary: string;
  description: string;
  columns: { name: string; description: string }[];
  caveats: string[];
  model: string;
  ai_model: string;
  cached: boolean;
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

export type ProposalStatus = "pending" | "accepted" | "rejected" | "superseded";

export interface Comment {
  author: string;
  text: string;
  created_at: string;
}

export interface Proposal {
  id: string;
  title: string;
  rationale: string;
  author: string;
  created_at: string;
  status: ProposalStatus;
  changes: { path: string; content: string }[];
  base?: Record<string, string | null> | null;
  comments?: Comment[];
  revises?: string | null;
  superseded_by?: string | null;
}

export type NodeStatus = "added" | "modified" | "removed" | "affected" | "unchanged";

export interface ReviewNode extends GraphNode {
  status: NodeStatus;
}

export interface ReviewGraph {
  nodes: ReviewNode[];
  edges: GraphEdge[];
}

export interface FileDiff {
  path: string;
  change: "added" | "modified" | "deleted";
  diff: string;
  before: string;
  after: string;
}

export interface ModelChange {
  name: string;
  unique_id: string;
  change: "added" | "removed" | "modified";
  details: string[];
  downstream: string[];
  owners: string[];
}

export interface ChangePreview {
  diff: { changes: ModelChange[] };
  files: FileDiff[];
  node_statuses: Record<string, NodeStatus>;
  graph: ReviewGraph;
  new_warnings: string[];
  parse_errors: { model: string; message: string }[];
  summary: string[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** Files that changed on disk since the proposal was made, for a 409 conflict. */
    public changedFiles: string[] = [],
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
    const detail = body.detail;
    if (detail && typeof detail === "object") {
      throw new ApiError(res.status, detail.message ?? res.statusText, detail.changed_files ?? []);
    }
    throw new ApiError(res.status, detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  project: () => request<ProjectInfo>("/api/project"),
  graph: () => request<Graph>("/api/graph"),
  model: (name: string) => request<ModelNode>(`/api/models/${enc(name)}`),
  saveDocs: (name: string, update: DocsUpdate) =>
    request<ModelNode>(`/api/models/${enc(name)}/docs`, {
      method: "PUT",
      body: JSON.stringify(update),
    }),
  aiStatus: () => request<AIStatus>("/api/ai"),
  aiExplain: (name: string, refresh = false) =>
    request<AIExplanation>(`/api/models/${enc(name)}/ai-explanation?refresh=${refresh}`, {
      method: "POST",
    }),
  story: (name: string) => request<ModelStory>(`/api/models/${enc(name)}/story`),
  impact: (name: string) => request<Impact>(`/api/models/${enc(name)}/impact`),
  proposals: () => request<Proposal[]>("/api/proposals"),
  decide: (
    id: string,
    status: "accepted" | "rejected",
    options: { reason?: string; force?: boolean } = {},
  ) =>
    request<Proposal>(`/api/proposals/${enc(id)}`, {
      method: "POST",
      body: JSON.stringify({ status, ...options }),
    }),
  comment: (id: string, text: string) =>
    request<Proposal>(`/api/proposals/${enc(id)}/comments`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  preview: (id: string) => request<ChangePreview>(`/api/proposals/${enc(id)}/preview`),
};
