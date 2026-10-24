import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type DocsUpdate, type GraphNode } from "../lib/api";
import { AiExplain } from "./AiExplain";
import { ColumnLineage } from "./ColumnLineage";
import { ModelRules } from "./ModelRules";
import { SampleRows } from "./SampleRows";

export function StoryPanel({ node }: { node: GraphNode }) {
  const queryClient = useQueryClient();
  const isModel = node.kind === "model";
  const story = useQuery({ queryKey: ["story", node.id], queryFn: () => api.story(node.id) });
  const impact = useQuery({ queryKey: ["impact", node.id], queryFn: () => api.impact(node.id) });
  const model = useQuery({
    queryKey: ["model", node.id],
    queryFn: () => api.model(node.id),
    enabled: isModel,
  });
  const aiStatus = useQuery({ queryKey: ["ai"], queryFn: api.aiStatus, enabled: isModel });

  // null means "not editing".
  const [descDraft, setDescDraft] = useState<string | null>(null);
  const [colDrafts, setColDrafts] = useState<Record<string, string> | null>(null);

  const save = useMutation({
    mutationFn: (update: DocsUpdate) => api.saveDocs(node.id, update),
    onSuccess: async () => {
      await Promise.all(
        [["graph"], ["story", node.id], ["model", node.id], ["impact", node.id]].map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
      );
    },
  });

  const documented = model.data?.description ?? "";
  const documentedColumns: Record<string, string> = Object.fromEntries(
    (model.data?.columns ?? []).map((c) => [c.name, c.description]),
  );
  const how = new Map((story.data?.columns ?? []).map((c) => [c.name, c.how]));
  const columnNames = [
    ...(story.data?.columns ?? []).map((c) => c.name).filter((n) => n !== "*"),
    ...Object.keys(documentedColumns).filter((n) => !how.has(n)),
  ];

  const saveDescription = () => {
    if (descDraft === null) return;
    save.mutate({ description: descDraft }, { onSuccess: () => setDescDraft(null) });
  };

  const saveColumns = () => {
    if (colDrafts === null) return;
    const changed = Object.fromEntries(
      Object.entries(colDrafts).filter(([name, text]) => text !== (documentedColumns[name] ?? "")),
    );
    if (Object.keys(changed).length === 0) {
      setColDrafts(null);
      return;
    }
    save.mutate({ columns: changed }, { onSuccess: () => setColDrafts(null) });
  };

  const startColumnEdit = (notes: Record<string, string> = {}) =>
    setColDrafts({
      ...Object.fromEntries(columnNames.map((n) => [n, documentedColumns[n] ?? ""])),
      ...colDrafts,
      ...notes,
    });

  return (
    <section className="panel" aria-label={`About ${node.name}`}>
      <header className="panel__header">
        <span className={`badge badge--${node.kind}`}>{node.kind}</span>
        <h2>{node.name}</h2>
        {node.path && <code className="muted">{node.path}</code>}
        {node.owner && <p className="muted">Owner: {node.owner}</p>}
      </header>

      {isModel &&
        (descDraft !== null ? (
          <div className="docs-edit">
            <textarea
              aria-label="Description"
              value={descDraft}
              onChange={(e) => setDescDraft(e.target.value)}
            />
            <div className="docs-actions">
              <button
                type="button"
                className="primary"
                disabled={save.isPending}
                onClick={saveDescription}
              >
                Save description
              </button>
              <button type="button" onClick={() => setDescDraft(null)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div>
            {documented ? (
              <p className="lede">{documented}</p>
            ) : (
              <p className="muted">No description yet.</p>
            )}
            {model.data && (
              <button
                type="button"
                className="link-button"
                onClick={() => setDescDraft(documented)}
              >
                Edit description
              </button>
            )}
          </div>
        ))}
      {!isModel && story.data?.description && <p className="lede">{story.data.description}</p>}
      {save.isError && <p className="error">Could not save: {save.error.message}</p>}

      {isModel && aiStatus.data?.available && (
        <AiExplain
          name={node.id}
          columnNames={columnNames}
          onUseDescription={setDescDraft}
          onUseColumns={startColumnEdit}
        />
      )}

      {story.isPending && <p className="muted">Reading the SQL…</p>}
      {story.isError && (
        <p className="error">Could not explain this model: {story.error.message}</p>
      )}
      {story.data && (
        <>
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
          {columnNames.length > 0 && (
            <>
              <div className="section-head">
                <h3>Columns</h3>
                {isModel && colDrafts === null && model.data && (
                  <button type="button" className="link-button" onClick={() => startColumnEdit()}>
                    Edit column descriptions
                  </button>
                )}
              </div>
              <table className="columns">
                <tbody>
                  {columnNames.map((name) => (
                    <tr key={name}>
                      <th scope="row">{name}</th>
                      <td>
                        {colDrafts !== null ? (
                          <div className="docs-edit">
                            <textarea
                              aria-label={`Description for ${name}`}
                              value={colDrafts[name] ?? ""}
                              onChange={(e) =>
                                setColDrafts({ ...colDrafts, [name]: e.target.value })
                              }
                            />
                          </div>
                        ) : (
                          documentedColumns[name] && <p>{documentedColumns[name]}</p>
                        )}
                        {how.get(name) && <span className="muted">{how.get(name)}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {colDrafts !== null && (
                <div className="docs-actions">
                  <button
                    type="button"
                    className="primary"
                    disabled={save.isPending}
                    onClick={saveColumns}
                  >
                    Save column descriptions
                  </button>
                  <button type="button" onClick={() => setColDrafts(null)}>
                    Cancel
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}

      <ModelRules node={node} />
      <ColumnLineage node={node} />
      <SampleRows node={node} />

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

      {isModel && aiStatus.data && !aiStatus.data.available && aiStatus.data.reason && (
        <footer className="panel__footer muted">
          AI explanations are off. {aiStatus.data.reason}
        </footer>
      )}
    </section>
  );
}
