import { createContext, useContext } from "react";

/** The column whose lineage the person is looking at. */
export interface ColumnSelection {
  nodeId: string;
  column: string;
}

export interface ColumnFocus {
  selection: ColumnSelection | null;
  /** Select a column, which also selects its node. Pass `null` to clear it. */
  select: (selection: ColumnSelection | null) => void;
}

export const ColumnFocusContext = createContext<ColumnFocus>({
  selection: null,
  select: () => {},
});

export function useColumnFocus(): ColumnFocus {
  return useContext(ColumnFocusContext);
}
