import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type ChangePreview, type Proposal } from "../lib/api";
import { useAuth } from "../lib/useAuth";
import { DiffView } from "./DiffView";

const KIND_LABEL = { added: "New file", modified: "Edited", deleted: "Deleted" } as const;

function Summary({ preview }: { preview: ChangePreview }) {
  // Warnings and unreadable SQL are shown on their own, highlighted.
  const lines = preview.summary.filter(
    (l) => !l.startsWith("New warning") && !l.startsWith("Could not read"),
  );
  return (
    <div className="summary">
      <ul>
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      {(preview.new_warnings.length > 0 || preview.parse_errors.length > 0) && (
        <div className="callout callout--warn" role="alert">
          <strong>Problems this change would cause</strong>
          <ul>
            {preview.new_warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
            {preview.parse_errors.map((e) => (
              <li key={e.model}>
                Could not read the SQL of {e.model}: {e.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Comments({ proposal }: { proposal: Proposal }) {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const [text, setText] = useState("");
  const send = useMutation({
    mutationFn: () => api.comment(proposal.id, text.trim()),
    onSuccess: () => {
      setText("");
      return qc.invalidateQueries({ queryKey: ["proposals"] });
    },
  });
  const comments = proposal.comments ?? [];
  return (
    <section aria-label="Comments" className="comments">
      <h4>Comments</h4>
      {comments.length === 0 && <p className="muted">No comments yet.</p>}
      <ul>
        {comments.map((c) => (
          <li key={`${c.created_at}-${c.author}-${c.text}`}>
            <strong>{c.author}</strong>{" "}
            <span className="muted">{new Date(c.created_at).toLocaleString()}</span>
            <p>{c.text}</p>
          </li>
        ))}
      </ul>
      {canWrite && (
        <>
          <label>
            <span className="visually-hidden">Feedback for the agent</span>
            <textarea
              rows={2}
              placeholder="Leave feedback for the agent"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={send.isPending || text.trim() === ""}
            onClick={() => send.mutate()}
          >
            Send feedback
          </button>
        </>
      )}
      {send.isError && <p className="error">{send.error.message}</p>}
    </section>
  );
}

interface CardProps {
  proposal: Proposal;
  reviewing: boolean;
  onReview: (id: string | null) => void;
}

function ProposalCard({ proposal, reviewing, onReview }: CardProps) {
  const qc = useQueryClient();
  const { canWrite } = useAuth();
  const pending = proposal.status === "pending";
  const [reason, setReason] = useState("");
  const preview = useQuery({
    queryKey: ["preview", proposal.id],
    queryFn: () => api.preview(proposal.id),
    enabled: pending,
    retry: false,
  });
  const decide = useMutation({
    mutationFn: (v: { status: "accepted" | "rejected"; force?: boolean }) =>
      api.decide(proposal.id, v.status, {
        force: v.force,
        reason: v.status === "rejected" ? reason.trim() || undefined : undefined,
      }),
    onSuccess: () => {
      onReview(null);
      return qc.invalidateQueries();
    },
  });
  const conflict =
    decide.error instanceof ApiError &&
    decide.error.status === 409 &&
    decide.error.changedFiles.length > 0
      ? decide.error
      : null;

  return (
    <article className="proposal">
      <header>
        <h3>{proposal.title}</h3>
        <span className={`badge badge--${proposal.status}`}>{proposal.status}</span>
      </header>
      <p className="muted">
        From {proposal.author} · {new Date(proposal.created_at).toLocaleString()}
      </p>
      {proposal.revises && <p className="muted">Revises an earlier proposal.</p>}
      {proposal.status === "superseded" && (
        <p className="muted">The agent replaced this with a newer proposal.</p>
      )}
      {proposal.rationale && <p>{proposal.rationale}</p>}

      {pending && preview.isPending && <p className="muted">Working out the effect…</p>}
      {pending && preview.isError && (
        <p className="error">Could not preview this change: {preview.error.message}</p>
      )}
      {pending && preview.data && <Summary preview={preview.data} />}

      {pending && (
        <button
          type="button"
          aria-pressed={reviewing}
          onClick={() => onReview(reviewing ? null : proposal.id)}
          disabled={!preview.data}
        >
          Show on graph
        </button>
      )}

      {pending && preview.data
        ? preview.data.files.map((f) => (
            <details key={f.path}>
              <summary>
                {KIND_LABEL[f.change]} <code>{f.path}</code>
              </summary>
              <DiffView diff={f.diff} />
            </details>
          ))
        : proposal.changes.map((c) => (
            <details key={c.path}>
              <summary>
                {c.content === "" ? "Delete" : "Write"} <code>{c.path}</code>
              </summary>
              {c.content && <pre>{c.content}</pre>}
            </details>
          ))}

      <Comments proposal={proposal} />

      {pending && !canWrite && (
        <p className="muted readonly-note">
          Read-only: this server does not allow accepting or rejecting proposals.
        </p>
      )}
      {pending && canWrite && (
        <>
          <label>
            <span className="visually-hidden">Reason for rejecting</span>
            <input
              type="text"
              placeholder="Reason for rejecting (optional)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ status: "accepted" })}
            >
              Accept and write files
            </button>
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ status: "rejected" })}
            >
              Reject
            </button>
          </div>
        </>
      )}
      {conflict && (
        <div className="callout callout--warn" role="alert">
          <p>
            Some files changed after this proposal was made: {conflict.changedFiles.join(", ")}.
            Accepting now would overwrite those changes.
          </p>
          <button type="button" onClick={() => decide.mutate({ status: "accepted", force: true })}>
            Accept anyway
          </button>
        </div>
      )}
      {decide.isError && !conflict && <p className="error">{decide.error.message}</p>}
    </article>
  );
}

interface Props {
  reviewingId?: string | null;
  onReview?: (id: string | null) => void;
}

export function ProposalsPanel({ reviewingId = null, onReview = () => {} }: Props) {
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
        <ProposalCard
          key={p.id}
          proposal={p}
          reviewing={reviewingId === p.id}
          onReview={onReview}
        />
      ))}
    </section>
  );
}
