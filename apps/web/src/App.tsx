import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { GraphView } from "./components/GraphView";
import { ProposalsPanel } from "./components/ProposalsPanel";
import { ReviewLegend } from "./components/ReviewLegend";
import { RulesPanel } from "./components/RulesPanel";
import { StoryPanel } from "./components/StoryPanel";
import { api, type GraphNode } from "./lib/api";

type Tab = "model" | "rules" | "proposals";

export function App() {
  const project = useQuery({ queryKey: ["project"], queryFn: api.project });
  const graph = useQuery({ queryKey: ["graph"], queryFn: api.graph });
  const proposals = useQuery({ queryKey: ["proposals"], queryFn: api.proposals });
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });
  const ruleModels = useMemo(
    () => new Set(rules.data?.rules.flatMap((r) => r.applies_to.map((l) => l.model)) ?? []),
    [rules.data],
  );
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [tab, setTab] = useState<Tab>("model");
  const [reviewId, setReviewId] = useState<string | null>(null);
  const preview = useQuery({
    queryKey: ["preview", reviewId],
    queryFn: () => api.preview(reviewId as string),
    enabled: reviewId !== null,
  });
  const reviewing = reviewId !== null && preview.data ? preview.data : null;
  const reviewTitle = proposals.data?.find((p) => p.id === reviewId)?.title ?? "proposal";
  const shownGraph = reviewing ? reviewing.graph : graph.data;

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
          <button type="button" aria-pressed={tab === "rules"} onClick={() => setTab("rules")}>
            Rules
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
          {shownGraph && (
            <GraphView
              graph={shownGraph}
              statuses={reviewing?.node_statuses}
              selectedId={selected?.id ?? null}
              ruleModels={ruleModels}
              onSelect={(n) => {
                setSelected(n);
                if (n) setTab("model");
              }}
            />
          )}
          {reviewing && <ReviewLegend title={reviewTitle} onExit={() => setReviewId(null)} />}
        </div>
        <aside className="side">
          {tab === "proposals" ? (
            <ProposalsPanel
              reviewingId={reviewId}
              onReview={(id) => {
                setReviewId(id);
                setSelected(null);
              }}
            />
          ) : tab === "rules" ? (
            <RulesPanel
              onSelectModel={(name) => {
                const node = graph.data?.nodes.find((n) => n.name === name);
                if (node) {
                  setSelected(node);
                  setTab("model");
                }
              }}
            />
          ) : selected && reviewing?.node_statuses[selected.id] === "added" ? (
            <section className="panel" aria-label={`About ${selected.name}`}>
              <h2>{selected.name}</h2>
              <p className="muted">
                This model is new in the proposal, so there is no story yet. Accept the proposal to
                read it here. Its SQL is in the diff under Proposals.
              </p>
            </section>
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
