import {
  Background,
  Controls,
  type Edge,
  Handle,
  MiniMap,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
} from "@xyflow/react";
import { useMemo } from "react";
import type { Graph, GraphNode, NodeStatus } from "../lib/api";
import { layoutGraph, lineage, NODE_HEIGHT, NODE_WIDTH } from "../lib/layout";

type PipelineNode = Node<
  { node: GraphNode; dimmed: boolean; selected: boolean; status?: NodeStatus; hasRules: boolean },
  "pipeline"
>;

function PipelineNodeView({ data }: NodeProps<PipelineNode>) {
  const { node, dimmed, selected, status, hasRules } = data;
  return (
    <div
      className={`pnode pnode--${node.kind}${dimmed ? " is-dimmed" : ""}${selected ? " is-selected" : ""}${status ? ` pnode--${status}` : ""}`}
      data-status={status}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
      title={node.description || node.name}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <span className="pnode__kind">{node.materialized ?? node.kind}</span>
      <span className="pnode__name">{node.name}</span>
      {hasRules && (
        <span className="pnode__rules" role="img" aria-label="Implements a business rule">
          R
        </span>
      )}
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}

const nodeTypes = { pipeline: PipelineNodeView };

const KIND_COLORS: Record<GraphNode["kind"], string> = {
  model: "#2f5bea",
  source: "#138a5e",
  seed: "#b7791f",
  snapshot: "#8b5cf6",
};

const STATUS_COLORS: Partial<Record<NodeStatus, string>> = {
  added: "#1f9d55",
  modified: "#d98e04",
  removed: "#d64545",
};

interface Props {
  graph: Graph;
  selectedId: string | null;
  onSelect: (node: GraphNode | null) => void;
  /** Review mode: colour nodes by how a proposal would change them, keyed by node id. */
  statuses?: Record<string, NodeStatus>;
  /** Names of models that implement at least one business rule. */
  ruleModels?: ReadonlySet<string>;
}

export function GraphView({ graph, selectedId, onSelect, statuses, ruleModels }: Props) {
  const positions = useMemo(() => layoutGraph(graph), [graph]);
  const highlighted = useMemo(
    () => (selectedId ? lineage(graph, selectedId) : null),
    [graph, selectedId],
  );

  const nodes: PipelineNode[] = graph.nodes.map((n) => {
    const p = positions.get(n.id);
    return {
      id: n.id,
      type: "pipeline",
      position: { x: p?.x ?? 0, y: p?.y ?? 0 },
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      data: {
        node: n,
        dimmed: highlighted !== null && !highlighted.has(n.id),
        selected: n.id === selectedId,
        status: statuses?.[n.id],
        hasRules: ruleModels?.has(n.name) ?? false,
      },
    };
  });

  const edges: Edge[] = graph.edges.map((e) => {
    const lit = highlighted?.has(e.source) && highlighted.has(e.target);
    return {
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      animated: Boolean(lit && selectedId),
      className:
        [
          highlighted && !lit ? "is-dimmed" : "",
          statuses?.[e.source] === "removed" || statuses?.[e.target] === "removed"
            ? "is-ghost"
            : "",
        ]
          .filter(Boolean)
          .join(" ") || undefined,
    };
  });

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, n) => onSelect((n as PipelineNode).data.node)}
      onPaneClick={() => onSelect(null)}
      nodesDraggable={false}
      nodesConnectable={false}
      fitView
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={20} />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(n) => {
          const d = (n as PipelineNode).data;
          return (d.status && STATUS_COLORS[d.status]) || KIND_COLORS[d.node.kind];
        }}
      />
    </ReactFlow>
  );
}
