import * as THREE from "three";
import { CSS2DObject } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import TWEEN from "@tweenjs/tween.js";
import type { ClauseNode } from "./types.js";

const KIND_COLOR: Record<ClauseNode["kind"], number> = {
  contract: 0x00e5ff,
  route: 0xff00e5,
  guidance: 0xffab00,
  information: 0xe0e0e0,
};

export function labelTextForId(id: string): string {
  const s = id.startsWith("aspis.") ? id.slice("aspis.".length) : id;
  const parts = s.split(".");
  if (parts.length >= 2) return `${parts[parts.length - 2]}.${parts[parts.length - 1]}`;
  return s;
}

export interface NodeVisual {
  id: string;
  group: THREE.Group;
  mesh: THREE.Mesh;
  label: CSS2DObject;
  ring?: THREE.Mesh;
  baseEmissive: number;
  kind: ClauseNode["kind"];
}

export interface NodesBuild {
  byId: Map<string, NodeVisual>;
  root: THREE.Group;
  entryRing: THREE.Mesh | null;
}

function geometryForKind(kind: ClauseNode["kind"]): THREE.BufferGeometry {
  switch (kind) {
    case "contract":
      return new THREE.SphereGeometry(0.4, 24, 24);
    case "route":
      return new THREE.OctahedronGeometry(0.5, 0);
    case "guidance":
      return new THREE.DodecahedronGeometry(0.45, 0);
    case "information":
      return new THREE.BoxGeometry(0.6, 0.6, 0.6);
    default:
      return new THREE.SphereGeometry(0.4, 16, 16);
  }
}

export function buildNodes(
  nodes: ClauseNode[],
  positions: Map<string, { x: number; z: number }>,
): NodesBuild {
  const root = new THREE.Group();
  const byId = new Map<string, NodeVisual>();
  let entryRing: THREE.Mesh | null = null;

  for (const clause of nodes) {
    const pos = positions.get(clause.id);
    if (!pos) continue;
    const color = KIND_COLOR[clause.kind] ?? 0x00e5ff;
    const geom = geometryForKind(clause.kind);
    const mat = new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.08,
      metalness: 0.2,
      roughness: 0.65,
    });
    const mesh = new THREE.Mesh(geom, mat);
    const group = new THREE.Group();
    group.position.set(pos.x, 0, pos.z);
    group.add(mesh);

    const span = document.createElement("span");
    span.className = "node-label";
    span.textContent = labelTextForId(clause.id);
    span.title = clause.id;
    const label = new CSS2DObject(span);
    label.position.set(0, 0.85, 0);
    group.add(label);

    let ringMesh: THREE.Mesh | undefined;
    if (clause.id === "aspis.entry") {
      const ringGeom = new THREE.RingGeometry(0.65, 0.85, 48);
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0x00e5ff,
        transparent: true,
        opacity: 0.55,
        side: THREE.DoubleSide,
      });
      ringMesh = new THREE.Mesh(ringGeom, ringMat);
      ringMesh.rotation.x = -Math.PI / 2;
      ringMesh.position.y = 0.02;
      group.add(ringMesh);
      entryRing = ringMesh;
      const pulse = { o: 0.55 };
      new TWEEN.Tween(pulse)
        .to({ o: 0.9 }, 1400)
        .easing(TWEEN.Easing.Sinusoidal.InOut)
        .yoyo(true)
        .repeat(Infinity)
        .onUpdate(() => {
          ringMat.opacity = pulse.o;
        })
        .start();
    }

    root.add(group);
    byId.set(clause.id, {
      id: clause.id,
      group,
      mesh,
      label,
      ring: ringMesh,
      baseEmissive: 0.08,
      kind: clause.kind,
    });
  }

  return { byId, root, entryRing };
}

export function setNodeHoverHighlight(nv: NodeVisual | null, on: boolean): void {
  if (!nv) return;
  const mat = nv.mesh.material as THREE.MeshStandardMaterial;
  mat.emissiveIntensity = on ? 0.45 : nv.baseEmissive;
  const el = nv.label.element as HTMLElement;
  el.classList.toggle("label-hover", on);
}

export function setNodeLabelVisited(nv: NodeVisual, visited: boolean): void {
  const el = nv.label.element as HTMLElement;
  el.classList.toggle("label-visited", visited);
}

export function pulseNodeScale(nv: NodeVisual, duration = 320): void {
  const g = nv.group;
  const from = { s: 1 };
  new TWEEN.Tween(from)
    .to({ s: 1.25 }, duration / 2)
    .easing(TWEEN.Easing.Quadratic.Out)
    .onUpdate(() => {
      g.scale.setScalar(from.s);
    })
    .chain(
      new TWEEN.Tween(from)
        .to({ s: 1 }, duration / 2)
        .easing(TWEEN.Easing.Quadratic.In)
        .onUpdate(() => {
          g.scale.setScalar(from.s);
        }),
    )
    .start();
}

export function updateLabelOpacities(
  byId: Map<string, NodeVisual>,
  camera: THREE.Camera,
): void {
  for (const nv of byId.values()) {
    const el = nv.label.element as HTMLElement;
    if (el.classList.contains("label-active") || el.classList.contains("label-connected")) {
      continue;
    }
    const w = new THREE.Vector3();
    nv.group.getWorldPosition(w);
    const d = camera.position.distanceTo(w);
    const t = THREE.MathUtils.clamp(1 - (d - 15) / 80, 0.25, 1);
    el.style.opacity = String(t);
  }
}
