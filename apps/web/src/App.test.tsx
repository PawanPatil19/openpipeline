import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

const responses: Record<string, unknown> = {
  "/api/project": {
    name: "jaffle_shop",
    root: "/p",
    loaded_from: "files",
    model_count: 1,
    source_count: 0,
    warnings: [],
  },
  "/api/graph": { nodes: [], edges: [] },
  "/api/rules": { rules: [], warnings: [] },
  "/api/proposals": [
    {
      id: "abc123abc123",
      title: "Add revenue model",
      rationale: "Finance asked for it",
      author: "claude",
      created_at: "2026-10-24T00:00:00Z",
      status: "pending",
      changes: [{ path: "models/revenue.sql", content: "select 1" }],
    },
  ],
};

function renderApp() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = responses[url];
      return new Response(JSON.stringify(body ?? { detail: "not found" }), {
        status: body ? 200 : 404,
      });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("shows the project summary and an empty-selection hint", async () => {
    renderApp();
    expect(await screen.findByText(/jaffle_shop · 1 models/)).toBeInTheDocument();
    expect(screen.getByText("Pick a model")).toBeInTheDocument();
  });

  it("lists pending proposals with a count", async () => {
    renderApp();
    const tab = await screen.findByRole("button", { name: /Proposals\s*1/ });
    await userEvent.click(tab);
    expect(await screen.findByText("Add revenue model")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept and write files" })).toBeEnabled();
  });
});
