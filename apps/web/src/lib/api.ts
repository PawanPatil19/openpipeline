// Types mirror the Python API in apps/server/src/openpipeline/api.py.

import { authHeaders, promptForToken } from "./auth";
import { DEMO_READ_ONLY_MESSAGE, demoUrl, isDemo, searchGraph } from "./demo";

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
  adapter: string | null;
  model_count: number;
  source_count: number;
  warnings: string[];
}

/** open: no token needed. token: writes need the Bearer token. off: read-only. */
export type WriteMode = "open" | "token" | "off";

/** `GET /api/auth`. Never contains the token. */
export interface AuthInfo {
  writes: WriteMode;
  token_valid: boolean | null;
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
  /** dbt's compiled SQL; empty unless the project was read from a manifest. */
  compiled_sql: string;
  /** Physical table name in the warehouse, when known. */
  relation_name: string | null;
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
  /** The CTE where this column was worked out; null for the final select or a pass-through. */
  from_step: string | null;
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

export interface SampleError {
  message: string;
  model: string | null;
  missing_table: string | null;
}

export interface SampleResult {
  columns: string[];
  rows: unknown[][];
  row_limit: number;
  error: SampleError | null;
}

export interface SampleStatus {
  duckdb: boolean;
  install_hint: string | null;
  sample_data: string | null;
  tables: { name: string; kind: string; path: string }[];
}

export type SearchKind = NodeKind | "column";

export interface SearchHit {
  kind: SearchKind;
  node_id: string;
  name: string;
  column: string | null;
  snippet: string;
  score: number;
}

export interface ColumnRefView {
  node_id: string;
  node: string;
  kind: NodeKind;
  column: string;
}

export interface ColumnInfo {
  name: string;
  description: string;
  tests: string[];
  upstream: ColumnRefView[];
}

export interface ColumnLineageView {
  model: string;
  column: string;
  upstream: ColumnRefView[];
  downstream: ColumnRefView[];
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
  /** Removed or renamed column -> downstream columns that read it, as "model.column". */
  column_usage?: Record<string, string[]>;
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

export interface RuleLink {
  model: string;
  columns: string[];
}

export interface Rule {
  id: string;
  name: string;
  description: string;
  owner: string | null;
  tags: string[];
  applies_to: RuleLink[];
}

export interface RulesResponse {
  rules: Rule[];
  warnings: string[];
}

/** A rule as it applies to one model, with the columns it is scoped to. */
export interface ModelRule {
  rule: Rule;
  columns: string[];
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
  if (isDemo()) return demoRequest<T>(path, init);
  const isWrite = init?.method !== undefined && init.method !== "GET";
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(isWrite || path === "/api/auth" ? authHeaders() : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    if (res.status === 401 && isWrite) promptForToken();
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    if (detail && typeof detail === "object") {
      throw new ApiError(res.status, detail.message ?? res.statusText, detail.changed_files ?? []);
    }
    throw new ApiError(res.status, detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

/** The hosted demo: read the exported JSON, search in the browser, refuse every write. */
async function demoRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if (init?.method && init.method !== "GET") {
    throw new ApiError(403, DEMO_READ_ONLY_MESSAGE);
  }
  const url = new URL(path, "http://demo.invalid");
  if (url.pathname === "/api/search") {
    const graph = await request<Graph>("/api/graph");
    const limit = Number(url.searchParams.get("limit") ?? 20);
    return searchGraph(graph, url.searchParams.get("q") ?? "", limit) as T;
  }
  const res = await fetch(demoUrl(path));
  if (!res.ok) throw new ApiError(res.status, "This part of the demo was not exported.");
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  // The hosted demo has no server to ask, so it never calls /api/auth.
  auth: (): Promise<AuthInfo> =>
    isDemo() ? Promise.resolve({ writes: "open", token_valid: null }) : request("/api/auth"),
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
  rules: () => request<RulesResponse>("/api/rules"),
  modelRules: (name: string) => request<ModelRule[]>(`/api/models/${enc(name)}/rules`),
  sampleStatus: () => request<SampleStatus>("/api/sample/status"),
  sample: (name: string, limit = 20) =>
    request<SampleResult>(`/api/models/${enc(name)}/sample?limit=${limit}`),
  search: (q: string, limit = 20) => request<SearchHit[]>(`/api/search?q=${enc(q)}&limit=${limit}`),
  columns: (name: string) => request<ColumnInfo[]>(`/api/models/${enc(name)}/columns`),
  columnLineage: (name: string, column: string) =>
    request<ColumnLineageView>(`/api/models/${enc(name)}/columns/${enc(column)}/lineage`),
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
