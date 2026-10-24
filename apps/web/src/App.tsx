import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { GraphView } from "./components/GraphView";
import { ProposalsPanel } from "./components/ProposalsPanel";
import { StoryPanel } from "./components/StoryPanel";
import { api, type GraphNode } from "./lib/api";

type Tab = "model" | "proposals";

export function App() {
  const project = useQuery({ queryKey: ["project"], queryFn: api.project });
  const graph = useQuery({ queryKey: ["graph"], queryFn: api.graph });
  const proposals = useQuery({ queryKey: ["proposals"], queryFn: api.proposals });
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [tab, setTab] = useState<Tab>("model");

  const pendingCount = proposals.data?.filter((p) => p.status === "pending").length ?? 0;

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">OpenPipeline</span>
        {project.data && (
          <span className="muted">
            {project.data.name} · {project.data.model_count} models · {project.data.source_count}{" "}
            sources · read from {project.data.loaded_from}
          </span>
        )}
        <nav className="tabs" aria-label="Side panel">
          <button type="button" aria-pressed={tab === "model"} onClick={() => setTab("model")}>
            Model
          </button>
          <button
            type="button"
            aria-pressed={tab === "proposals"}
            onClick={() => setTab("proposals")}
          >
            Proposals{pendingCount > 0 && <span className="count">{pendingCount}</span>}
          </button>
        </nav>
      </header>

      {project.data && project.data.warnings.length > 0 && (
        <div className="banner" role="status">
          {project.data.warnings.length} warning(s): {project.data.warnings.join("; ")}
        </div>
      )}

      <main className="layout">
        <div className="canvas">
          {graph.isPending && <p className="center muted">Loading graph…</p>}
          {graph.isError && (
            <p className="center error">Could not load the project: {graph.error.message}</p>
          )}
          {graph.data && (
            <GraphView
              graph={graph.data}
              selectedId={selected?.id ?? null}
              onSelect={(n) => {
                setSelected(n);
                if (n) setTab("model");
              }}
            />
          )}
        </div>
        <aside className="side">
          {tab === "proposals" ? (
            <ProposalsPanel />
          ) : selected ? (
            <StoryPanel key={selected.id} node={selected} />
          ) : (
            <section className="panel">
              <h2>Pick a model</h2>
              <p className="muted">
                Click any box in the graph to see what it does in plain English, which columns it
                produces, and what depends on it.
              </p>
            </section>
          )}
        </aside>
      </main>
    </div>
  );
}
