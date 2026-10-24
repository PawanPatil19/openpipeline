import { useQuery } from "@tanstack/react-query";
import { api, type GraphNode } from "../lib/api";

export function StoryPanel({ node }: { node: GraphNode }) {
  const story = useQuery({ queryKey: ["story", node.id], queryFn: () => api.story(node.id) });
  const impact = useQuery({ queryKey: ["impact", node.id], queryFn: () => api.impact(node.id) });

  return (
    <section className="panel" aria-label={`About ${node.name}`}>
      <header className="panel__header">
        <span className={`badge badge--${node.kind}`}>{node.kind}</span>
        <h2>{node.name}</h2>
        {node.path && <code className="muted">{node.path}</code>}
        {node.owner && <p className="muted">Owner: {node.owner}</p>}
      </header>

      {story.isPending && <p className="muted">Reading the SQL…</p>}
      {story.isError && (
        <p className="error">Could not explain this model: {story.error.message}</p>
      )}
      {story.data && (
        <>
          {story.data.description && <p className="lede">{story.data.description}</p>}
          <p>{story.data.summary}</p>
          {story.data.parse_error && (
            <p className="warn">Some of the SQL could not be read: {story.data.parse_error}</p>
          )}
          {story.data.steps.length > 0 && (
            <>
              <h3>How it is built</h3>
              <ol className="steps">
                {story.data.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
            </>
          )}
          {story.data.columns.length > 0 && (
            <>
              <h3>Columns</h3>
              <table className="columns">
                <tbody>
                  {story.data.columns.map((c) => (
                    <tr key={c.name}>
                      <th scope="row">{c.name}</th>
                      <td>{c.how}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}

      {impact.data && impact.data.downstream.length > 0 && (
        <>
          <h3>If this changes, these are affected</h3>
          <ul className="chips">
            {impact.data.downstream.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
