import { marked } from "marked";
import type { ClauseNode } from "./types.js";

export interface DetailPanelApi {
  open: (clause: ClauseNode) => void;
  close: () => void;
  root: HTMLElement;
}

export function createDetailPanel(
  onNavigate: (targetId: string) => void,
  onClose: () => void,
): DetailPanelApi {
  const root = document.createElement("aside");
  root.className = "detail-panel";
  root.innerHTML = `
    <div class="detail-panel-inner">
      <header class="detail-header">
        <button type="button" class="detail-close" aria-label="Close">×</button>
        <h2 class="detail-title"></h2>
        <div class="detail-badges"></div>
      </header>
      <div class="detail-body">
        <section class="detail-section"><h3>Content</h3><div class="detail-content markdown-body"></div></section>
        <section class="detail-section"><h3>Paths</h3><ul class="detail-paths"></ul></section>
        <section class="detail-section detail-keywords"><h3>Keywords</h3><div class="kw-tags"></div></section>
        <section class="detail-section detail-slots"><h3>Registry slots</h3><dl class="slots-dl"></dl></section>
      </div>
    </div>
  `;
  root.style.display = "none";

  const titleEl = root.querySelector(".detail-title") as HTMLElement;
  const badgesEl = root.querySelector(".detail-badges") as HTMLElement;
  const contentEl = root.querySelector(".detail-content") as HTMLElement;
  const pathsEl = root.querySelector(".detail-paths") as HTMLElement;
  const kwEl = root.querySelector(".kw-tags") as HTMLElement;
  const slotsEl = root.querySelector(".slots-dl") as HTMLElement;
  const kwSection = root.querySelector(".detail-keywords") as HTMLElement;
  const slotsSection = root.querySelector(".detail-slots") as HTMLElement;

  root.querySelector(".detail-close")?.addEventListener("click", () => {
    onClose();
  });

  const open = (clause: ClauseNode) => {
    root.style.display = "block";
    titleEl.textContent = clause.id;
    badgesEl.innerHTML = "";
    const kind = document.createElement("span");
    kind.className = `badge badge-kind badge-${clause.kind}`;
    kind.textContent = clause.kind;
    badgesEl.appendChild(kind);
    const st = document.createElement("span");
    st.className = "badge badge-status";
    st.textContent = clause.status;
    badgesEl.appendChild(st);
    if (clause.meta) {
      const m = document.createElement("span");
      m.className = "badge badge-meta";
      m.textContent = "meta";
      badgesEl.appendChild(m);
    }

    const raw = clause.content ?? "_No content._";
    contentEl.innerHTML = String(marked.parse(raw, { async: false }));

    pathsEl.innerHTML = "";
    for (const p of clause.paths ?? []) {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = "#";
      a.textContent = p;
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        onNavigate(p);
      });
      li.appendChild(a);
      pathsEl.appendChild(li);
    }

    if (clause.keywords?.length) {
      kwSection.style.display = "block";
      kwEl.innerHTML = "";
      for (const k of clause.keywords) {
        const t = document.createElement("span");
        t.className = "tag";
        t.textContent = k;
        kwEl.appendChild(t);
      }
    } else {
      kwSection.style.display = "none";
    }

    if (clause.registry_slots && Object.keys(clause.registry_slots).length > 0) {
      slotsSection.style.display = "block";
      slotsEl.innerHTML = "";
      for (const [k, v] of Object.entries(clause.registry_slots)) {
        const dt = document.createElement("dt");
        dt.textContent = k;
        const dd = document.createElement("dd");
        dd.textContent = v;
        slotsEl.appendChild(dt);
        slotsEl.appendChild(dd);
      }
    } else {
      slotsSection.style.display = "none";
    }
  };

  const close = () => {
    root.style.display = "none";
  };

  return { open, close, root };
}
