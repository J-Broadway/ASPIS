import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationNodeDatum,
} from "d3-force";
import type { ClauseNode, GraphEdge } from "./types.js";

export interface LayoutNode extends SimulationNodeDatum {
  id: string;
  group: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

const CLUSTER_TABLE: Array<{ group: number; match: (id: string) => boolean }> = [
  {
    group: 0,
    match: (id) =>
      id === "aspis.entry" ||
      id === "aspis.domains" ||
      id.startsWith("aspis.authority."),
  },
  { group: 1, match: (id) => id.startsWith("aspis.registration.") },
  { group: 2, match: (id) => id.startsWith("aspis.clause.") },
  { group: 3, match: (id) => id.startsWith("aspis.registry.") },
  {
    group: 4,
    match: (id) => id.startsWith("aspis.workspace.") || id.startsWith("aspis.instance."),
  },
  { group: 5, match: (id) => id.startsWith("aspis.tools.") },
];

export function clusterGroupForId(id: string): number {
  for (const row of CLUSTER_TABLE) {
    if (row.match(id)) return row.group;
  }
  const rest = id.startsWith("aspis.") ? id.slice("aspis.".length) : id;
  const parts = rest.split(".");
  const key = parts.length >= 2 ? `${parts[0]}.${parts[1]}` : parts[0] ?? "ungrouped";
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
  return 6 + (Math.abs(h) % 8);
}

function forceCluster() {
  let nodes: LayoutNode[];
  const strength = 0.35;
  function force(alpha: number) {
    const centroids = new Map<number, { x: number; y: number; n: number }>();
    for (const d of nodes) {
      const g = d.group;
      if (!centroids.has(g)) centroids.set(g, { x: 0, y: 0, n: 0 });
      const c = centroids.get(g)!;
      c.x += d.x ?? 0;
      c.y += d.y ?? 0;
      c.n += 1;
    }
    for (const c of centroids.values()) {
      c.x /= c.n;
      c.y /= c.n;
    }
    for (const d of nodes) {
      const c = centroids.get(d.group);
      if (!c) continue;
      const x = d.x ?? 0;
      const y = d.y ?? 0;
      const dx = c.x - x;
      const dy = c.y - y;
      d.vx = (d.vx ?? 0) + dx * strength * alpha;
      d.vy = (d.vy ?? 0) + dy * strength * alpha;
    }
  }
  force.initialize = (init: LayoutNode[]) => {
    nodes = init;
  };
  return force;
}

export interface LayoutResult {
  positions: Map<string, { x: number; z: number }>;
  extent: { minX: number; maxX: number; minZ: number; maxZ: number };
}

export function computeLayout(nodes: ClauseNode[], edges: GraphEdge[]): LayoutResult {
  const simNodes: LayoutNode[] = nodes.map((n) => ({
    id: n.id,
    group: clusterGroupForId(n.id),
  }));

  const idToSim = new Map(simNodes.map((n) => [n.id, n]));
  const links = edges
    .map((e) => {
      const s = idToSim.get(e.from);
      const t = idToSim.get(e.to);
      if (!s || !t) return null;
      return { source: s, target: t };
    })
    .filter((x): x is { source: LayoutNode; target: LayoutNode } => x !== null);

  const sim = forceSimulation(simNodes as SimulationNodeDatum[])
    .force(
      "link",
      forceLink(links)
        .id((d: SimulationNodeDatum) => (d as LayoutNode).id)
        .distance(2.2)
        .strength(0.35),
    )
    .force("charge", forceManyBody().strength(-120))
    .force("center", forceCenter(0, 0))
    .force("cluster", forceCluster());

  sim.stop();
  for (let i = 0; i < 300; i++) sim.tick();

  /** Bias aspis.entry left of centroid (left-to-right crawl read). */
  let sx = 0,
    sz = 0;
  for (const n of simNodes) {
    sx += n.x ?? 0;
    sz += n.y ?? 0;
  }
  const inv = simNodes.length ? 1 / simNodes.length : 1;
  const cx = sx * inv;
  const entryNode = idToSim.get("aspis.entry");
  if (entryNode) {
    const ex = entryNode.x ?? 0;
    const ez = entryNode.y ?? 0;
    entryNode.x = Math.min(ex, cx - 6);
    entryNode.y = ez;
  }

  const positions = new Map<string, { x: number; z: number }>();
  let minX = Infinity,
    maxX = -Infinity,
    minZ = Infinity,
    maxZ = -Infinity;
  for (const n of simNodes) {
    const x = n.x ?? 0;
    const z = n.y ?? 0;
    positions.set(n.id, { x, z });
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minZ = Math.min(minZ, z);
    maxZ = Math.max(maxZ, z);
  }
  if (!Number.isFinite(minX)) {
    minX = maxX = minZ = maxZ = 0;
  }

  return { positions, extent: { minX, maxX, minZ, maxZ } };
}
