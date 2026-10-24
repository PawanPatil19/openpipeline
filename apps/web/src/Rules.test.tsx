import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

const lifetimeValue = {
  id: "lifetime-value",
  name: "Lifetime value excludes refunds",
  description: "Refunds never count towards what a customer has paid.",
  owner: "growth-team",
  tags: ["finance"],
  applies_to: [
    { model: "customers", columns: ["lifetime_value"] },
    { model: "orders", columns: [] },
  ],
};

const responses: Record<string, unknown> = {
  "/api/project": {
    name: "jaffle_shop",
    root: "/p",
    loaded_from: "files",
    model_count: 2,
    source_count: 0,
    warnings: [],
  },
  "/api/graph": {
    nodes: ["orders", "customers"].map((name) => ({
      id: `model.jaffle_shop.${name}`,
      name,
      kind: "model",
      description: "",
      materialized: "table",
      path: `models/${name}.sql`,
      owner: null,
    })),
    edges: [{ source: "model.jaffle_shop.orders", target: "model.jaffle_shop.customers" }],
  },
  "/api/proposals": [],
  "/api/rules": {
    rules: [
      lifetimeValue,
      {
        id: "orphan",
        name: "Unlinked rule",
        description: "",
        owner: null,
        tags: [],
        applies_to: [],
      },
    ],
    warnings: [],
  },
  "/api/models/model.jaffle_shop.customers/rules": [
    { rule: lifetimeValue, columns: ["lifetime_value"] },
  ],
  "/api/models/model.jaffle_shop.orders/rules": [],
  "/api/models/model.jaffle_shop.customers/story": {
    model: "customers",
    description: "",
    summary: "One row per customer.",
    steps: [],
    reads_from: [],
    columns: [],
    filters: [],
    grain: [],
    parse_error: null,
  },
  "/api/models/model.jaffle_shop.customers/impact": {
    model: "customers",
    upstream: [],
    downstream: [],
  },
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

describe("Rules tab", () => {
  it("lists rules with owner, description, and linked models", async () => {
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Rules" }));
    const card = (await screen.findByText("Lifetime value excludes refunds")).closest("article");
    expect(card).not.toBeNull();
    const rule = within(card as HTMLElement);
    expect(rule.getByText(/Owner: growth-team/)).toBeInTheDocument();
    expect(rule.getByText(/Refunds never count/)).toBeInTheDocument();
    expect(rule.getByRole("button", { name: "customers (lifetime_value)" })).toBeInTheDocument();
    expect(rule.getByRole("button", { name: "orders" })).toBeInTheDocument();
    expect(screen.getByText(/No owner yet/)).toBeInTheDocument();
    expect(screen.getByText("Not linked to any model yet.")).toBeInTheDocument();
  });

  it("selects the model when a chip is clicked and shows its rules", async () => {
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Rules" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "customers (lifetime_value)" }),
    );

    const panel = await screen.findByRole("region", { name: "About customers" });
    expect(await within(panel).findByText("Business rules")).toBeInTheDocument();
    expect(within(panel).getByText("Lifetime value excludes refunds")).toBeInTheDocument();
    expect(within(panel).getByText("lifetime_value")).toBeInTheDocument();
  });

  it("marks graph nodes that implement a rule", async () => {
    renderApp();
    const badges = await screen.findAllByRole("img", { name: "Implements a business rule" });
    expect(badges).toHaveLength(2);
  });
});
