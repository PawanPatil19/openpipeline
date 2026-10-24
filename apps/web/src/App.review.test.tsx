import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

const node = (id: string, name: string, status: string) => ({
  id,
  name,
  kind: "model",
  description: "",
  materialized: "view",
  path: null,
  owner: null,
  status,
});

const preview = {
  diff: { changes: [] },
  files: [
    {
      path: "models/revenue.sql",
      change: "added",
      diff: "--- /dev/null\n+++ b/models/revenue.sql\n@@ -0,0 +1 @@\n+select 1 as revenue\n",
      before: "",
      after: "select 1 as revenue\n",
    },
  ],
  node_statuses: { "model.p.revenue": "added", "model.p.orders": "unchanged" },
  graph: {
    nodes: [
      node("model.p.orders", "orders", "unchanged"),
      node("model.p.revenue", "revenue", "added"),
    ],
    edges: [{ source: "model.p.orders", target: "model.p.revenue" }],
  },
  new_warnings: ["models/revenue.sql: ref('ghost') not found"],
  parse_errors: [],
  summary: ["Adds 1 model: revenue.", "New warning: models/revenue.sql: ref('ghost') not found"],
};

const proposal = {
  id: "abc123abc123",
  title: "Add revenue model",
  rationale: "Finance asked for it",
  author: "claude",
  created_at: "2026-10-24T00:00:00Z",
  status: "pending",
  changes: [{ path: "models/revenue.sql", content: "select 1 as revenue\n" }],
  comments: [{ author: "reviewer", text: "Looks close", created_at: "2026-10-24T01:00:00Z" }],
};

let conflictOnce = true;
const calls: { url: string; body?: string }[] = [];

function renderApp() {
  conflictOnce = true;
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body as string | undefined });
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
      if (url === "/api/project")
        return json({
          name: "p",
          root: "/p",
          loaded_from: "files",
          model_count: 1,
          source_count: 0,
          warnings: [],
        });
      if (url === "/api/graph") return json({ nodes: [], edges: [] });
      if (url === "/api/proposals") return json([proposal]);
      if (url === "/api/proposals/abc123abc123/preview") return json(preview);
      if (url === "/api/proposals/abc123abc123" && init?.method === "POST") {
        if (conflictOnce && !JSON.parse(init.body as string).force) {
          conflictOnce = false;
          return json(
            {
              detail: {
                code: "stale",
                message: "Files changed",
                changed_files: ["models/revenue.sql"],
              },
            },
            409,
          );
        }
        return json({ ...proposal, status: "accepted" });
      }
      return json({ detail: "not found" }, 404);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

async function openProposals() {
  await userEvent.click(await screen.findByRole("button", { name: /Proposals/ }));
}

describe("proposal review", () => {
  it("summarises the change, highlights warnings, and shows the diff and comments", async () => {
    renderApp();
    await openProposals();
    expect(await screen.findByText("Adds 1 model: revenue.")).toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("ref('ghost') not found");
    await userEvent.click(screen.getByText("models/revenue.sql"));
    expect(screen.getByText("+select 1 as revenue").getAttribute("data-kind")).toBe("add");
    expect(screen.getByText("Looks close")).toBeInTheDocument();
  });

  it("sends feedback as a comment", async () => {
    renderApp();
    await openProposals();
    await userEvent.type(
      await screen.findByPlaceholderText("Leave feedback for the agent"),
      "Please use orders",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    const post = calls.find((c) => c.url.endsWith("/comments"));
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ text: "Please use orders" });
  });

  it("enters and exits review mode with a legend", async () => {
    renderApp();
    await openProposals();
    await userEvent.click(await screen.findByRole("button", { name: "Show on graph" }));
    expect(await screen.findByRole("complementary", { name: "Review mode" })).toBeInTheDocument();
    expect(screen.getByText("Results may change")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Exit review" }));
    expect(screen.queryByRole("complementary", { name: "Review mode" })).not.toBeInTheDocument();
  });

  it("offers Accept anyway after a conflict", async () => {
    renderApp();
    await openProposals();
    await userEvent.click(await screen.findByRole("button", { name: "Accept and write files" }));
    expect(await screen.findByText(/Some files changed after this proposal/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept anyway" }));
    const forced = calls.filter((c) => c.body?.includes('"force":true'));
    expect(forced).toHaveLength(1);
  });

  it("sends the reason when rejecting", async () => {
    renderApp();
    await openProposals();
    await userEvent.type(
      await screen.findByPlaceholderText("Reason for rejecting (optional)"),
      "Not needed",
    );
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    const sent = calls.find((c) => c.body?.includes('"rejected"'));
    expect(JSON.parse(sent?.body ?? "{}")).toEqual({ status: "rejected", reason: "Not needed" });
  });
});
