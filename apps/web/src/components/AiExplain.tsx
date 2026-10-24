import { useMutation } from "@tanstack/react-query";
import { api } from "../lib/api";

interface Props {
  /** Model id or name. */
  name: string;
  /** Columns that can take a note. Notes for other columns are ignored. */
  columnNames: string[];
  /** Puts text in the description editor. Nothing is saved until the person clicks Save. */
  onUseDescription: (text: string) => void;
  /** Puts notes in the column editor. Nothing is saved until the person clicks Save. */
  onUseColumns: (notes: Record<string, string>) => void;
}

export function AiExplain({ name, columnNames, onUseDescription, onUseColumns }: Props) {
  const explain = useMutation({
    mutationFn: (refresh: boolean) => api.aiExplain(name, refresh),
  });
  const result = explain.data;

  const useColumns = () => {
    if (!result) return;
    const notes = Object.fromEntries(
      result.columns
        .filter((c) => columnNames.includes(c.name))
        .map((c) => [c.name, c.description]),
    );
    onUseColumns(notes);
  };

  return (
    <div>
      <div className="docs-actions">
        <button
          type="button"
          disabled={explain.isPending}
          onClick={() => explain.mutate(result !== undefined)}
        >
          {explain.isPending ? "Asking…" : result ? "Ask again" : "Explain with AI"}
        </button>
      </div>
      {explain.isError && <p className="error">{explain.error.message}</p>}
      {result && (
        <section className="ai-card" aria-label="AI explanation">
          <p>{result.summary}</p>
          {result.caveats.length > 0 && (
            <>
              <strong>Worth checking</strong>
              <ul>
                {result.caveats.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </>
          )}
          <p className="muted">
            Written by {result.ai_model}
            {result.cached && " (cached)"}. It can be wrong, so read it before you save it.
          </p>
          <div className="docs-actions">
            <button type="button" onClick={() => onUseDescription(result.description)}>
              Use as description
            </button>
            <button type="button" onClick={useColumns}>
              Use column notes
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
