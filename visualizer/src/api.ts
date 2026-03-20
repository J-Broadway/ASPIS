import type { GraphResponse, SessionMeta, TraceResponse } from "./types.js";

const DEFAULT_BASE = "http://127.0.0.1:8765";

function apiBase(): string {
  const raw = import.meta.env.VITE_ASPIS_API_BASE;
  return (typeof raw === "string" && raw.length > 0 ? raw : DEFAULT_BASE).replace(/\/$/, "");
}

let workspaceQuery = "";

/** Call once at startup — reads workspace query params from the page URL. */
export function initApiFromLocation(): void {
  const params = new URLSearchParams(window.location.search);
  const forwarded = new URLSearchParams();
  for (const key of ["config", "design_docs_dir", "governance_doc"]) {
    const v = params.get(key);
    if (v !== null && v !== "") forwarded.set(key, v);
  }
  workspaceQuery = forwarded.toString();
}

function withWorkspace(pathWithQuery: string): string {
  if (!workspaceQuery) return pathWithQuery;
  const sep = pathWithQuery.includes("?") ? "&" : "?";
  return `${pathWithQuery}${sep}${workspaceQuery}`;
}

async function parseJsonResponse(res: Response): Promise<unknown> {
  const text = await res.text();
  let data: unknown;
  try {
    data = JSON.parse(text) as unknown;
  } catch {
    throw new Error(`Invalid JSON (HTTP ${res.status})`);
  }
  if (!res.ok) {
    const err = data as { status?: string; issues?: Array<{ code: string; message: string }> };
    if (err.status === "error" && Array.isArray(err.issues) && err.issues.length > 0) {
      const msg = err.issues.map((i) => `${i.code}: ${i.message}`).join("; ");
      throw new Error(msg);
    }
    throw new Error(`HTTP ${res.status}`);
  }
  return data;
}

export async function fetchGraph(includeContent = true): Promise<GraphResponse> {
  const q = includeContent ? "?include_content=true" : "?include_content=false";
  const url = `${apiBase()}/api/graph${q}`;
  const res = await fetch(withWorkspace(url));
  return parseJsonResponse(res) as Promise<GraphResponse>;
}

export async function fetchSessionMeta(sessionId: string): Promise<SessionMeta> {
  const url = `${apiBase()}/api/session/${encodeURIComponent(sessionId)}/meta`;
  const res = await fetch(withWorkspace(url));
  return parseJsonResponse(res) as Promise<SessionMeta>;
}

export async function pollTrace(
  sessionId: string,
  afterSeq: number,
  limit = 100,
): Promise<TraceResponse> {
  const url = `${apiBase()}/api/session/${encodeURIComponent(sessionId)}/trace?after_seq=${afterSeq}&limit=${limit}`;
  const res = await fetch(withWorkspace(url));
  return parseJsonResponse(res) as Promise<TraceResponse>;
}

export interface SessionsListResponse {
  schema_version: string;
  sessions: import("./types.js").SessionMeta[];
}

export async function fetchSessions(): Promise<SessionsListResponse> {
  const url = `${apiBase()}/api/sessions`;
  const res = await fetch(withWorkspace(url));
  return parseJsonResponse(res) as Promise<SessionsListResponse>;
}

export { apiBase };
