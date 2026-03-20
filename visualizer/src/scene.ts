import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";

export interface SceneBundle {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  webglRenderer: THREE.WebGLRenderer;
  css2dRenderer: CSS2DRenderer;
  controls: OrbitControls;
  resize: () => void;
  dispose: () => void;
}

export function createScene(canvas: HTMLCanvasElement, cssHost: HTMLElement): SceneBundle {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0c0f);
  scene.fog = new THREE.Fog(0x0a0c0f, 400, 8000);

  /** `far` / fog are tuned after layout in `frameGraphCamera` — avoid tiny defaults that clip large graphs. */
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 50_000);
  camera.up.set(0, 1, 0);

  const webglRenderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  webglRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const css2dRenderer = new CSS2DRenderer();
  cssHost.appendChild(css2dRenderer.domElement);
  css2dRenderer.domElement.style.position = "absolute";
  css2dRenderer.domElement.style.inset = "0";
  css2dRenderer.domElement.style.pointerEvents = "none";

  const controls = new OrbitControls(camera, webglRenderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minPolarAngle = 0;
  controls.maxPolarAngle = Math.PI / 3;
  controls.mouseButtons = {
    LEFT: THREE.MOUSE.PAN,
    MIDDLE: THREE.MOUSE.DOLLY,
    RIGHT: THREE.MOUSE.ROTATE,
  };

  const amb = new THREE.AmbientLight(0x8899aa, 0.5);
  scene.add(amb);
  const dir = new THREE.DirectionalLight(0xffffff, 0.45);
  dir.position.set(10, 40, 20);
  scene.add(dir);

  const resize = () => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    webglRenderer.setSize(w, h);
    css2dRenderer.setSize(w, h);
  };
  resize();
  window.addEventListener("resize", resize);

  const dispose = () => {
    window.removeEventListener("resize", resize);
    controls.dispose();
    webglRenderer.dispose();
    cssHost.removeChild(css2dRenderer.domElement);
  };

  return { scene, camera, webglRenderer, css2dRenderer, controls, resize, dispose };
}

export function frameGraphCamera(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  scene: THREE.Scene,
  extent: { minX: number; maxX: number; minZ: number; maxZ: number },
): void {
  const cx = (extent.minX + extent.maxX) / 2;
  const cz = (extent.minZ + extent.maxZ) / 2;
  const dx = extent.maxX - extent.minX;
  const dz = extent.maxZ - extent.minZ;
  const span = Math.max(dx, dz, 12);
  const dist = span * 1.1;
  camera.position.set(cx + dist * 0.15, dist * 1.05, cz + dist * 0.85);
  controls.target.set(cx, 0, cz);
  const maxDist = span * 6;
  controls.maxDistance = maxDist;
  controls.minDistance = Math.max(2, span * 0.08);

  const target = new THREE.Vector3(cx, 0, cz);
  const camDist = camera.position.distanceTo(target);
  const halfDiag = 0.5 * Math.hypot(dx, dz);
  const horizon = camDist + halfDiag + 8;
  camera.far = Math.max(horizon * 4, span * 40, 2000);
  camera.near = Math.min(0.5, camera.far / 50_000);
  camera.updateProjectionMatrix();

  if (scene.fog instanceof THREE.Fog) {
    scene.fog.near = Math.max(20, camDist * 0.25);
    scene.fog.far = Math.max(scene.fog.near + span * 2, horizon * 2.2);
  }

  controls.update();
}
