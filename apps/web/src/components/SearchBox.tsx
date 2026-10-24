import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { api, type SearchHit } from "../lib/api";
import "./search-lineage.css";

interface Props {
  onPick: (hit: SearchHit) => void;
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

export function SearchBox({ onPick }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const text = query.trim();

  const results = useQuery({
    queryKey: ["search", text],
    queryFn: () => api.search(text),
    enabled: text.length > 0,
    placeholderData: keepPreviousData,
  });
  const hits = text ? (results.data ?? []) : [];

  // "/" or Ctrl/Cmd+K jumps to the search box from anywhere on the page.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const shortcut = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k";
      const slash = e.key === "/" && !e.ctrlKey && !e.metaKey && !isTypingTarget(e.target);
      if (shortcut || slash) {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function pick(hit: SearchHit) {
    onPick(hit);
    setOpen(false);
    setQuery("");
    inputRef.current?.blur();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      if (hits.length === 0) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((a) => (a + step + hits.length) % hits.length);
    } else if (e.key === "Enter") {
      const hit = hits[active];
      if (open && hit) {
        e.preventDefault();
        pick(hit);
      }
    } else if (e.key === "Escape") {
      if (open) e.preventDefault();
      setOpen(false);
      inputRef.current?.blur();
    }
  }

  const showList = open && text.length > 0;
  const activeId = hits[active] ? `${listId}-${active}` : undefined;

  return (
    <div className="search">
      <input
        ref={inputRef}
        className="search__input"
        type="search"
        role="combobox"
        aria-label="Search models and columns"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList ? activeId : undefined}
        aria-autocomplete="list"
        placeholder="Search models and columns"
        value={query}
        autoComplete="off"
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {!query && <kbd className="search__hint">/</kbd>}
      {showList && (
        <div className="search__results" id={listId} role="listbox" aria-label="Search results">
          {hits.length === 0 && !results.isFetching && (
            <div className="search__empty" role="presentation">
              Nothing matches "{text}".
            </div>
          )}
          {hits.map((hit, i) => (
            <div
              key={`${hit.node_id}:${hit.column ?? ""}`}
              id={`${listId}-${i}`}
              className="search__result"
              role="option"
              tabIndex={-1}
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              // mousedown runs before the input loses focus, so the click is not lost.
              onMouseDown={(e) => {
                e.preventDefault();
                pick(hit);
              }}
            >
              <span className={`badge badge--${hit.kind}`}>{hit.kind}</span>
              <span className="search__name">
                {hit.column ? `${hit.name}.${hit.column}` : hit.name}
              </span>
              {hit.snippet && <span className="search__snippet">{hit.snippet}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
