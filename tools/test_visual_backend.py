#!/usr/bin/env python3
"""Tests for registry graph export, trace incremental read, and visual HTTP bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASPIS_PY = REPO / "tools" / "aspis.py"
sys.path.insert(0, str(REPO / "tools"))

import trace_io as trace_io_runtime


def _run_aspis(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(ASPIS_PY), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO / "tools")},
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class VisualBackendTests(unittest.TestCase):
    def test_visual_graph_cli_schema_and_entry_edges(self) -> None:
        code, out = _run_aspis("visual:graph", "--config", "aspis.yaml")
        self.assertEqual(code, 0, out)
        doc = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(doc.get("schema_version"), "aspis.registry_graph.v1")
        self.assertIn("nodes", doc)
        self.assertIn("edges", doc)
        self.assertIn("issues", doc)
        self.assertTrue(any(n.get("id") == "aspis.entry" for n in doc["nodes"]))
        from_entry = [e for e in doc["edges"] if e.get("from") == "aspis.entry"]
        self.assertTrue(len(from_entry) > 0, "aspis.entry should have path edges")

    def test_read_trace_lines_since_sort_and_filter(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as handle:
            path = Path(handle.name)
            handle.write('{"seq":1,"a":1}\n{"seq":3,"a":3}\n{"seq":2,"a":2}\n')
        try:
            events, max_seq = trace_io_runtime.read_trace_lines_since(path, 0, 10)
            self.assertEqual(max_seq, 3)
            self.assertEqual([e.get("seq") for e in events], [1, 2, 3])
            ev2, m2 = trace_io_runtime.read_trace_lines_since(path, 2, 10)
            self.assertEqual(m2, 3)
            self.assertEqual([e.get("seq") for e in ev2], [3])
            ev3, m3 = trace_io_runtime.read_trace_lines_since(path, 3, 10)
            self.assertEqual(m3, 3)
            self.assertEqual(ev3, [])
        finally:
            path.unlink(missing_ok=True)

    def test_http_graph_matches_cli(self) -> None:
        import serve_aspis_visual as serve_mod

        server = serve_mod.ThreadingHTTPServer(
            (serve_mod.BIND_HOST, 0),
            serve_mod.AspisVisualRequestHandler,
        )
        server.allow_cors = True
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            q = urllib.parse.urlencode({"config": str(REPO / "aspis.yaml")})
            url = f"http://127.0.0.1:{port}/api/graph?{q}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode("utf-8")
            api_doc = json.loads(body.strip())
            code, out = _run_aspis("visual:graph", "--config", "aspis.yaml")
            self.assertEqual(code, 0, out)
            cli_doc = json.loads(out.strip().splitlines()[-1])
            self.assertEqual(api_doc.get("schema_version"), cli_doc.get("schema_version"))
            self.assertEqual(len(api_doc.get("nodes", [])), len(cli_doc.get("nodes", [])))
            self.assertEqual(len(api_doc.get("edges", [])), len(cli_doc.get("edges", [])))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_graph_uses_server_workspace_defaults(self) -> None:
        import serve_aspis_visual as serve_mod

        server = serve_mod.ThreadingHTTPServer(
            (serve_mod.BIND_HOST, 0),
            serve_mod.AspisVisualRequestHandler,
        )
        server.allow_cors = True
        server.workspace_defaults = {
            "config": str(REPO / "aspis.yaml"),
            "design_docs_dir": str(REPO / "demo - ASPIS"),
            "governance_doc": None,
        }
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/graph", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode("utf-8")
            api_doc = json.loads(body.strip())
            self.assertEqual(api_doc.get("docs_root"), str((REPO / "demo - ASPIS").resolve()))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
