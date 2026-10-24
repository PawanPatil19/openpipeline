import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Proposal } from "../lib/api";

function ProposalCard({ proposal }: { proposal: Proposal }) {
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (status: "accepted" | "rejected") => api.decide(proposal.id, status),
    onSuccess: () => qc.invalidateQueries(),
  });
  const pending = proposal.status === "pending";

  return (
    <article className="proposal">
      <header>
        <h3>{proposal.title}</h3>
        <span className={`badge badge--${proposal.status}`}>{proposal.status}</span>
      </header>
      <p className="muted">
        From {proposal.author} · {new Date(proposal.created_at).toLocaleString()}
      </p>
      {proposal.rationale && <p>{proposal.rationale}</p>}
      {proposal.changes.map((c) => (
        <details key={c.path}>
          <summary>
            {c.content === "" ? "Delete" : "Write"} <code>{c.path}</code>
          </summary>
          {c.content && <pre>{c.content}</pre>}
        </details>
      ))}
      {pending && (
        <div className="actions">
          <button
            type="button"
            className="primary"
            disabled={decide.isPending}
            onClick={() => decide.mutate("accepted")}
          >
            Accept and write files
          </button>
          <button
            type="button"
            disabled={decide.isPending}
            onClick={() => decide.mutate("rejected")}
          >
            Reject
          </button>
        </div>
      )}
      {decide.isError && <p className="error">{decide.error.message}</p>}
    </article>
  );
}

export function ProposalsPanel() {
  const proposals = useQuery({ queryKey: ["proposals"], queryFn: api.proposals });

  return (
    <section className="panel" aria-label="Proposals">
      <header className="panel__header">
        <h2>Proposals</h2>
        <p className="muted">
          Changes suggested by AI agents through the MCP server. Nothing is written until you
          accept.
        </p>
      </header>
      {proposals.isPending && <p className="muted">Loading…</p>}
      {proposals.data?.length === 0 && <p className="muted">No proposals yet.</p>}
      {proposals.data?.map((p) => (
        <ProposalCard key={p.id} proposal={p} />
      ))}
    </section>
  );
}
