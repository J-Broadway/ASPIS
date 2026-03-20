import type { MergedTraceEvent, SessionTraceState, TraceEvent } from "./types.js";

export type PlaybackSpeed = 0.5 | 1 | 2 | 4;

export class PlaybackController {
  /** Per-session HTTP poll cursor — monotonic while polling. */
  pollAfterSeq = new Map<string, number>();
  /** Position in merged virtual timeline (inclusive: state includes event at this index). */
  virtualPlaybackIndex = -1;
  isPlaying = true;
  speed: PlaybackSpeed = 1;
  /** When true, live polling is suspended (pause, step, scrub, replay). */
  pollSuspended = false;

  getPollIntervalMs(): number {
    return 500 / this.speed;
  }

  getAnimationScale(): number {
    return 1 / this.speed;
  }

  /**
   * Recompute pollAfterSeq from merged events [0..N] inclusive per session.
   * Used after scrub / resume-to-live.
   */
  recomputePollCursorsFromMerged(merged: MergedTraceEvent[], throughInclusive: number): void {
    const allSessions = new Set<string>();
    const maxBySession = new Map<string, number>();
    for (const row of merged) allSessions.add(row.sessionId);
    for (let i = 0; i <= throughInclusive && i < merged.length; i++) {
      const { sessionId, event } = merged[i]!;
      const prev = maxBySession.get(sessionId) ?? -1;
      if (event.seq > prev) maxBySession.set(sessionId, event.seq);
    }
    for (const sid of allSessions) {
      this.pollAfterSeq.set(sid, maxBySession.get(sid) ?? 0);
    }
  }

  /** Max seq seen in merged events for one session up through inclusive index. */
  maxSeqForSession(merged: MergedTraceEvent[], sessionId: string, throughInclusive: number): number {
    let m = -1;
    for (let i = 0; i <= throughInclusive && i < merged.length; i++) {
      const me = merged[i]!;
      if (me.sessionId === sessionId) m = Math.max(m, me.event.seq);
    }
    return m;
  }

  pause(): void {
    this.isPlaying = false;
    this.pollSuspended = true;
  }

  resumeLive(): void {
    this.isPlaying = true;
    this.pollSuspended = false;
  }

  replayStart(): void {
    this.virtualPlaybackIndex = -1;
    this.pollSuspended = true;
    this.isPlaying = true;
  }

  replayEndResumePoll(): void {
    this.pollSuspended = false;
  }
}

export function buildMergedTimeline(
  sessions: Map<string, SessionTraceState>,
): MergedTraceEvent[] {
  const out: MergedTraceEvent[] = [];
  for (const [sessionId, st] of sessions) {
    for (const ev of st.events) {
      out.push({ sessionId, event: ev, virtualIndex: 0 });
    }
  }
  out.sort((a, b) => {
    const ta = Date.parse(a.event.ts);
    const tb = Date.parse(b.event.ts);
    if (ta !== tb) return ta - tb;
    if (a.sessionId !== b.sessionId) return a.sessionId.localeCompare(b.sessionId);
    return a.event.seq - b.event.seq;
  });
  for (let i = 0; i < out.length; i++) {
    const row = out[i];
    if (row) row.virtualIndex = i;
  }
  return out;
}

export function nextEventDelayMs(prev: TraceEvent | null, cur: TraceEvent, speed: PlaybackSpeed): number {
  if (!prev) return 0;
  const a = Date.parse(prev.ts);
  const b = Date.parse(cur.ts);
  const d = Math.max(0, b - a);
  return d / speed;
}
