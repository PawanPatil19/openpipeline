import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { GraphView } from "./components/GraphView";
import { ProposalsPanel } from "./components/ProposalsPanel";
import { ReviewLegend } from "./components/ReviewLegend";
import { RulesPanel } from "./components/RulesPanel";
import { SearchBox } from "./components/SearchBox";
import { StoryPanel } from "./components/StoryPanel";
import { TokenDialog } from "./components/TokenDialog";
import { api } from "./lib/api";
import { promptForToken } from "./lib/auth";
import { ColumnFocusContext } from "./lib/columnFocus";
import { DEMO_COMMAND, isDemo } from "./lib/demo";
import { useAuth } from "./lib/useAuth";
import { useGraphFocus } from "./lib/useGraphFocus";

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
  const auth = useAuth();
  const [tab, setTab] = useState<Tab>("model");
  const showModelTab = useCallback(() => setTab("model"), []);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const preview = useQuery({
    queryKey: ["preview", reviewId],
    queryFn: () => api.preview(reviewId as string),
    enabled: reviewId !== null,
  });
  const reviewing = reviewId !== null && preview.data ? preview.data : null;
  const reviewTitle = proposals.data?.find((p) => p.id === reviewId)?.title ?? "proposal";
  const shownGraph = reviewing ? reviewing.graph : graph.data;
  const { selected, setSelected, focus, highlightIds, columnFocus, pickHit } = useGraphFocus(
    shownGraph,
    showModelTab,
  );

  const pendingCount = proposals.data?.filter((p) => p.status === "pending").length ?? 0;

  return (
    <div className="app">
      {isDemo() && (
        <div className="demo-banner" role="note">
          <span>
            Read-only demo. Run <code>{DEMO_COMMAND}</code> to try it for real.
          </span>
          <a href="/">About OpenPipeline</a>
        </div>
      )}
      <header className="topbar">
        <span className="brand">OpenPipeline</span>
        {project.data && (
          <span className="muted">
            {project.data.name} · {project.data.model_count} models · {project.data.source_count}{" "}
            sources · read from {project.data.loaded_from}
          </span>
        )}
        <SearchBox onPick={pickHit} />
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

      {auth.mode === "off" && (
        <div className="banner" role="note">
          Read-only: this server does not allow edits, accepting proposals, comments, or AI calls.
        </div>
      )}
      {auth.mode === "token" && auth.tokenValid === false && (
        <div className="banner" role="note">
          Changes need a write token.{" "}
          <button type="button" className="link-button" onClick={promptForToken}>
            Enter token
          </button>
        </div>
      )}
      <TokenDialog />

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
              highlightIds={highlightIds}
              focus={focus}
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
            <ColumnFocusContext.Provider value={columnFocus}>
              <StoryPanel key={selected.id} node={selected} />
            </ColumnFocusContext.Provider>
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
