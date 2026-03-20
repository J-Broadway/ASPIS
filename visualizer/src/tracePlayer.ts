import * as THREE from "three";
import TWEEN from "@tweenjs/tween.js";
import { fetchSessionMeta, pollTrace } from "./api.js";
import type { EdgeVisual } from "./edges.js";
import { resetEdgeStyle, setEdgeHighlight } from "./edges.js";
import type { NodeVisual } from "./nodes.js";
import { pulseNodeScale, setNodeLabelVisited } from "./nodes.js";
import {
  buildMergedTimeline,
  nextEventDelayMs,
  type PlaybackController,
  type PlaybackSpeed,
} from "./playback.js";
import type { MergedTraceEvent, SessionTraceState, TraceEvent, TraceLogEntry } from "./types.js";

const SESSION_PALETTE = [
  { hex: 0x00e5ff, label: "Agent A" },
  { hex: 0xff00e5, label: "Agent B" },
  { hex: 0xffab00, label: "Agent C" },
  { hex: 0x76ff03, label: "Agent D" },
];

export const SESSION_ID_RE = /^[a-f0-9]{32}$/;

function kindBaseHex(kind: NodeVisual["kind"]): number {
  const m: Record<NodeVisual["kind"], number> = {
    contract: 0x00e5ff,
    route: 0xff00e5,
    guidance: 0xffab00,
    information: 0xe0e0e0,
  };
  return m[kind];
}

export class TraceManager {
  sessions = new Map<string, SessionTraceState>();
  merged: MergedTraceEvent[] = [];
  private sessionIndex = 0;
  private replayTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly edgesByKey: Map<string, EdgeVisual>,
    private readonly nodesById: Map<string, NodeVisual>,
    private readonly scene: THREE.Scene,
    private readonly getPlayback: () => PlaybackController,
    public readonly onMergedUpdate: () => void,
    public readonly onLog: (entry: TraceLogEntry) => void,
    public readonly onStatus: (sessionId: string, status: SessionTraceState["status"], err?: string) => void,
  ) {}

  private paletteEntry(i: number) {
    const p = SESSION_PALETTE[i % SESSION_PALETTE.length]!;
    const label =
      i < SESSION_PALETTE.length
        ? p.label
        : `Agent ${String.fromCharCode(65 + (i % 26))}`;
    return { color: new THREE.Color(p.hex), label };
  }

  private refreshMerged(): void {
    this.merged = buildMergedTimeline(this.sessions);
    this.onMergedUpdate();
  }

  async addSession(sessionId: string): Promise<void> {
    if (this.sessions.has(sessionId)) return;
    const idx = this.sessionIndex++;
    const { color, label } = this.paletteEntry(idx);
    const st: SessionTraceState = {
      sessionId,
      color,
      label,
      lastSeq: 0,
      visitedNodes: new Set(),
      visitedEdges: new Set(),
      events: [],
      pollTimer: null,
      meta: null,
      status: "idle",
    };
    this.sessions.set(sessionId, st);
    this.getPlayback().pollAfterSeq.set(sessionId, 0);
    try {
      const meta = await fetchSessionMeta(sessionId);
      st.meta = meta;
      if (!meta.trace_enabled) {
        st.status = "error";
        st.errorMessage = "trace_enabled is false";
        this.onStatus(sessionId, "error", st.errorMessage);
        return;
      }
      st.status = this.getPlayback().pollSuspended ? "paused" : "polling";
      this.onStatus(sessionId, st.status);
      this.armPoll(sessionId);
    } catch (e) {
      st.status = "error";
      st.errorMessage = e instanceof Error ? e.message : String(e);
      this.onStatus(sessionId, "error", st.errorMessage);
    }
  }

  removeSession(sessionId: string): void {
    const st = this.sessions.get(sessionId);
    if (!st) return;
    if (st.pollTimer) {
      clearInterval(st.pollTimer);
      st.pollTimer = null;
    }
    this.sessions.delete(sessionId);
    this.getPlayback().pollAfterSeq.delete(sessionId);
    this.refreshMerged();
  }

  private armPoll(sessionId: string): void {
    const st = this.sessions.get(sessionId);
    if (!st || st.pollTimer) return;
    const pb = this.getPlayback();
    if (pb.pollSuspended) return;

    const tick = async () => {
      const play = this.getPlayback();
      if (play.pollSuspended) return;
      const s = this.sessions.get(sessionId);
      if (!s || s.status === "error") return;

      try {
        const afterSeq = play.pollAfterSeq.get(sessionId) ?? 0;
        const tr = await pollTrace(sessionId, afterSeq, 100);
        if (!tr.trace_enabled) return;
        if (tr.events.length > 0) {
          const maxInBatch = Math.max(...tr.events.map((e) => e.seq));
          s.lastSeq = Math.max(s.lastSeq, maxInBatch);
          play.pollAfterSeq.set(sessionId, maxInBatch);
          let mergedChanged = false;
          for (const ev of tr.events) {
            const seen = s.events.some((existing) => existing.seq === ev.seq);
            if (!seen) {
              s.events.push(ev);
              mergedChanged = true;
              this.onLog({
                sessionId,
                event: ev,
                line: `[${ev.seq}] [${s.label}] ${ev.cmd} → ${(ev.response_summary?.clauses_resolved ?? []).join(", ")} (${ev.elapsed_ms} ms)`,
                color: `#${s.color.getHexString()}`,
              });
            }
            this.dispatchEventAnimation(sessionId, s, ev);
          }
          if (mergedChanged) this.refreshMerged();
          const liveTail = this.findMergedIndex(sessionId, maxInBatch);
          if (liveTail >= 0) {
            play.virtualPlaybackIndex = liveTail;
            this.onMergedUpdate();
          }
        } else {
          const nextMeta = await fetchSessionMeta(sessionId);
          s.meta = nextMeta;
          if (nextMeta.lifecycle === "ended") {
            s.status = "ended";
            this.onStatus(sessionId, "ended");
            if (s.pollTimer) {
              clearInterval(s.pollTimer);
              s.pollTimer = null;
            }
          }
        }
      } catch (e) {
        s.status = "error";
        s.errorMessage = e instanceof Error ? e.message : String(e);
        this.onStatus(sessionId, "error", s.errorMessage);
        if (s.pollTimer) {
          clearInterval(s.pollTimer);
          s.pollTimer = null;
        }
      }
    };

    const ms = this.getPlayback().getPollIntervalMs();
    st.pollTimer = window.setInterval(() => {
      void tick();
    }, ms);
    void tick();
  }

  private findMergedIndex(sessionId: string, seq: number): number {
    for (let i = this.merged.length - 1; i >= 0; i--) {
      const row = this.merged[i]!;
      if (row.sessionId === sessionId && row.event.seq === seq) return i;
    }
    return -1;
  }

  dispatchEventAnimation(_sessionId: string, st: SessionTraceState, ev: TraceEvent): void {
    const col = st.color.getHex();
    let delay = 0;
    for (const [fromId, targets] of Object.entries(ev.paths_by_id ?? {})) {
      for (const toId of targets) {
        const key = `${fromId}→${toId}`;
        const edge = this.edgesByKey.get(key);
        const fromN = this.nodesById.get(fromId);
        const toN = this.nodesById.get(toId);
        st.visitedNodes.add(fromId);
        st.visitedNodes.add(toId);
        st.visitedEdges.add(key);
        if (edge) {
          const d = delay;
          window.setTimeout(() => this.pulseEdge(edge, col), d);
          if (fromN && toN) {
            window.setTimeout(() => this.packetAlong(edge, fromN, toN, col), d);
          }
          delay += 100;
        }
      }
    }
    this.applyVisitedStyle(st);
  }

  private pulseEdge(edge: EdgeVisual, colorHex: number): void {
    const scale = this.getPlayback().getAnimationScale();
    const dur = 600 * scale;
    const start = { t: 0 };
    new TWEEN.Tween(start)
      .to({ t: 1 }, dur)
      .onUpdate(() => {
        const u = start.t < 0.5 ? start.t * 2 : 2 - start.t * 2;
        const op = 0.3 + u * 0.55;
        setEdgeHighlight(edge, colorHex, op);
      })
      .onComplete(() => {
        resetEdgeStyle(edge);
      })
      .start();
  }

  private packetAlong(edge: EdgeVisual, _fromN: NodeVisual, _toN: NodeVisual, colorHex: number): void {
    const scale = this.getPlayback().getAnimationScale();
    const dur = 400 * scale;
    const geom = new THREE.SphereGeometry(0.12, 10, 10);
    const mat = new THREE.MeshStandardMaterial({
      color: colorHex,
      emissive: colorHex,
      emissiveIntensity: 0.8,
    });
    const mesh = new THREE.Mesh(geom, mat);
    const curve = edge.curve;
    const start = { u: 0 };
    mesh.position.copy(curve.getPoint(0));
    this.scene.add(mesh);
    new TWEEN.Tween(start)
      .to({ u: 1 }, dur)
      .onUpdate(() => {
        mesh.position.copy(curve.getPoint(start.u));
      })
      .onComplete(() => {
        this.scene.remove(mesh);
        geom.dispose();
        mat.dispose();
      })
      .start();
  }

  private applyVisitedStyle(st: SessionTraceState): void {
    const c = st.color;
    for (const id of st.visitedNodes) {
      const nv = this.nodesById.get(id);
      if (!nv) continue;
      const mat = nv.mesh.material as THREE.MeshStandardMaterial;
      mat.emissive.lerp(c, 0.12);
      mat.emissiveIntensity = Math.min(0.55, nv.baseEmissive + 0.2);
      setNodeLabelVisited(nv, true);
    }
    for (const key of st.visitedEdges) {
      const ev = this.edgesByKey.get(key);
      if (!ev) continue;
      setEdgeHighlight(ev, c.getHex(), 0.42);
    }
  }

  applyMergedRangeInstant(upToExclusive: number): void {
    this.clearVisitedVisual();
    for (let i = 0; i < upToExclusive && i < this.merged.length; i++) {
      const { sessionId, event } = this.merged[i]!;
      const st = this.sessions.get(sessionId);
      if (!st) continue;
      for (const [fromId, targets] of Object.entries(event.paths_by_id ?? {})) {
        for (const toId of targets) {
          st.visitedNodes.add(fromId);
          st.visitedNodes.add(toId);
          st.visitedEdges.add(`${fromId}→${toId}`);
        }
      }
    }
    for (const st of this.sessions.values()) this.applyVisitedStyle(st);
  }

  flashTraceEvent(sessionId: string, event: TraceEvent): string[] {
    const st = this.sessions.get(sessionId);
    const colorHex = st?.color.getHex() ?? SESSION_PALETTE[0]!.hex;
    const focus = new Set<string>(event.response_summary?.clauses_resolved ?? []);
    let delay = 0;
    for (const [fromId, targets] of Object.entries(event.paths_by_id ?? {})) {
      focus.add(fromId);
      const fromNode = this.nodesById.get(fromId);
      if (fromNode) pulseNodeScale(fromNode, 420);
      for (const toId of targets) {
        focus.add(toId);
        const edge = this.edgesByKey.get(`${fromId}→${toId}`);
        const toNode = this.nodesById.get(toId);
        if (edge) window.setTimeout(() => this.pulseEdge(edge, colorHex), delay);
        if (toNode) window.setTimeout(() => pulseNodeScale(toNode, 420), delay);
        delay += 90;
      }
    }
    return [...focus];
  }

  clearVisitedVisual(): void {
    for (const st of this.sessions.values()) {
      st.visitedNodes.clear();
      st.visitedEdges.clear();
    }
    for (const nv of this.nodesById.values()) {
      const mat = nv.mesh.material as THREE.MeshStandardMaterial;
      mat.emissive.setHex(kindBaseHex(nv.kind));
      mat.emissiveIntensity = nv.baseEmissive;
      setNodeLabelVisited(nv, false);
    }
    for (const ev of this.edgesByKey.values()) resetEdgeStyle(ev);
  }

  stepVirtual(): void {
    this.stopReplay();
    const pb = this.getPlayback();
    const next = pb.virtualPlaybackIndex + 1;
    if (next >= this.merged.length) return;
    const { sessionId, event } = this.merged[next]!;
    const st = this.sessions.get(sessionId);
    if (st) this.dispatchEventAnimation(sessionId, st, event);
    pb.virtualPlaybackIndex = next;
    this.onMergedUpdate();
  }

  startReplay(): void {
    this.stopReplay();
    this.clearVisitedVisual();
    const pb = this.getPlayback();
    pb.replayStart();
    pb.virtualPlaybackIndex = -1;
    let i = 0;
    const run = (prev: TraceEvent | null) => {
      if (i >= this.merged.length) {
        this.replayTimer = null;
        pb.replayEndResumePoll();
        this.onMergedUpdate();
        return;
      }
      const { sessionId, event } = this.merged[i]!;
      const st = this.sessions.get(sessionId);
      if (st) this.dispatchEventAnimation(sessionId, st, event);
      pb.virtualPlaybackIndex = i;
      this.onMergedUpdate();
      i++;
      const delay = nextEventDelayMs(prev, event, pb.speed as PlaybackSpeed);
      this.replayTimer = window.setTimeout(() => run(event), delay);
    };
    this.replayTimer = window.setTimeout(() => run(null), 0);
  }

  stopReplay(): void {
    if (this.replayTimer) {
      clearTimeout(this.replayTimer);
      this.replayTimer = null;
    }
  }

  scrubTo(index: number, resumeLive: boolean): void {
    this.stopReplay();
    const pb = this.getPlayback();
    this.setPollingEnabled(false);
    this.applyMergedRangeInstant(index);
    if (index >= 0 && index < this.merged.length) {
      const { sessionId, event } = this.merged[index]!;
      const st = this.sessions.get(sessionId);
      if (st) this.dispatchEventAnimation(sessionId, st, event);
      pb.recomputePollCursorsFromMerged(this.merged, index);
      pb.virtualPlaybackIndex = index;
    } else {
      pb.recomputePollCursorsFromMerged(this.merged, -1);
      pb.virtualPlaybackIndex = -1;
    }
    if (resumeLive) {
      pb.resumeLive();
      this.setPollingEnabled(true);
    } else {
      pb.pause();
      this.setPollingEnabled(false);
    }
    this.onMergedUpdate();
  }

  setPollingEnabled(enabled: boolean): void {
    const pb = this.getPlayback();
    pb.pollSuspended = !enabled;
    if (!enabled) {
      for (const st of this.sessions.values()) {
        if (st.pollTimer) {
          clearInterval(st.pollTimer);
          st.pollTimer = null;
        }
        if (st.status === "polling") {
          st.status = "paused";
          this.onStatus(st.sessionId, "paused");
        }
      }
    } else {
      for (const st of this.sessions.values()) {
        if (st.status === "paused" || st.status === "polling") {
          if (!st.pollTimer && st.meta?.trace_enabled) {
            st.status = "polling";
            this.onStatus(st.sessionId, "polling");
            this.armPoll(st.sessionId);
          }
        }
      }
    }
  }
}
