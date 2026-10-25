import { useQuery } from "@tanstack/react-query";
import { api, type GlossaryTerm } from "../lib/api";

function TermCard({ term }: { term: GlossaryTerm }) {
  return (
    <article className="rule">
      <h3>{term.label}</h3>
      <p className="muted">
        <code>{term.name}</code>
        {term.aliases.length > 0 && <> · also {term.aliases.map((a) => `"${a}"`).join(", ")}</>}
        {term.origin === "meta" && " · from dbt meta"}
      </p>
      {term.definition ? <p>{term.definition}</p> : <p className="muted">No definition yet.</p>}
    </article>
  );
}

export function GlossaryPanel() {
  const glossary = useQuery({ queryKey: ["glossary"], queryFn: api.glossary });

  return (
    <section className="panel" aria-label="Glossary">
      <header className="panel__header">
        <h2>Glossary</h2>
        <p className="muted">
          The words your business uses for its models and columns. Business words mode tells stories
          with these. They are written in openpipeline.yml, or as a label in a dbt model's or
          column's meta.
        </p>
      </header>
      {glossary.isPending && <p className="muted">Loading…</p>}
      {glossary.isError && (
        <p className="error">Could not load the glossary: {glossary.error.message}</p>
      )}
      {glossary.data && glossary.data.warnings.length > 0 && (
        <p className="warn" role="status">
          {glossary.data.warnings.join("; ")}
        </p>
      )}
      {glossary.data?.terms.length === 0 && (
        <p className="muted">No terms yet. Add a glossary list to openpipeline.yml.</p>
      )}
      {glossary.data?.terms.map((t) => (
        <TermCard key={t.name} term={t} />
      ))}
    </section>
  );
}
