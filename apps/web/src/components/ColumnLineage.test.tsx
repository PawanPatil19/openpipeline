import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { GraphNode } from "../lib/api";
import { ColumnFocusContext, type ColumnSelection } from "../lib/columnFocus";
import { ColumnLineage } from "./ColumnLineage";

const orders: GraphNode = {
  id: "model.shop.orders",
  name: "orders",
  kind: "model",
  description: "",
  materialized: null,
  path: null,
  owner: null,
};

const responses: Record<string, unknown> = {
  "/api/models/model.shop.orders/columns": [
    { name: "order_id", description: "", tests: [], upstream: [] },
    { name: "amount", description: "Dollars paid.", tests: [], upstream: [] },
  ],
  "/api/models/model.shop.orders/columns/amount/lineage": {
    model: "orders",
    column: "amount",
    upstream: [
      { node_id: "model.shop.stg_payments", node: "stg_payments", kind: "model", column: "amount" },
      {
        node_id: "source.shop.raw.payments",
        node: "raw.payments",
        kind: "source",
        column: "amount",
      },
    ],
    downstream: [
      {
        node_id: "model.shop.customers",
        node: "customers",
        kind: "model",
        column: "lifetime_value",
      },
    ],
  },
  "/api/models/model.shop.orders/columns/order_id/lineage": {
    model: "orders",
    column: "order_id",
    upstream: [],
    downstream: [],
  },
};

function Harness({ onSelect }: { onSelect: (s: ColumnSelection | null) => void }) {
  const [selection, setSelection] = useState<ColumnSelection | null>(null);
  return (
    <ColumnFocusContext.Provider
      value={{
        selection,
        select: (s) => {
          onSelect(s);
          setSelection(s);
        },
      }}
    >
      <ColumnLineage node={orders} />
    </ColumnFocusContext.Provider>
  );
}

function setup() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = responses[decodeURIComponent(url)];
      return new Response(JSON.stringify(body ?? { detail: "not found" }), {
        status: body ? 200 : 404,
      });
    }),
  );
  const onSelect = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness onSelect={onSelect} />
    </QueryClientProvider>,
  );
  return onSelect;
}

afterEach(() => vi.unstubAllGlobals());

describe("ColumnLineage", () => {
  it("lists columns, then shows where a column comes from and where it is used", async () => {
    const onSelect = setup();
    await userEvent.click(await screen.findByRole("button", { name: "amount" }));
    expect(onSelect).toHaveBeenCalledWith({ nodeId: "model.shop.orders", column: "amount" });

    expect(await screen.findByText("amount comes from")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /stg_payments\.amount/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /raw\.payments\.amount/ })).toBeInTheDocument();
    expect(screen.getByText("amount is used by")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /customers\.lifetime_value/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "amount" })).toHaveAttribute("aria-pressed", "true");
  });

  it("selects the column behind a lineage link", async () => {
    const onSelect = setup();
    await userEvent.click(await screen.findByRole("button", { name: "amount" }));
    await userEvent.click(await screen.findByRole("button", { name: /customers\.lifetime_value/ }));
    expect(onSelect).toHaveBeenLastCalledWith({
      nodeId: "model.shop.customers",
      column: "lifetime_value",
    });
  });

  it("clears the selection when the same column is clicked again", async () => {
    const onSelect = setup();
    const button = await screen.findByRole("button", { name: "amount" });
    await userEvent.click(button);
    await userEvent.click(button);
    expect(onSelect).toHaveBeenLastCalledWith(null);
    expect(screen.queryByText("amount comes from")).not.toBeInTheDocument();
  });

  it("explains an empty lineage in plain words", async () => {
    setup();
    await userEvent.click(await screen.findByRole("button", { name: "order_id" }));
    expect(await screen.findByText(/Nothing upstream/)).toBeInTheDocument();
    expect(screen.getByText("No other model uses this column.")).toBeInTheDocument();
  });
});
