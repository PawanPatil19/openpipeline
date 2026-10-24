import { useQuery } from "@tanstack/react-query";
import { api, type GraphNode } from "../lib/api";

/** The "Business rules" section of the model panel. Renders nothing when there are none. */
export function ModelRules({ node }: { node: GraphNode }) {
  const rules = useQuery({
    queryKey: ["model-rules", node.id],
    queryFn: () => api.modelRules(node.id),
  });
  if (!rules.data || rules.data.length === 0) return null;

  return (
    <>
      <h3>Business rules</h3>
      <ul className="model-rules">
        {rules.data.map(({ rule, columns }) => (
          <li key={rule.id}>
            <strong>{rule.name}</strong>
            {rule.owner && <span className="muted"> · owner: {rule.owner}</span>}
            {columns.length > 0 && (
              <span className="muted">
                {" "}
                · applies to {columns.length === 1 ? "column" : "columns"}{" "}
                <code>{columns.join(", ")}</code>
              </span>
            )}
            {rule.description && <p>{rule.description}</p>}
          </li>
        ))}
      </ul>
    </>
  );
}
