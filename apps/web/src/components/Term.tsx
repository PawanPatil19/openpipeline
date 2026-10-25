import { type ReactNode, useId, useState } from "react";
import type { TermUsed } from "../lib/api";

/**
 * A label with its definition in a small popover. It opens on hover and on keyboard focus,
 * and a tap or Enter toggles it too, so it works without a mouse. Escape closes it.
 * Without a definition it is just the label.
 */
export function Term({ label, definition }: { label: string; definition?: string | null }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  if (!definition) return <>{label}</>;
  return (
    <span className="term-wrap">
      <button
        type="button"
        className="term"
        aria-describedby={id}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        {label}
      </button>
      <span role="tooltip" id={id} className={open ? "term__tip term__tip--open" : "term__tip"}>
        {definition}
      </span>
    </span>
  );
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * `text` with the glossary labels that have a definition turned into `Term`s. Quoted
 * values such as 'completed' are left alone, and a label only matches as whole words.
 */
export function TermText({ text, terms }: { text: string; terms: TermUsed[] }): ReactNode {
  const defined = new Map(terms.filter((t) => t.definition).map((t) => [t.label, t.definition]));
  if (defined.size === 0) return text;
  const labels = [...defined.keys()].sort((a, b) => b.length - a.length).map(escapeRegExp);
  // A quoted value (not an apostrophe inside a word) comes first so it wins; group 1 is a label.
  const pattern = new RegExp(
    `(?<!\\w)'(?:[^']|'')*(?:'|$)|(?<!\\w)(${labels.join("|")})(?!\\w)`,
    "g",
  );
  const parts: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    const label = m[1];
    if (label === undefined) continue;
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(<Term key={m.index} label={label} definition={defined.get(label)} />);
    last = m.index + label.length;
  }
  if (last === 0) return text;
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
