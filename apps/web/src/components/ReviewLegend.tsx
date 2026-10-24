const ITEMS = [
  { status: "added", label: "New" },
  { status: "modified", label: "Changed" },
  { status: "removed", label: "Removed" },
  { status: "affected", label: "Results may change" },
] as const;

interface Props {
  title: string;
  onExit: () => void;
}

/** Shown over the graph while a proposal is being reviewed. */
export function ReviewLegend({ title, onExit }: Props) {
  return (
    <aside className="legend" aria-label="Review mode">
      <p className="legend__title">
        Reviewing <strong>{title}</strong>
      </p>
      <ul>
        {ITEMS.map((i) => (
          <li key={i.status}>
            <span className={`legend__swatch legend__swatch--${i.status}`} aria-hidden="true" />
            {i.label}
          </li>
        ))}
      </ul>
      <button type="button" onClick={onExit}>
        Exit review
      </button>
    </aside>
  );
}
