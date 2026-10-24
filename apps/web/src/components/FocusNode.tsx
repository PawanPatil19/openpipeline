import { useReactFlow } from "@xyflow/react";
import { useEffect } from "react";

export interface FocusRequest {
  id: string;
  /** Changes on every request, so asking for the same node twice still centers it. */
  seq: number;
  /** Fit all of these nodes in view instead of just `id`. Used to show a column's whole path. */
  ids?: string[];
}

/** Renders nothing. Centers the view on a node, or fits a set of nodes, whenever `focus` changes. Mount inside React Flow. */
export function FocusNode({ focus }: { focus: FocusRequest | null }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (!focus) return;
    const many = focus.ids !== undefined && focus.ids.length > 1;
    void fitView({
      nodes: (many ? (focus.ids as string[]) : [focus.id]).map((id) => ({ id })),
      duration: 300,
      maxZoom: 1.2,
      padding: many ? 0.25 : 0.6,
    });
  }, [focus, fitView]);
  return null;
}
