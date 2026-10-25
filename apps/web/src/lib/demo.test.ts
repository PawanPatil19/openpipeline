import { ApiError, api, type Graph } from "./api";
import { demoUrl, searchGraph } from "./demo";

const graph: Graph = {
  nodes: [
    {
      id: "model.p.customers",
      name: "customers",
      kind: "model",
      description: "Every buyer",
      materialized: null,
      path: null,
      owner: null,
    },
    {
      id: "model.p.orders",
      name: "orders",
      kind: "model",
      description: "One row per customer order",
      materialized: null,
      path: null,
      owner: null,
    },
    {
      id: "source.p.raw.items",
      name: "items",
      kind: "source",
      description: "",
      materialized: null,
      path: null,
      owner: null,
    },
  ],
  edges: [],
};

describe("demo mode", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_DEMO", "1");
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("maps GET paths to the exported JSON and drops the query string", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ model: "customers" })));
    vi.stubGlobal("fetch", fetchMock);
    expect(demoUrl("/api/models/a%20b/sample?limit=20")).toBe("/data/api/models/a%20b/sample.json");
    await api.story("model.p.customers");
    expect(fetchMock).toHaveBeenCalledWith("/data/api/models/model.p.customers/story.json");
    await api.sample("model.p.customers");
    expect(fetchMock).toHaveBeenLastCalledWith("/data/api/models/model.p.customers/sample.json");
  });

  it("never calls /api/auth: the demo reports open writes locally and refuses at write time", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    expect(await api.auth()).toEqual({ writes: "open", token_valid: null });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("searches the graph in the browser", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(graph)));
    vi.stubGlobal("fetch", fetchMock);
    const hits = await api.search("customer");
    expect(hits.map((h) => h.name)).toEqual(["customers", "orders"]);
    expect(hits[0]).toMatchObject({ kind: "model", node_id: "model.p.customers", column: null });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(searchGraph(graph, "  ", 5)).toEqual([]);
  });

  it("refuses every write without calling the network", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const writes = [
      api.saveDocs("customers", { description: "x" }),
      api.aiExplain("customers"),
      api.decide("abc", "accepted"),
      api.comment("abc", "hi"),
    ];
    for (const write of writes) {
      await expect(write).rejects.toBeInstanceOf(ApiError);
      await expect(write).rejects.toThrow(/read-only demo/);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
