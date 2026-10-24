import { useQuery } from "@tanstack/react-query";
import { api, type ColumnRefView, type GraphNode } from "../lib/api";
import { useColumnFocus } from "../lib/columnFocus";
import "./search-lineage.css";

function RefList({ refs, empty }: { refs: ColumnRefView[]; empty: string }) {
  const { select } = useColumnFocus();
  if (refs.length === 0) return <p className="muted">{empty}</p>;
  return (
    <ul className="collineage__list">
      {refs.map((r) => (
        <li key={`${r.node_id}:${r.column}`}>
          <button
            type="button"
            className="collineage__ref"
            onClick={() => select({ nodeId: r.node_id, column: r.column })}
          >
            <span className={`badge badge--${r.kind}`}>{r.kind}</span>
            {r.node}.{r.column}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Pick a column of a model and see where it comes from and where it is used. */
export function ColumnLineage({ node }: { node: GraphNode }) {
  const { selection, select } = useColumnFocus();
  const columns = useQuery({ queryKey: ["columns", node.id], queryFn: () => api.columns(node.id) });
  const current = selection?.nodeId === node.id ? selection.column : null;
  const lineage = useQuery({
    queryKey: ["column-lineage", node.id, current],
    queryFn: () => api.columnLineage(node.id, current as string),
    enabled: current !== null,
  });

  if (!columns.data || columns.data.length === 0) return null;

  return (
    <section aria-label="Column lineage">
      <h3>Column lineage</h3>
      <p className="muted">
        Pick a column to see where it comes from and where it is used. The graph shows only the
        models on its path.
      </p>
      <ul className="collineage__columns">
        {columns.data.map((c) => (
          <li key={c.name}>
            <button
              type="button"
              aria-pressed={c.name === current}
              title={c.description || undefined}
              onClick={() =>
                select(c.name === current ? null : { nodeId: node.id, column: c.name })
              }
            >
              {c.name}
            </button>
          </li>
        ))}
      </ul>
      {current && lineage.isPending && <p className="muted">Tracing {current}…</p>}
      {current && lineage.isError && (
        <p className="error">Could not trace this column: {lineage.error.message}</p>
      )}
      {current && lineage.data && (
        <>
          <p className="collineage__subhead">{current} comes from</p>
          <RefList
            refs={lineage.data.upstream}
            empty="Nothing upstream. This column starts here, or its source could not be read."
          />
          <p className="collineage__subhead">{current} is used by</p>
          <RefList refs={lineage.data.downstream} empty="No other model uses this column." />
        </>
      )}
    </section>
  );
}
