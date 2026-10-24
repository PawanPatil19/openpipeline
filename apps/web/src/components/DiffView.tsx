type LineKind = "add" | "del" | "hunk" | "meta" | "ctx";

function kindOf(line: string): LineKind {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "ctx";
}

/** A unified diff with added lines in green and removed lines in red. */
export function DiffView({ diff }: { diff: string }) {
  if (diff.trim() === "") return <p className="muted">No changes in this file.</p>;
  const lines = diff.replace(/\n$/, "").split("\n");
  return (
    <pre className="diff">
      {lines.map((line, i) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: diff lines can repeat and never reorder
          key={i}
          className={`diff__line diff__line--${kindOf(line)}`}
          data-kind={kindOf(line)}
        >
          {line || " "}
          {"\n"}
        </span>
      ))}
    </pre>
  );
}
