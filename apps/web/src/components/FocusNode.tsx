import { useReactFlow } from "@xyflow/react";
import { useEffect } from "react";

export interface FocusRequest {
  id: string;
  /** Changes on every request, so asking for the same node twice still centers it. */
  seq: number;
}

/** Renders nothing. Centers the view on a node whenever `focus` changes. Mount inside React Flow. */
export function FocusNode({ focus }: { focus: FocusRequest | null }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (!focus) return;
    void fitView({ nodes: [{ id: focus.id }], duration: 300, maxZoom: 1.2, padding: 0.6 });
  }, [focus, fitView]);
  return null;
}
