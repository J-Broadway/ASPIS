import type { Color } from "three";

export interface ClauseNode {
  id: string;
  meta: boolean;
  kind: "contract" | "route" | "guidance" | "information";
  status: string;
  owner_doc: string;
  paths: string[];
  content?: string;
  keywords?: string[];
  registry_slots?: Record<string, string>;
}

export interface GraphEdge {
  from: string;
  to: string;
}

export interface GraphResponse {
  schema_version: string;
  docs_root: string;
  nodes: ClauseNode[];
  edges: GraphEdge[];
  issues: Array<{ code: string; message: string }>;
}

export interface TraceEvent {
  ts: string;
  seq: number;
  cmd: string;
  elapsed_ms: number;
  response_summary: {
    status: string;
    clauses_resolved: string[];
    paths_returned: string[];
    blocking: boolean;
  };
  paths_by_id: Record<string, string[]>;
  context?: Record<string, unknown>;
}

export interface TraceLogEntry {
  sessionId: string;
  event: TraceEvent;
  line: string;
  color: string;
}

export interface TraceResponse {
  schema_version: string;
  trace_enabled: boolean;
  events: TraceEvent[];
  max_seq: number;
}

export interface SessionMeta {
  schema_version: string;
  session_id: string;
  name: string;
  lifecycle: string;
  started_at: string;
  ended_at: string | null;
  command_count: number;
  next_seq: number;
  trace_enabled: boolean;
  trace_full_default: boolean;
  surface_kind: string | null;
  namespace: string | null;
  clauses_touched_count: number;
}

export interface SessionTraceState {
  sessionId: string;
  color: Color;
  label: string;
  lastSeq: number;
  visitedNodes: Set<string>;
  visitedEdges: Set<string>;
  events: TraceEvent[];
  pollTimer: ReturnType<typeof setInterval> | null;
  meta: SessionMeta | null;
  status: "polling" | "paused" | "ended" | "error" | "idle";
  errorMessage?: string;
}

export interface MergedTraceEvent {
  sessionId: string;
  event: TraceEvent;
  virtualIndex: number;
}
