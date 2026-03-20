import * as THREE from "three";
import TWEEN from "@tweenjs/tween.js";
import "./style.css";
import { initApiFromLocation, fetchGraph, fetchSessions } from "./api.js";
import { computeLayout } from "./layout.js";
import { createScene, frameGraphCamera } from "./scene.js";
import { buildNodes, updateLabelOpacities } from "./nodes.js";
import { buildEdges, updateEdgeLineResolution } from "./edges.js";
import { attachInteraction } from "./interaction.js";
import { createDetailPanel } from "./detailPanel.js";
import { createHud, countKinds, type HudApi } from "./hud.js";
import { PlaybackController } from "./playback.js";
import { SESSION_ID_RE, TraceManager } from "./tracePlayer.js";
import type { TraceLogEntry } from "./types.js";

async function main(): Promise<void> {
  initApiFromLocation();

  const canvas = document.getElementById("webgl") as HTMLCanvasElement;
  const cssHost = document.getElementById("css2d-host") as HTMLElement;
  const app = document.getElementById("app") as HTMLElement;

  let graph: Awaited<ReturnType<typeof fetchGraph>>;
  try {
    graph = await fetchGraph(true);
  } catch (e) {
    app.innerHTML = `<pre class="fatal">${e instanceof Error ? e.message : String(e)}</pre>`;
    return;
  }

  const { positions, extent } = computeLayout(graph.nodes, graph.edges);
  const { scene, camera, webglRenderer, css2dRenderer, controls, resize } = createScene(canvas, cssHost);

  const nodesBuild = buildNodes(graph.nodes, positions);
  scene.add(nodesBuild.root);

  const edgesBuild = buildEdges(graph.edges, positions, window.innerWidth, window.innerHeight);
  scene.add(edgesBuild.root);

  frameGraphCamera(camera, controls, scene, extent);

  const clausesById = new Map(graph.nodes.map((n) => [n.id, n]));
  const playback = new PlaybackController();

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip";
  document.body.appendChild(tooltip);

  const detail = createDetailPanel(
    (targetId) => {
      detail.close();
      flyToClause(targetId);
      const c = clausesById.get(targetId);
      if (c) detail.open(c);
    },
    () => detail.close(),
  );
  document.body.appendChild(detail.root);

  function flyToClause(id: string): void {
    const nv = nodesBuild.byId.get(id);
    if (!nv) return;
    const wp = new THREE.Vector3();
    nv.group.getWorldPosition(wp);
    flyToPoint(wp);
  }

  function flyToPoint(target: THREE.Vector3): void {
    const endCam = new THREE.Vector3(target.x + 18, 22, target.z + 18);
    const startCam = camera.position.clone();
    const startTgt = controls.target.clone();
    const u = { t: 0 };
    new TWEEN.Tween(u)
      .to({ t: 1 }, 550)
      .easing(TWEEN.Easing.Cubic.Out)
      .onUpdate(() => {
        camera.position.lerpVectors(startCam, endCam, u.t);
        controls.target.lerpVectors(startTgt, target, u.t);
        controls.update();
      })
      .start();
  }

  function flyToClauseIds(ids: string[]): void {
    const points: THREE.Vector3[] = [];
    for (const id of ids) {
      const nv = nodesBuild.byId.get(id);
      if (!nv) continue;
      const wp = new THREE.Vector3();
      nv.group.getWorldPosition(wp);
      points.push(wp);
    }
    if (points.length === 0) return;
    const center = new THREE.Vector3();
    for (const point of points) center.add(point);
    center.multiplyScalar(1 / points.length);
    flyToPoint(center);
  }

  const hudRef: { current: HudApi | null } = { current: null };

  const trace = new TraceManager(
    edgesBuild.byKey,
    nodesBuild.byId,
    scene,
    () => playback,
    () => {
      hudRef.current?.setPlayback(
        playback.virtualPlaybackIndex,
        trace.merged.length,
        playback.isPlaying && !playback.pollSuspended,
      );
      hudRef.current?.setSessionList(trace.sessions, graph.nodes.length);
    },
    (entry) => {
      hudRef.current?.pushTraceLog(entry);
    },
    () => {
      hudRef.current?.setSessionList(trace.sessions, graph.nodes.length);
    },
  );

  const hud = createHud(
    async (id) => {
      if (!SESSION_ID_RE.test(id)) {
        hud.pushTraceLog({
          sessionId: id,
          event: {
            ts: new Date().toISOString(),
            seq: 0,
            cmd: "session:add",
            elapsed_ms: 0,
            response_summary: {
              status: "error",
              clauses_resolved: [],
              paths_returned: [],
              blocking: false,
            },
            paths_by_id: {},
          },
          line: `Invalid session id: ${id}`,
          color: "#ff6666",
        });
        return;
      }
      await trace.addSession(id);
      hud.setSessionList(trace.sessions, graph.nodes.length);
    },
    (id) => {
      trace.removeSession(id);
      hud.setSessionList(trace.sessions, graph.nodes.length);
    },
    () => {
      if (playback.isPlaying) {
        playback.pause();
        trace.stopReplay();
        trace.setPollingEnabled(false);
      } else {
        playback.resumeLive();
        trace.stopReplay();
        trace.setPollingEnabled(true);
      }
      hud.setPlayback(playback.virtualPlaybackIndex, trace.merged.length, playback.isPlaying && !playback.pollSuspended);
    },
    () => {
      trace.stopReplay();
      playback.pause();
      trace.setPollingEnabled(false);
      trace.stepVirtual();
      hud.setPlayback(playback.virtualPlaybackIndex, trace.merged.length, false);
    },
    () => {
      trace.stopReplay();
      trace.startReplay();
    },
    (s) => {
      playback.speed = s;
    },
    (index) => {
      const resumeLive = playback.isPlaying;
      trace.scrubTo(index, resumeLive);
      hud.setPlayback(playback.virtualPlaybackIndex, trace.merged.length, playback.isPlaying && !playback.pollSuspended);
    },
    (entry: TraceLogEntry) => {
      const ids = trace.flashTraceEvent(entry.sessionId, entry.event);
      flyToClauseIds(ids);
    },
  );
  hudRef.current = hud;

  document.body.appendChild(hud.root);

  const kindCounts = countKinds(graph.nodes);
  hud.setGraphStats(graph, kindCounts);
  hud.setIssues(graph.issues);
  hud.setSessionList(trace.sessions, graph.nodes.length);
  hud.setPlayback(-1, trace.merged.length, true);

  const params = new URLSearchParams(window.location.search);
  for (const id of params.getAll("session")) {
    const t = id.trim();
    if (SESSION_ID_RE.test(t)) void trace.addSession(t);
  }
  hud.setSessionList(trace.sessions, graph.nodes.length);

  const autoDiscoverDisabled = params.has("no_auto");
  if (!autoDiscoverDisabled) {
    const DISCOVER_INTERVAL_MS = 3000;
    const discoverSessions = async () => {
      try {
        const resp = await fetchSessions();
        for (const meta of resp.sessions) {
          if (!meta.trace_enabled) continue;
          if (meta.lifecycle === "ended") continue;
          if (trace.sessions.has(meta.session_id)) continue;
          if (!SESSION_ID_RE.test(meta.session_id)) continue;
          await trace.addSession(meta.session_id);
          hud.setSessionList(trace.sessions, graph.nodes.length);
        }
      } catch {
        /* backend may be temporarily unreachable — ignore */
      }
    };
    void discoverSessions();
    setInterval(() => void discoverSessions(), DISCOVER_INTERVAL_MS);
  }

  const interaction = attachInteraction({
    camera,
    domElement: webglRenderer.domElement,
    nodesById: nodesBuild.byId,
    edgesByKey: edgesBuild.byKey,
    clausesById,
    graphEdges: graph.edges,
    onSelectNode: (id) => {
      if (!id) {
        detail.close();
        return;
      }
      const c = clausesById.get(id);
      if (c) detail.open(c);
    },
    onEdgeHoverInfo: () => {
      /* reserved */
    },
    tooltipEl: tooltip,
  });

  interaction.highlightNode("aspis.entry");

  function loop(t: number): void {
    requestAnimationFrame(loop);
    TWEEN.update(t);
    controls.update();
    updateLabelOpacities(nodesBuild.byId, camera);
    webglRenderer.render(scene, camera);
    css2dRenderer.render(scene, camera);
  }
  requestAnimationFrame(loop);

  window.addEventListener("resize", () => {
    updateEdgeLineResolution(edgesBuild, window.innerWidth, window.innerHeight);
  });
  resize();

  const canvasEl = webglRenderer.domElement;
  document.addEventListener("wheel", (e) => {
    if (e.target === canvasEl) return;
    const t = e.target as HTMLElement;
    if (t.closest(".log-body") || t.closest(".session-list")) return;
    e.preventDefault();
    canvasEl.dispatchEvent(new WheelEvent("wheel", e));
  }, { passive: false });
}

void main();
