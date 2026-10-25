import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { BusinessStory, GraphNode } from "../lib/api";
import { WORDS_MODE_KEY } from "../lib/wordsMode";
import { GlossaryPanel } from "./GlossaryPanel";
import { StoryPanel } from "./StoryPanel";
import { Term, TermText } from "./Term";

const node: GraphNode = {
  id: "model.shop.customers",
  name: "customers",
  kind: "model",
  description: "",
  materialized: "table",
  path: "models/customers.sql",
  owner: null,
};

const terms = [
  { name: "customer_id", label: "Customer", definition: "The person who placed the order." },
  { name: "amount", label: "Amount paid", definition: "Money received, in dollars." },
];

const business: BusinessStory = {
  model: "customers",
  title: "Customers",
  definition: "",
  summary: "Customers is built from Cleaned orders into one row per Customer.",
  reads_from: [{ name: "stg_orders", label: "Cleaned orders" }],
  grain: ["Customer"],
  columns: [
    {
      name: "customer_id",
      label: "Customer",
      meaning: "Comes straight from Cleaned orders",
      definition: terms[0]?.definition ?? null,
    },
    {
      name: "lifetime_value",
      label: "Lifetime value",
      meaning: "The total of Amount paid",
      definition: null,
    },
  ],
  steps: ["Final result: starts with Cleaned orders, rolls up to one row per Customer."],
  filters: ["Order status is not 'Customer'"],
  terms_used: terms,
  technical: {
    model: "customers",
    description: "",
    summary: "customers is built from stg_orders into one row per customer_id.",
    steps: [
      "Reads stg_orders.",
      "Final result: takes rows from stg_orders, rolls up to one row per customer_id.",
    ],
    reads_from: ["stg_orders"],
    columns: [
      { name: "customer_id", how: "passed through from stg_orders", from_step: null },
      { name: "lifetime_value", how: "the total of amount", from_step: "totals" },
    ],
    filters: ["status is not 'test'"],
    grain: ["customer_id"],
    parse_error: null,
  },
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function setup(options: { businessFails?: boolean } = {}) {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      if (url.endsWith("/business-story")) {
        return options.businessFails ? json({ detail: "No model" }, 404) : json(business);
      }
      if (url.endsWith("/story")) return json(business.technical);
      if (url.endsWith("/impact"))
        return json({ model: "customers", upstream: [], downstream: [] });
      if (url.endsWith("/rules") || url.endsWith("/columns")) return json([]);
      if (url === "/api/ai") return json({ available: false, model: null, reason: null });
      if (url === "/api/sample/status")
        return json({ duckdb: false, install_hint: null, sample_data: null, tables: [] });
      if (url === "/api/glossary")
        return json({
          terms: [
            {
              name: "customer_id",
              label: "Customer",
              definition: "Who orders.",
              aliases: ["user_id"],
              origin: "glossary",
            },
            { name: "orders", label: "Orders", definition: "", aliases: [], origin: "meta" },
          ],
          warnings: ["openpipeline.yml: 'x' is used more than once"],
        });
      if (url.startsWith("/api/models/"))
        return json({
          unique_id: node.id,
          name: "customers",
          kind: "model",
          description: "",
          path: node.path,
          columns: [],
        });
      return json({ detail: "not found" }, 404);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StoryPanel node={node} />
    </QueryClientProvider>,
  );
  return { urls };
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("words toggle", () => {
  it("starts technical and does not ask for the business story", async () => {
    const { urls } = setup();
    expect(
      await screen.findByText("customers is built from stg_orders into one row per customer_id."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Technical" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Business words" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(urls.some((u) => u.endsWith("/business-story"))).toBe(false);
  });

  it("switches to business words and remembers the choice", async () => {
    setup();
    await userEvent.click(await screen.findByRole("button", { name: "Business words" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Customers" })).toBeInTheDocument();
    expect(screen.getByText(/Customers is built from Cleaned orders/)).toBeInTheDocument();
    // The technical story and the file path are gone from view.
    expect(
      screen.queryByText("customers is built from stg_orders into one row per customer_id."),
    ).toBeNull();
    expect(screen.queryByText("models/customers.sql", { selector: "code.muted" })).toBeNull();
    expect(localStorage.getItem(WORDS_MODE_KEY)).toBe("business");

    await userEvent.click(screen.getByRole("button", { name: "Technical" }));
    expect(
      await screen.findByText("customers is built from stg_orders into one row per customer_id."),
    ).toBeInTheDocument();
    expect(localStorage.getItem(WORDS_MODE_KEY)).toBe("technical");
  });

  it("opens in business words when that was the last choice", async () => {
    localStorage.setItem(WORDS_MODE_KEY, "business");
    setup();
    expect(await screen.findByText(/Customers is built from Cleaned orders/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Business words" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("still works when storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    setup();
    await userEvent.click(await screen.findByRole("button", { name: "Business words" }));
    expect(await screen.findByText(/Customers is built from Cleaned orders/)).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("shows an error when the business story cannot be loaded", async () => {
    localStorage.setItem(WORDS_MODE_KEY, "business");
    setup({ businessFails: true });
    expect(await screen.findByText(/Could not explain this model: No model/)).toBeInTheDocument();
  });
});

describe("business story", () => {
  beforeEach(() => localStorage.setItem(WORDS_MODE_KEY, "business"));

  it("shows columns as a label and a meaning, without technical names", async () => {
    setup();
    const [table = document.body] = await screen.findAllByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(within(rows[0] as HTMLElement).getByText("Customer")).toBeInTheDocument();
    expect(
      within(rows[0] as HTMLElement).getByText("Comes straight from Cleaned orders"),
    ).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Lifetime value")).toBeInTheDocument();
    expect(within(table).queryByText("lifetime_value")).toBeNull();
  });

  it("tucks technical names behind a collapsed Show details", async () => {
    setup();
    const summary = await screen.findByText("Show details");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details?.open).toBe(false);

    await userEvent.click(summary);
    expect(details?.open).toBe(true);
    const inside = within(details as HTMLElement);
    expect(inside.getByText("customers", { selector: "code" })).toBeInTheDocument();
    expect(inside.getByText("lifetime_value")).toBeInTheDocument();
    expect(inside.getByText("status is not 'test'")).toBeInTheDocument();
    expect(inside.getByText(/Reads stg_orders\./)).toBeInTheDocument();

    await userEvent.click(summary);
    expect(details?.open).toBe(false);
  });

  it("lists the words used with their definitions", async () => {
    setup();
    const heading = await screen.findByRole("heading", { name: "Words used" });
    const list = heading.nextElementSibling as HTMLElement;
    expect(within(list).getByText("Amount paid")).toBeInTheDocument();
    expect(within(list).getByText("Money received, in dollars.")).toBeInTheDocument();
  });
});

describe("definitions on hover and focus", () => {
  it("gives a term a focusable button that describes itself with the definition", async () => {
    render(<Term label="Customer" definition="The person who ordered." />);
    const button = screen.getByRole("button", { name: "Customer" });
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("The person who ordered.");
    expect(button).toHaveAttribute("aria-describedby", tip.id);
    expect(tip).not.toHaveClass("term__tip--open");

    await userEvent.tab();
    expect(button).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(tip).toHaveClass("term__tip--open");
    await userEvent.keyboard("{Escape}");
    expect(tip).not.toHaveClass("term__tip--open");
  });

  it("is plain text when there is no definition", () => {
    render(<Term label="Lifetime value" definition={null} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Lifetime value")).toBeInTheDocument();
  });

  it("marks labels inside a sentence, but never inside a quoted value", () => {
    render(
      <p data-testid="p">
        <TermText
          text="Customer is present and status is 'Customer' for the Amount paid, Customers too"
          terms={terms}
        />
      </p>,
    );
    const p = screen.getByTestId("p");
    expect(
      within(p)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Customer", "Amount paid"]);
    // The quoted value and the longer word "Customers" are plain text.
    expect(p.textContent).toContain("status is 'Customer' for the");
    expect(p.textContent).toContain(", Customers too");
  });

  it("prefers the longest label and ignores terms without a definition", () => {
    const longer = [
      { name: "a", label: "Order", definition: "One purchase." },
      { name: "b", label: "Order date", definition: "When it was placed." },
      { name: "c", label: "Plain", definition: "" },
    ];
    render(
      <p data-testid="p">
        <TermText text="Order date and Order and Plain" terms={longer} />
      </p>,
    );
    const buttons = within(screen.getByTestId("p")).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Order date", "Order"]);
  });
});

describe("GlossaryPanel", () => {
  it("lists terms with names, aliases, definitions and warnings", async () => {
    setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <GlossaryPanel />
      </QueryClientProvider>,
    );
    const panel = await screen.findByRole("region", { name: "Glossary" });
    expect(await within(panel).findByRole("heading", { name: "Customer" })).toBeInTheDocument();
    expect(within(panel).getByText("Who orders.")).toBeInTheDocument();
    expect(within(panel).getByText("customer_id")).toBeInTheDocument();
    expect(within(panel).getByText(/also "user_id"/)).toBeInTheDocument();
    expect(within(panel).getByText(/from dbt meta/)).toBeInTheDocument();
    expect(within(panel).getByText("No definition yet.")).toBeInTheDocument();
    expect(within(panel).getByRole("status")).toHaveTextContent("used more than once");
  });
});
