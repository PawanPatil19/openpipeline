import type { BusinessStory, GraphNode } from "../lib/api";
import { Term, TermText } from "./Term";

/**
 * A story in the business's own words. Model and column names, SQL-ish steps and filters
 * are tucked behind "Show details" so a reader who does not know SQL never has to see them.
 */
export function BusinessStoryView({ node, story }: { node: GraphNode; story: BusinessStory }) {
  const terms = story.terms_used;
  const tech = story.technical;
  const defined = terms.filter((t) => t.definition);
  const columns = story.columns.filter((c) => c.name !== "*");
  const allColumns = story.columns.filter((c) => c.name === "*");

  return (
    <div className="business">
      <p>
        <TermText text={story.summary} terms={terms} />
      </p>
      {tech.parse_error && (
        <p className="warn">Some of the SQL could not be read, so this story may be incomplete.</p>
      )}

      {story.steps.length > 0 && (
        <>
          <h3>How it is built</h3>
          <ol className="steps">
            {story.steps.map((s) => (
              <li key={s}>
                <TermText text={s} terms={terms} />
              </li>
            ))}
          </ol>
        </>
      )}

      {story.filters.length > 0 && (
        <>
          <h3>Only rows where</h3>
          <ul className="steps">
            {story.filters.map((f) => (
              <li key={f}>
                <TermText text={f} terms={terms} />
              </li>
            ))}
          </ul>
        </>
      )}

      {(columns.length > 0 || allColumns.length > 0) && (
        <>
          <h3>What you get</h3>
          <table className="columns columns--business">
            <tbody>
              {columns.map((c) => (
                <tr key={c.name}>
                  <th scope="row">
                    <Term label={c.label} definition={c.definition} />
                  </th>
                  <td>
                    <TermText text={c.meaning} terms={terms} />
                  </td>
                </tr>
              ))}
              {allColumns.map((c) => (
                <tr key={c.name}>
                  <th scope="row">{c.label}</th>
                  <td>
                    <TermText text={c.meaning} terms={terms} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {defined.length > 0 && (
        <>
          <h3>Words used</h3>
          <dl className="words">
            {defined.map((t) => (
              <div key={t.name} className="words__item">
                <dt>{t.label}</dt>
                <dd>{t.definition}</dd>
              </div>
            ))}
          </dl>
        </>
      )}

      <details className="details">
        <summary>Show details</summary>
        <dl className="details__facts">
          <div className="details__fact">
            <dt>Name</dt>
            <dd>
              <code>{story.model}</code>
              {node.path && <code className="muted"> · {node.path}</code>}
            </dd>
          </div>
          {tech.reads_from.length > 0 && (
            <div className="details__fact">
              <dt>Built from</dt>
              <dd>
                {tech.reads_from.map((r) => (
                  <code key={r} className="chip-code">
                    {r}
                  </code>
                ))}
              </dd>
            </div>
          )}
          {tech.grain.length > 0 && (
            <div className="details__fact">
              <dt>One row per</dt>
              <dd>
                {tech.grain.map((g) => (
                  <code key={g} className="chip-code">
                    {g}
                  </code>
                ))}
              </dd>
            </div>
          )}
        </dl>

        {tech.steps.length > 0 && (
          <>
            <h4>Steps</h4>
            <ol className="steps">
              {tech.steps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          </>
        )}
        {tech.filters.length > 0 && (
          <>
            <h4>Filters</h4>
            <ul className="steps">
              {tech.filters.map((f) => (
                <li key={f}>
                  <code>{f}</code>
                </li>
              ))}
            </ul>
          </>
        )}
        {tech.columns.length > 0 && (
          <>
            <h4>Columns</h4>
            <table className="columns">
              <tbody>
                {tech.columns.map((c) => (
                  <tr key={c.name}>
                    <th scope="row">{c.name}</th>
                    <td className="muted">
                      {c.how}
                      {c.from_step ? ` · in step ${c.from_step}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </details>
    </div>
  );
}
