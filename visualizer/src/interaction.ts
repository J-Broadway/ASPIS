import * as THREE from "three";
import type { ClauseNode, GraphEdge } from "./types.js";
import type { EdgeVisual } from "./edges.js";
import { resetEdgeStyle, setEdgeHighlight } from "./edges.js";
import type { NodeVisual } from "./nodes.js";
import { setNodeHoverHighlight } from "./nodes.js";

const EDGE_PICK_PX = 12;
const OUT_COLOR = 0x00e5ff;
const IN_COLOR = 0x446688;

export interface InteractionContext {
  camera: THREE.Camera;
  domElement: HTMLElement;
  nodesById: Map<string, NodeVisual>;
  edgesByKey: Map<string, EdgeVisual>;
  clausesById: Map<string, ClauseNode>;
  graphEdges: GraphEdge[];
  onSelectNode: (id: string | null) => void;
  onEdgeHoverInfo: (info: { from: string; to: string } | null) => void;
  tooltipEl: HTMLElement;
}

export interface InteractionHandle {
  dispose: () => void;
  highlightNode: (id: string) => void;
  clearHighlight: () => void;
}

export function attachInteraction(ctx: InteractionContext): InteractionHandle {
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let hoveredNode: NodeVisual | null = null;
  let hoveredEdge: EdgeVisual | null = null;

  const outgoingKeys = (id: string): Set<string> => {
    const c = ctx.clausesById.get(id);
    if (!c?.paths) return new Set();
    return new Set(c.paths.map((t) => `${id}→${t}`));
  };

  const incomingKeys = (id: string): Set<string> => {
    const s = new Set<string>();
    for (const e of ctx.graphEdges) {
      if (e.to === id) s.add(`${e.from}→${e.to}`);
    }
    return s;
  };

  const clearPathHighlight = () => {
    for (const ev of ctx.edgesByKey.values()) resetEdgeStyle(ev);
    for (const nv of ctx.nodesById.values()) {
      const el = nv.label.element as HTMLElement;
      el.classList.remove("label-active", "label-connected");
    }
  };

  const connectedNodeIds = (id: string): Set<string> => {
    const c = ctx.clausesById.get(id);
    return new Set(c?.paths ?? []);
  };

  const highlightPaths = (id: string) => {
    clearPathHighlight();
    const out = outgoingKeys(id);
    const inn = incomingKeys(id);
    for (const k of out) {
      const ev = ctx.edgesByKey.get(k);
      if (ev) setEdgeHighlight(ev, OUT_COLOR, 0.85);
    }
    for (const k of inn) {
      const ev = ctx.edgesByKey.get(k);
      if (ev) setEdgeHighlight(ev, IN_COLOR, 0.55);
    }

    const active = ctx.nodesById.get(id);
    if (active) (active.label.element as HTMLElement).classList.add("label-active");

    for (const tid of connectedNodeIds(id)) {
      const tn = ctx.nodesById.get(tid);
      if (tn) (tn.label.element as HTMLElement).classList.add("label-connected");
    }
  };

  const pickNode = (x: number, y: number): NodeVisual | null => {
    pointer.x = (x / window.innerWidth) * 2 - 1;
    pointer.y = -(y / window.innerHeight) * 2 + 1;
    raycaster.setFromCamera(pointer, ctx.camera);
    const meshes: THREE.Object3D[] = [];
    for (const nv of ctx.nodesById.values()) meshes.push(nv.mesh);
    const hits = raycaster.intersectObjects(meshes, false);
    if (hits.length === 0) return null;
    const mesh = hits[0].object as THREE.Mesh;
    for (const nv of ctx.nodesById.values()) {
      if (nv.mesh === mesh) return nv;
    }
    return null;
  };

  const projectToScreen = (v: THREE.Vector3, target: THREE.Vector2): void => {
    v.project(ctx.camera);
    target.x = (v.x * 0.5 + 0.5) * window.innerWidth;
    target.y = (-v.y * 0.5 + 0.5) * window.innerHeight;
  };

  const pickEdgeByScreenDist = (x: number, y: number): EdgeVisual | null => {
    const p = new THREE.Vector2(x, y);
    const scratch = new THREE.Vector3();
    const sp = new THREE.Vector2();
    let best: EdgeVisual | null = null;
    let bestD = EDGE_PICK_PX + 1;
    for (const ev of ctx.edgesByKey.values()) {
      ev.arrow.getWorldPosition(scratch);
      projectToScreen(scratch, sp);
      const d = p.distanceTo(sp);
      if (d < bestD) {
        bestD = d;
        best = ev;
      }
    }
    return bestD <= EDGE_PICK_PX ? best : null;
  };

  const onMove = (ev: PointerEvent) => {
    const node = pickNode(ev.clientX, ev.clientY);
    const edge = node ? null : pickEdgeByScreenDist(ev.clientX, ev.clientY);

    if (node !== hoveredNode) {
      if (hoveredNode) {
        setNodeHoverHighlight(hoveredNode, false);
        clearPathHighlight();
        ctx.tooltipEl.style.display = "none";
      }
      hoveredNode = node;
      if (hoveredNode) {
        setNodeHoverHighlight(hoveredNode, true);
        highlightPaths(hoveredNode.id);
        const c = ctx.clausesById.get(hoveredNode.id);
        ctx.tooltipEl.style.display = "block";
        ctx.tooltipEl.style.left = `${ev.clientX + 12}px`;
        ctx.tooltipEl.style.top = `${ev.clientY + 12}px`;
        ctx.tooltipEl.textContent = `${hoveredNode.id} · ${c?.kind ?? "?"} · paths ${c?.paths?.length ?? 0}`;
      }
    }

    if (edge !== hoveredEdge) {
      if (hoveredEdge && !hoveredNode) resetEdgeStyle(hoveredEdge);
      hoveredEdge = edge;
      if (hoveredEdge && !hoveredNode) {
        setEdgeHighlight(hoveredEdge, 0x00ffff, 0.85);
        ctx.onEdgeHoverInfo({ from: hoveredEdge.from, to: hoveredEdge.to });
        ctx.tooltipEl.style.display = "block";
        ctx.tooltipEl.style.left = `${ev.clientX + 12}px`;
        ctx.tooltipEl.style.top = `${ev.clientY + 12}px`;
        ctx.tooltipEl.textContent = `${hoveredEdge.from} → ${hoveredEdge.to}`;
      } else if (!hoveredEdge) {
        ctx.onEdgeHoverInfo(null);
        if (!hoveredNode) ctx.tooltipEl.style.display = "none";
      }
    }

    if (hoveredNode) {
      ctx.tooltipEl.style.left = `${ev.clientX + 12}px`;
      ctx.tooltipEl.style.top = `${ev.clientY + 12}px`;
    }

    ctx.domElement.style.cursor = hoveredNode || hoveredEdge ? "pointer" : "default";
  };

  const onClick = (ev: MouseEvent) => {
    const node = pickNode(ev.clientX, ev.clientY);
    if (node) {
      ctx.onSelectNode(node.id);
      return;
    }
    const edge = pickEdgeByScreenDist(ev.clientX, ev.clientY);
    if (edge) {
      ctx.onSelectNode(null);
      return;
    }
    ctx.onSelectNode(null);
  };

  const onKey = (ev: KeyboardEvent) => {
    if (ev.key === "Escape") ctx.onSelectNode(null);
  };

  ctx.domElement.addEventListener("pointermove", onMove);
  ctx.domElement.addEventListener("click", onClick);
  window.addEventListener("keydown", onKey);

  for (const nv of ctx.nodesById.values()) {
    const el = nv.label.element as HTMLElement;

    el.addEventListener("pointerenter", (ev: PointerEvent) => {
      if (hoveredNode !== nv) {
        if (hoveredNode) {
          setNodeHoverHighlight(hoveredNode, false);
          clearPathHighlight();
          ctx.tooltipEl.style.display = "none";
        }
        hoveredNode = nv;
        setNodeHoverHighlight(nv, true);
        highlightPaths(nv.id);
      }
      const c = ctx.clausesById.get(nv.id);
      ctx.tooltipEl.style.display = "block";
      ctx.tooltipEl.style.left = `${ev.clientX + 12}px`;
      ctx.tooltipEl.style.top = `${ev.clientY + 12}px`;
      ctx.tooltipEl.textContent = `${nv.id} · ${c?.kind ?? "?"} · paths ${c?.paths?.length ?? 0}`;
      ctx.domElement.style.cursor = "pointer";
    });

    el.addEventListener("pointerleave", () => {
      if (hoveredNode === nv) {
        setNodeHoverHighlight(nv, false);
        clearPathHighlight();
        ctx.tooltipEl.style.display = "none";
        hoveredNode = null;
        ctx.domElement.style.cursor = "default";
      }
    });

    el.addEventListener("pointermove", (ev: PointerEvent) => {
      ctx.tooltipEl.style.left = `${ev.clientX + 12}px`;
      ctx.tooltipEl.style.top = `${ev.clientY + 12}px`;
    });

    el.addEventListener("click", (e: MouseEvent) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      ctx.onSelectNode(nv.id);
    });

    el.addEventListener("contextmenu", (e: MouseEvent) => {
      e.preventDefault();
    });

    el.addEventListener("wheel", (e: WheelEvent) => {
      e.preventDefault();
      ctx.domElement.dispatchEvent(new WheelEvent("wheel", e));
    }, { passive: false });
  }

  const api: InteractionHandle = {
    dispose: () => {
      ctx.domElement.removeEventListener("pointermove", onMove);
      ctx.domElement.removeEventListener("click", onClick);
      window.removeEventListener("keydown", onKey);
    },
    highlightNode: (id: string) => {
      const nv = ctx.nodesById.get(id);
      if (!nv) return;
      hoveredNode = nv;
      setNodeHoverHighlight(nv, true);
      highlightPaths(id);
    },
    clearHighlight: () => {
      if (hoveredNode) {
        setNodeHoverHighlight(hoveredNode, false);
        clearPathHighlight();
        hoveredNode = null;
      }
    },
  };

  return api;
}
