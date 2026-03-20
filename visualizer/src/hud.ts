import type { ClauseNode, GraphResponse, SessionTraceState, TraceLogEntry } from "./types.js";

export interface HudApi {
  root: HTMLElement;
  setGraphStats: (g: GraphResponse, kindCounts: Record<string, number>) => void;
  setIssues: (issues: GraphResponse["issues"]) => void;
  setSessionList: (sessions: Map<string, SessionTraceState>, totalNodes: number) => void;
  pushTraceLog: (entry: TraceLogEntry) => void;
  setPlayback: (virtualIndex: number, total: number, isPlaying: boolean) => void;
  toggleLegend: () => void;
}

export function createHud(
  onAddSession: (id: string) => void,
  onRemoveSession: (id: string) => void,
  onPlayPause: () => void,
  onStep: () => void,
  onReplay: () => void,
  onSpeed: (s: 0.5 | 1 | 2 | 4) => void,
  onScrub: (index: number) => void,
  onTraceLogSelect: (entry: TraceLogEntry) => void,
): HudApi {
  const root = document.createElement("div");
  root.className = "hud-root";

  root.innerHTML = `
    <div class="hud-stats panel"></div>
    <div class="hud-sessions panel">
      <div class="hud-sessions-head">
        <input type="text" class="session-input" placeholder="session id (32 hex)" />
        <button type="button" class="btn-add-session">Add</button>
        <button type="button" class="btn-url-sessions">Add from URL</button>
      </div>
      <ul class="session-list"></ul>
    </div>
    <div class="hud-issues panel collapsible"></div>
    <div class="hud-playback panel">
      <button type="button" class="btn-play">Pause</button>
      <button type="button" class="btn-step">Step</button>
      <label>Speed <select class="sel-speed">
        <option value="0.5">0.5x</option>
        <option value="1" selected>1x</option>
        <option value="2">2x</option>
        <option value="4">4x</option>
      </select></label>
      <button type="button" class="btn-replay">Replay</button>
      <input type="range" class="scrub" min="0" max="0" value="0" />
      <span class="scrub-label">0 / 0</span>
    </div>
    <div class="hud-log panel">
      <div class="log-header">Trace log</div>
      <div class="log-body"></div>
    </div>
    <button type="button" class="legend-toggle">Legend</button>
    <div class="hud-legend panel" style="display:none"></div>
  `;

  const statsEl = root.querySelector(".hud-stats") as HTMLElement;
  const issuesEl = root.querySelector(".hud-issues") as HTMLElement;
  const sessionList = root.querySelector(".session-list") as HTMLElement;
  const logBody = root.querySelector(".log-body") as HTMLElement;
  const scrub = root.querySelector(".scrub") as HTMLInputElement;
  const scrubLabel = root.querySelector(".scrub-label") as HTMLElement;
  const btnPlay = root.querySelector(".btn-play") as HTMLButtonElement;
  const legendEl = root.querySelector(".hud-legend") as HTMLElement;

  root.querySelector(".btn-add-session")?.addEventListener("click", () => {
    const inp = root.querySelector(".session-input") as HTMLInputElement;
    onAddSession(inp.value.trim());
  });
  root.querySelector(".btn-url-sessions")?.addEventListener("click", () => {
    const params = new URLSearchParams(window.location.search);
    for (const id of params.getAll("session")) onAddSession(id.trim());
  });

  btnPlay.addEventListener("click", () => onPlayPause());
  root.querySelector(".btn-step")?.addEventListener("click", () => onStep());
  root.querySelector(".btn-replay")?.addEventListener("click", () => onReplay());
  root.querySelector(".sel-speed")?.addEventListener("change", (ev) => {
    const v = Number((ev.target as HTMLSelectElement).value);
    if (v === 0.5 || v === 1 || v === 2 || v === 4) onSpeed(v);
  });

  scrub.addEventListener("input", () => {
    onScrub(Number(scrub.value));
  });

  root.querySelector(".legend-toggle")?.addEventListener("click", () => {
    legendEl.style.display = legendEl.style.display === "none" ? "block" : "none";
  });

  const setGraphStats = (g: GraphResponse, kindCounts: Record<string, number>) => {
    const parts = Object.entries(kindCounts)
      .filter(([, n]) => n > 0)
      .map(([k, n]) => `${n} ${k}`)
      .join(" · ");
    statsEl.innerHTML = `
      <div class="stat-docs">${escapeHtml(g.docs_root)}</div>
      <div class="stat-counts">${g.nodes.length} nodes · ${g.edges.length} edges</div>
      <div class="stat-kinds">${parts}</div>
    `;
  };

  const setIssues = (issues: GraphResponse["issues"]) => {
    if (!issues.length) {
      issuesEl.style.display = "none";
      return;
    }
    issuesEl.style.display = "block";
    issuesEl.innerHTML = `<div class="issues-title">Issues (${issues.length})</div><ul>${issues.map((i) => `<li><code>${escapeHtml(i.code)}</code> ${escapeHtml(i.message)}</li>`).join("")}</ul>`;
  };

  const setSessionList = (sessions: Map<string, SessionTraceState>, totalNodes: number) => {
    sessionList.innerHTML = "";
    for (const st of sessions.values()) {
      const cov = totalNodes ? ((st.visitedNodes.size / totalNodes) * 100).toFixed(1) : "0";
      const li = document.createElement("li");
      li.innerHTML = `<span class="sess-dot" style="background:#${st.color.getHexString()}"></span>
        <span class="sess-label">${escapeHtml(st.label)}</span>
        <span class="sess-id">${st.sessionId.slice(0, 8)}…</span>
        <span class="sess-st">${st.status}</span>
        <span class="sess-cov">${cov}%</span>
        <button type="button" data-sid="${escapeHtml(st.sessionId)}">Remove</button>`;
      li.querySelector("button")?.addEventListener("click", () => onRemoveSession(st.sessionId));
      sessionList.appendChild(li);
    }
  };

  const pushTraceLog = (entry: TraceLogEntry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "log-entry";
    button.style.color = entry.color;
    button.textContent = entry.line;
    button.title = "Flash trace path and center graph";
    button.addEventListener("click", () => onTraceLogSelect(entry));
    logBody.appendChild(button);
    logBody.scrollTop = logBody.scrollHeight;
  };

  const setPlayback = (virtualIndex: number, total: number, isPlaying: boolean) => {
    scrub.max = String(Math.max(0, total - 1));
    scrub.value = String(Math.max(0, virtualIndex));
    scrubLabel.textContent = `${virtualIndex + 1} / ${total}`;
    btnPlay.textContent = isPlaying ? "Pause" : "Play";
  };

  legendEl.innerHTML = `
    <div><strong>Kinds</strong></div>
    <div>● contract (sphere) cyan</div>
    <div>● route (octahedron) magenta</div>
    <div>● guidance (dodecahedron) amber</div>
    <div>● information (box) white</div>
  `;

  return {
    root,
    setGraphStats,
    setIssues,
    setSessionList,
    pushTraceLog,
    setPlayback,
    toggleLegend: () => {
      legendEl.style.display = legendEl.style.display === "none" ? "block" : "none";
    },
  };
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function countKinds(nodes: ClauseNode[]): Record<string, number> {
  const o: Record<string, number> = { contract: 0, route: 0, guidance: 0, information: 0 };
  for (const n of nodes) {
    o[n.kind] = (o[n.kind] ?? 0) + 1;
  }
  return o;
}
