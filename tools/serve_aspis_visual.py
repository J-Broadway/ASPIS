#!/usr/bin/env python3
"""
Local HTTP bridge for an ASPIS session visualizer (stdlib only).

Always binds to 127.0.0.1. API JSON responses set Access-Control-Allow-Origin: *
only because the listen address is loopback — safe for local Vite/Three.js dev.
Do not change the bind address to 0.0.0.0 while keeping wildcard CORS.

Contracts:
- GET /api/graph returns the same JSON object as `python3 tools/aspis.py visual:graph`
  (top-level schema_version: aspis.registry_graph.v1).
- Session endpoints wrap data with schema_version: aspis.visual_api.v1.
- Errors (non-2xx JSON): {"status":"error","issues":[{"code":"...","message":"..."}]}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import graph_export as graph_export_runtime
import session_store as session_store_runtime
import trace_io as trace_io_runtime
import workspace as workspace_runtime

# Import workspace resolution from CLI module (same semantics as clause/session commands).
import aspis as aspis_runtime

VISUAL_API_SCHEMA_VERSION = "aspis.visual_api.v1"
SESSION_ID_RE = re.compile(r"^[a-f0-9]{32}$")
DEFAULT_TRACE_LIMIT = 100
MAX_TRACE_LIMIT = 1000
BIND_HOST = "127.0.0.1"


def _error_body(code: str, message: str) -> bytes:
    payload = {"status": "error", "issues": [{"code": code, "message": message}]}
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _query_first(qs: Dict[str, List[str]], key: str) -> Optional[str]:
    vals = qs.get(key)
    if not vals:
        return None
    return vals[0]


def _resolve_workspace(
    qs: Dict[str, List[str]],
    cwd: Path,
    defaults: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[Optional[Any], Optional[Path], Optional[Path], Optional[bytes]]:
    defaults = defaults or {}
    config = _query_first(qs, "config") or defaults.get("config")
    design_docs_dir = _query_first(qs, "design_docs_dir") or defaults.get("design_docs_dir")
    governance_doc = _query_first(qs, "governance_doc") or defaults.get("governance_doc")
    try:
        manifest, docs_root, gov = aspis_runtime._resolve_clause_runtime_paths_with_manifest(
            design_docs_dir,
            governance_doc,
            config,
            cwd,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        return None, None, None, _error_body("PATH_RESOLUTION", str(exc))
    return manifest, docs_root, gov, None


def _parse_include_content(qs: Dict[str, List[str]]) -> bool:
    raw = (_query_first(qs, "include_content") or "").strip().lower()
    if not raw:
        return False
    return raw in ("true", "1", "yes")


def _parse_after_seq_limit(qs: Dict[str, List[str]]) -> Tuple[Optional[int], Optional[int], Optional[bytes]]:
    raw_after = _query_first(qs, "after_seq") or "0"
    try:
        after_seq = int(raw_after)
    except ValueError:
        return None, None, _error_body("INVALID_INPUT", "Query after_seq must be an integer.")
    if after_seq < 0:
        return None, None, _error_body("INVALID_INPUT", "Query after_seq must be non-negative.")
    raw_limit = _query_first(qs, "limit")
    if raw_limit is None:
        limit = DEFAULT_TRACE_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            return None, None, _error_body("INVALID_INPUT", "Query limit must be an integer.")
    if limit < 1:
        return None, None, _error_body("INVALID_INPUT", "Query limit must be at least 1.")
    if limit > MAX_TRACE_LIMIT:
        limit = MAX_TRACE_LIMIT
    return after_seq, limit, None


def _session_meta_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    touched = state.get("clauses_touched_success") or []
    if isinstance(touched, list):
        tc = len(touched)
    else:
        tc = 0
    return {
        "schema_version": VISUAL_API_SCHEMA_VERSION,
        "session_id": state.get("session_id"),
        "name": state.get("name"),
        "lifecycle": state.get("lifecycle"),
        "started_at": state.get("started_at"),
        "ended_at": state.get("ended_at"),
        "command_count": state.get("command_count"),
        "next_seq": state.get("next_seq"),
        "trace_enabled": state.get("trace_enabled"),
        "trace_full_default": state.get("trace_full_default"),
        "surface_kind": state.get("surface_kind"),
        "namespace": state.get("namespace"),
        "clauses_touched_count": tc,
    }


class AspisVisualRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(
        self,
        status: int,
        body: bytes,
        *,
        content_type: str = "application/json",
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if getattr(self.server, "allow_cors", False):
            self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if not getattr(self.server, "allow_cors", False):
            self.send_error(405)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path or "/"
        qs = parse_qs(parsed.query, keep_blank_values=False)
        cwd = Path.cwd()
        workspace_defaults = getattr(self.server, "workspace_defaults", {})

        if path == "/health":
            self._send(200, b'{"status":"ok"}\n')
            return

        if path == "/api/sessions":
            _manifest, docs_root, _gov, err = _resolve_workspace(qs, cwd, workspace_defaults)
            if err is not None:
                self._send(400, err)
                return
            assert docs_root is not None
            sessions_dir = workspace_runtime.sessions_root(docs_root)
            result: List[Dict[str, Any]] = []
            if sessions_dir.is_dir():
                for entry in sorted(sessions_dir.iterdir()):
                    if not entry.is_dir():
                        continue
                    sjson = entry / "session.json"
                    if not sjson.is_file():
                        continue
                    try:
                        state = workspace_runtime.read_json_file(sjson)
                    except (OSError, json.JSONDecodeError):
                        continue
                    if not state.get("trace_enabled"):
                        continue
                    result.append(_session_meta_payload(state))
            payload = {
                "schema_version": VISUAL_API_SCHEMA_VERSION,
                "sessions": result,
            }
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self._send(200, raw + b"\n")
            return

        if path == "/api/graph":
            _manifest, docs_root, _gov, err = _resolve_workspace(qs, cwd, workspace_defaults)
            if err is not None:
                self._send(400, err)
                return
            assert docs_root is not None
            include_content = _parse_include_content(qs)
            try:
                doc = graph_export_runtime.build_registry_graph_document(
                    docs_root,
                    include_content=include_content,
                )
            except (OSError, ValueError) as exc:
                self._send(500, _error_body("REGISTRY_LOAD_FAILED", str(exc)))
                return
            raw = json.dumps(doc, separators=(",", ":")).encode("utf-8")
            self._send(200, raw + b"\n")
            return

        parts = [p for p in path.split("/") if p]
        if (
            len(parts) == 4
            and parts[0] == "api"
            and parts[1] == "session"
            and parts[3] in {"meta", "trace"}
        ):
            session_id = parts[2]
            tail = parts[3]
            if not SESSION_ID_RE.fullmatch(session_id):
                self._send(400, _error_body("INVALID_SESSION_ID", "session_id must be 32 lowercase hex characters."))
                return

            manifest, docs_root, governance_doc, err = _resolve_workspace(qs, cwd, workspace_defaults)
            if err is not None:
                self._send(400, err)
                return
            assert manifest is not None and docs_root is not None and governance_doc is not None

            session_dir, found_elsewhere = session_store_runtime.locate_session_dir(
                manifest, docs_root, session_id
            )
            if found_elsewhere:
                self._send(
                    400,
                    _error_body(
                        "SESSION_CONFIG_MISMATCH",
                        "Current workspace flags do not match the session authority snapshot.",
                    ),
                )
                return
            if session_dir is None:
                session_dir = workspace_runtime.session_directory(docs_root, session_id)
            session_json_path = session_dir / "session.json"
            if not session_dir.is_dir() or not session_json_path.is_file():
                self._send(
                    404,
                    _error_body("SESSION_NOT_FOUND", f"No session state at {session_dir}."),
                )
                return

            try:
                state = workspace_runtime.read_json_file(session_json_path)
            except (OSError, json.JSONDecodeError) as exc:
                self._send(404, _error_body("SESSION_NOT_FOUND", str(exc)))
                return

            config_path = manifest.config_path.resolve()
            if not session_store_runtime.session_paths_match(state, config_path, docs_root, governance_doc):
                self._send(
                    400,
                    _error_body(
                        "SESSION_CONFIG_MISMATCH",
                        "Current workspace flags do not match the session authority snapshot.",
                    ),
                )
                return

            if tail == "meta":
                meta = _session_meta_payload(state)
                raw = json.dumps(meta, separators=(",", ":")).encode("utf-8")
                self._send(200, raw + b"\n")
                return

            trace_enabled = bool(state.get("trace_enabled"))
            after_seq, limit, perr = _parse_after_seq_limit(qs)
            if perr is not None:
                self._send(400, perr)
                return
            assert after_seq is not None and limit is not None
            trace_path = session_store_runtime.trace_file_path(session_dir)
            if trace_enabled:
                events, max_seq = trace_io_runtime.read_trace_lines_since(trace_path, after_seq, limit)
            else:
                events, max_seq = [], 0
            out: Dict[str, Any] = {
                "schema_version": VISUAL_API_SCHEMA_VERSION,
                "trace_enabled": trace_enabled,
                "events": events,
                "max_seq": max_seq,
            }
            raw = json.dumps(out, separators=(",", ":")).encode("utf-8")
            self._send(200, raw + b"\n")
            return

        self._send(404, _error_body("NOT_FOUND", f"No route for {path}"))


def main() -> int:
    parser = argparse.ArgumentParser(description="ASPIS visualizer HTTP bridge (loopback only).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", default=None)
    parser.add_argument("--design-docs-dir", dest="design_docs_dir", default=None)
    parser.add_argument("--governance-doc", dest="governance_doc", default=None)
    args = parser.parse_args()

    cwd = Path.cwd()
    try:
        aspis_runtime._resolve_clause_runtime_paths_with_manifest(
            args.design_docs_dir,
            args.governance_doc,
            args.config,
            cwd,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Workspace resolution failed: {exc}", file=sys.stderr)
        return 2

    server = ThreadingHTTPServer((BIND_HOST, args.port), AspisVisualRequestHandler)
    server.allow_cors = True
    server.workspace_defaults = {
        "config": args.config,
        "design_docs_dir": args.design_docs_dir,
        "governance_doc": args.governance_doc,
    }
    print(f"Aspis visual server on http://{BIND_HOST}:{args.port} (CORS * for loopback only)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
