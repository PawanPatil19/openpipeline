import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FocusRequest } from "../components/FocusNode";
import { api, type Graph, type GraphNode, type SearchHit } from "./api";
import type { ColumnFocus, ColumnSelection } from "./columnFocus";

/**
 * Which node and column are selected, and what the graph should do about it.
 *
 * Search results and column lineage links both call `select`, which selects the node,
 * centers the graph on it, and (for a column) starts tracing that column's lineage.
 */
export function useGraphFocus(graph: Graph | undefined, onNodeChosen?: () => void) {
  const [selected, setSelectedNode] = useState<GraphNode | null>(null);
  const [selection, setSelection] = useState<ColumnSelection | null>(null);
  const [focus, setFocus] = useState<FocusRequest | null>(null);

  // A column selection only counts while its node is the selected one.
  const activeColumn = selection && selection.nodeId === selected?.id ? selection : null;

  const lineage = useQuery({
    queryKey: ["column-lineage", activeColumn?.nodeId, activeColumn?.column],
    queryFn: () => api.columnLineage(activeColumn?.nodeId ?? "", activeColumn?.column ?? ""),
    enabled: activeColumn !== null,
  });

  const highlightIds = useMemo(() => {
    if (!activeColumn || !lineage.data) return null;
    const ids = new Set([activeColumn.nodeId]);
    for (const r of [...lineage.data.upstream, ...lineage.data.downstream]) ids.add(r.node_id);
    return ids;
  }, [activeColumn, lineage.data]);

  // Once a column's lineage is known, bring the whole path into view, not just the node.
  useEffect(() => {
    if (!activeColumn || !highlightIds) return;
    const ids = [...highlightIds];
    setFocus((f) => ({ id: activeColumn.nodeId, ids, seq: (f?.seq ?? 0) + 1 }));
  }, [activeColumn, highlightIds]);

  const setSelected = useCallback((node: GraphNode | null) => {
    setSelectedNode(node);
    setSelection(null);
  }, []);

  const select = useCallback(
    (next: ColumnSelection | null) => {
      if (next === null) {
        setSelection(null);
        return;
      }
      const node = graph?.nodes.find((n) => n.id === next.nodeId);
      if (!node) return;
      // Picking a column of the node that is already open: the path fit below is enough.
      const sameNode = node.id === selected?.id;
      setSelectedNode(node);
      setSelection(next);
      if (!sameNode) setFocus((f) => ({ id: node.id, seq: (f?.seq ?? 0) + 1 }));
      onNodeChosen?.();
    },
    [graph, onNodeChosen, selected],
  );

  const pickHit = useCallback(
    (hit: SearchHit) => {
      const node = graph?.nodes.find((n) => n.id === hit.node_id);
      if (!node) return;
      if (hit.column) {
        select({ nodeId: node.id, column: hit.column });
        return;
      }
      setSelectedNode(node);
      setSelection(null);
      setFocus((f) => ({ id: node.id, seq: (f?.seq ?? 0) + 1 }));
      onNodeChosen?.();
    },
    [graph, select, onNodeChosen],
  );

  const columnFocus: ColumnFocus = useMemo(
    () => ({ selection: activeColumn, select }),
    [activeColumn, select],
  );

  return { selected, setSelected, focus, highlightIds, columnFocus, pickHit };
}
