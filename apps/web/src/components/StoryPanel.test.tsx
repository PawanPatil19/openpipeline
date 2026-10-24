import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { GraphNode } from "../lib/api";
import { StoryPanel } from "./StoryPanel";

const node: GraphNode = {
  id: "model.shop.customers",
  name: "customers",
  kind: "model",
  description: "Old text.",
  materialized: "table",
  path: "models/customers.sql",
  owner: null,
};

const story = {
  model: "customers",
  description: "Old text.",
  summary: "One row per customer.",
  steps: ["Read orders"],
  reads_from: ["orders"],
  columns: [
    { name: "customer_id", how: "Taken from orders." },
    { name: "total", how: "Sum of amount." },
  ],
  filters: [],
  grain: ["customer_id"],
  parse_error: null,
};

interface Setup {
  aiAvailable?: boolean;
  aiFails?: boolean;
}

function setup({ aiAvailable = true, aiFails = false }: Setup = {}) {
  let description = "Old text.";
  let columns: Record<string, string> = { customer_id: "Customer key." };
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  const modelNode = () => ({
    unique_id: node.id,
    name: "customers",
    kind: "model",
    description,
    path: node.path,
    columns: Object.entries(columns).map(([name, d]) => ({ name, description: d, tests: [] })),
  });
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      if (url.endsWith("/rules")) return json([]);
      if (url.endsWith("/story")) return json(story);
      if (url.endsWith("/impact"))
        return json({ model: "customers", upstream: [], downstream: ["report"] });
      if (url === "/api/ai")
        return json(
          aiAvailable
            ? { available: true, model: "claude-test", reason: null }
            : { available: false, model: null, reason: "Set ANTHROPIC_API_KEY to turn it on." },
        );
      if (url.includes("/ai-explanation")) {
        if (aiFails) return json({ detail: "Rate limited." }, 502);
        return json({
          summary: "Everyone who has ordered.",
          description: "Customers and their spend.",
          columns: [
            { name: "total", description: "Money spent." },
            { name: "unknown", description: "Ignored." },
          ],
          caveats: ["Customers with no orders are left out."],
          model: "customers",
          ai_model: "claude-test",
          cached: true,
        });
      }
      if (url.endsWith("/docs") && method === "PUT") {
        if (body?.description !== undefined) description = String(body.description);
        columns = { ...columns, ...(body?.columns as Record<string, string> | undefined) };
        return json(modelNode());
      }
      if (url.startsWith("/api/models/")) return json(modelNode());
      return json({ detail: "not found" }, 404);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <StoryPanel node={node} />
    </QueryClientProvider>,
  );
  return { calls, invalidate };
}

afterEach(() => vi.unstubAllGlobals());

describe("StoryPanel editing", () => {
  it("edits and saves the description, then refreshes queries", async () => {
    const { calls, invalidate } = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Edit description" }));
    const box = screen.getByRole("textbox", { name: "Description" });
    expect(box).toHaveValue("Old text.");
    await userEvent.clear(box);
    await userEvent.type(box, "New text.");
    await userEvent.click(screen.getByRole("button", { name: "Save description" }));

    expect(await screen.findByText("New text.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ description: "New text." });
    const keys = invalidate.mock.calls.map((c) => (c[0] as { queryKey: string[] }).queryKey[0]);
    expect(keys).toEqual(expect.arrayContaining(["graph", "story", "model"]));
  });

  it("cancel leaves the description alone", async () => {
    const { calls } = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Edit description" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Description" }), " more");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Old text.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("shows documented column text and saves only what changed", async () => {
    const { calls } = setup();
    expect(await screen.findByText("Customer key.")).toBeInTheDocument();
    expect(screen.getByText("Sum of amount.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit column descriptions" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Description for total" }), "Spend.");
    await userEvent.click(screen.getByRole("button", { name: "Save column descriptions" }));

    await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ columns: { total: "Spend." } });
    expect(await screen.findByText("Spend.")).toBeInTheDocument();
  });
});

describe("StoryPanel AI", () => {
  it("shows the AI answer and only prefills the editors", async () => {
    const { calls } = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Explain with AI" }));
    expect(await screen.findByText("Everyone who has ordered.")).toBeInTheDocument();
    expect(screen.getByText(/Customers with no orders are left out/)).toBeInTheDocument();
    expect(screen.getByText(/Written by claude-test \(cached\)/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Use as description" }));
    expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue(
      "Customers and their spend.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Use column notes" }));
    expect(screen.getByRole("textbox", { name: "Description for total" })).toHaveValue(
      "Money spent.",
    );
    expect(screen.getByRole("textbox", { name: "Description for customer_id" })).toHaveValue(
      "Customer key.",
    );
    expect(screen.queryByRole("textbox", { name: "Description for unknown" })).toBeNull();
    // Nothing is saved until the person clicks Save.
    expect(calls.some((c) => c.method === "PUT")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Save column descriptions" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
        columns: { total: "Money spent." },
      }),
    );
  });

  it("shows an error when the AI call fails", async () => {
    setup({ aiFails: true });
    await userEvent.click(await screen.findByRole("button", { name: "Explain with AI" }));
    expect(await screen.findByText("Rate limited.")).toBeInTheDocument();
  });

  it("shows a quiet hint instead of a button when AI is off", async () => {
    setup({ aiAvailable: false });
    expect(await screen.findByText(/Set ANTHROPIC_API_KEY/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Explain with AI" })).toBeNull();
  });
});
