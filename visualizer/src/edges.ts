import * as THREE from "three";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import type { GraphEdge } from "./types.js";

const REST_COLOR = 0x1a3a4a;
const REST_OPACITY = 0.3;

export interface EdgeVisual {
  key: string;
  from: string;
  to: string;
  line: Line2;
  material: LineMaterial;
  arrow: THREE.Mesh;
  /** World position of arrow (direction cue) for screen-space hit test */
  arrowWorld: THREE.Vector3;
  curve: THREE.QuadraticBezierCurve3;
}

export interface EdgesBuild {
  byKey: Map<string, EdgeVisual>;
  root: THREE.Group;
  lineResolution: { w: number; h: number };
}

function perp2(a: THREE.Vector3, b: THREE.Vector3): THREE.Vector3 {
  const d = new THREE.Vector3().subVectors(b, a);
  d.y = 0;
  if (d.lengthSq() < 1e-8) return new THREE.Vector3(1, 0, 0);
  d.normalize();
  return new THREE.Vector3(-d.z, 0, d.x);
}

export function buildEdges(
  edges: GraphEdge[],
  positions: Map<string, { x: number; z: number }>,
  viewportW: number,
  viewportH: number,
): EdgesBuild {
  const root = new THREE.Group();
  const byKey = new Map<string, EdgeVisual>();
  const edgeList = edges.filter((e) => positions.has(e.from) && positions.has(e.to));
  const forward = new Set(edgeList.map((e) => `${e.from}→${e.to}`));
  const pairKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);
  const bidirectionalPair = new Set<string>();
  for (const e of edgeList) {
    if (forward.has(`${e.to}→${e.from}`)) bidirectionalPair.add(pairKey(e.from, e.to));
  }

  function makeMaterial(): LineMaterial {
    const m = new LineMaterial({
      color: REST_COLOR,
      linewidth: 2,
      transparent: true,
      opacity: REST_OPACITY,
      depthWrite: false,
    });
    m.resolution.set(viewportW, viewportH);
    return m;
  }

  for (const e of edgeList) {
    const key = `${e.from}→${e.to}`;
    const p0 = positions.get(e.from)!;
    const p1 = positions.get(e.to)!;
    const a = new THREE.Vector3(p0.x, 0, p0.z);
    const b = new THREE.Vector3(p1.x, 0, p1.z);
    const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);

    let offsetSign = 0;
    if (bidirectionalPair.has(pairKey(e.from, e.to))) {
      offsetSign = e.from.localeCompare(e.to) < 0 ? 1 : -1;
    }

    const perp = perp2(a, b).multiplyScalar(0.15 * offsetSign);
    const ctrl = mid.clone().add(perp);
    const curve = new THREE.QuadraticBezierCurve3(a, ctrl, b);

    const samples = 32;
    const pts: number[] = [];
    for (let i = 0; i <= samples; i++) {
      const t = i / samples;
      const p = curve.getPoint(t);
      pts.push(p.x, p.y, p.z);
    }

    const geom = new LineGeometry();
    geom.setPositions(pts);
    const material = makeMaterial();
    const line = new Line2(geom, material);
    line.computeLineDistances();

    const tArrow = 0.85;
    const posArrow = curve.getPoint(tArrow);
    const tan = curve.getTangent(tArrow).normalize();
    const arrowGeom = new THREE.ConeGeometry(0.12, 0.3, 12);
    const arrowMat = new THREE.MeshStandardMaterial({
      color: REST_COLOR,
      transparent: true,
      opacity: REST_OPACITY,
      emissive: REST_COLOR,
      emissiveIntensity: 0.1,
    });
    const arrow = new THREE.Mesh(arrowGeom, arrowMat);
    arrow.position.copy(posArrow);
    const up = new THREE.Vector3(0, 1, 0);
    const quat = new THREE.Quaternion().setFromUnitVectors(up, tan);
    arrow.setRotationFromQuaternion(quat);

    root.add(line);
    root.add(arrow);

    byKey.set(key, {
      key,
      from: e.from,
      to: e.to,
      line,
      material,
      arrow,
      arrowWorld: posArrow.clone(),
      curve,
    });
  }

  return { byKey, root, lineResolution: { w: viewportW, h: viewportH } };
}

export function updateEdgeLineResolution(build: EdgesBuild, w: number, h: number): void {
  build.lineResolution = { w, h };
  for (const ev of build.byKey.values()) {
    ev.material.resolution.set(w, h);
  }
}

export function setEdgeHighlight(ev: EdgeVisual, color: number, opacity: number): void {
  ev.material.color.setHex(color);
  ev.material.opacity = opacity;
  const am = ev.arrow.material as THREE.MeshStandardMaterial;
  am.color.setHex(color);
  am.opacity = opacity;
}

export function resetEdgeStyle(ev: EdgeVisual): void {
  setEdgeHighlight(ev, REST_COLOR, REST_OPACITY);
}
