import { useQuery } from "@tanstack/react-query";
import { api, type Rule } from "../lib/api";

function RuleCard({ rule, onSelectModel }: { rule: Rule; onSelectModel: (name: string) => void }) {
  return (
    <article className="rule">
      <h3>{rule.name}</h3>
      <p className="muted">
        {rule.owner ? `Owner: ${rule.owner}` : "No owner yet"} · <code>{rule.id}</code>
      </p>
      {rule.description && <p>{rule.description}</p>}
      {rule.tags.length > 0 && <p className="muted">Tags: {rule.tags.join(", ")}</p>}
      {rule.applies_to.length === 0 ? (
        <p className="muted">Not linked to any model yet.</p>
      ) : (
        <ul className="chips" aria-label={`Models that use ${rule.name}`}>
          {rule.applies_to.map((link) => (
            <li key={link.model}>
              <button
                type="button"
                className="chip-button"
                onClick={() => onSelectModel(link.model)}
              >
                {link.model}
                {link.columns.length > 0 && ` (${link.columns.join(", ")})`}
              </button>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export function RulesPanel({ onSelectModel }: { onSelectModel: (name: string) => void }) {
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });

  return (
    <section className="panel" aria-label="Rules">
      <header className="panel__header">
        <h2>Business rules</h2>
        <p className="muted">
          Rules your team has named, with who owns them and which models carry them. They are
          written in openpipeline.yml. Click a model to see it in the graph.
        </p>
      </header>
      {rules.isPending && <p className="muted">Loading…</p>}
      {rules.isError && <p className="error">Could not load rules: {rules.error.message}</p>}
      {rules.data?.rules.length === 0 && (
        <p className="muted">No rules yet. Add a rules list to openpipeline.yml.</p>
      )}
      {rules.data?.rules.map((r) => (
        <RuleCard key={r.id} rule={r} onSelectModel={onSelectModel} />
      ))}
    </section>
  );
}
