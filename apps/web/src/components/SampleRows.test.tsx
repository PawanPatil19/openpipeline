import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { GraphNode } from "../lib/api";
import { SampleRows } from "./SampleRows";

const model: GraphNode = {
  id: "model.p.orders",
  name: "orders",
  kind: "model",
  description: "",
  materialized: "table",
  path: "models/orders.sql",
  owner: null,
};

function setup(node: GraphNode, responses: Record<string, unknown>) {
  const fetchMock = vi.fn(async (url: string) => {
    const body = responses[url];
    return new Response(JSON.stringify(body ?? { detail: "not found" }), {
      status: body ? 200 : 404,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SampleRows node={node} />
    </QueryClientProvider>,
  );
  return fetchMock;
}

const okStatus = { duckdb: true, install_hint: null, sample_data: "sample_data", tables: [] };
const sampleUrl = "/api/models/model.p.orders/sample?limit=20";

afterEach(() => vi.unstubAllGlobals());

describe("SampleRows", () => {
  it("loads rows only when expanded", async () => {
    const fetchMock = setup(model, {
      "/api/sample/status": okStatus,
      [sampleUrl]: {
        columns: ["order_id", "status"],
        rows: [
          [1, "completed"],
          [2, null],
        ],
        row_limit: 20,
        error: null,
      },
    });
    const toggle = await screen.findByRole("button", { name: /Sample rows/ });
    expect(fetchMock.mock.calls.map((c) => c[0])).not.toContain(sampleUrl);
    await userEvent.click(toggle);
    expect(await screen.findByRole("columnheader", { name: "order_id" })).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("explains which data to add when a table is missing", async () => {
    setup(model, {
      "/api/sample/status": okStatus,
      [sampleUrl]: {
        columns: [],
        rows: [],
        row_limit: 20,
        error: {
          message: "stg_orders reads raw.orders, but there is no sample data for it.",
          model: "stg_orders",
          missing_table: "raw.orders",
        },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: /Sample rows/ }));
    expect(await screen.findByText(/there is no sample data for it/)).toBeInTheDocument();
    expect(screen.getByText("sample_data/raw.orders.csv")).toBeInTheDocument();
  });

  it("shows an install hint when DuckDB is missing", async () => {
    setup(model, {
      "/api/sample/status": {
        duckdb: false,
        install_hint: "Install DuckDB to preview rows: pip install 'openpipeline[preview]'",
        sample_data: null,
        tables: [],
      },
    });
    expect(await screen.findByText(/openpipeline\[preview\]/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Sample rows/ })).not.toBeInTheDocument();
  });

  it("renders nothing for sources", () => {
    const fetchMock = setup(
      { ...model, kind: "source", id: "source.p.raw.orders" },
      { "/api/sample/status": okStatus },
    );
    expect(screen.queryByText("Sample rows")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
