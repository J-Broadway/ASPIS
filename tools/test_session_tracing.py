#!/usr/bin/env python3
"""Session tracing CLI tests (subprocess against workspace aspis.yaml)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASPIS_PY = REPO / "tools" / "aspis.py"
sys.path.insert(0, str(REPO / "tools"))

import workspace as workspace_runtime


def _run(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(ASPIS_PY), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO / "tools")},
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class SessionTracingTests(unittest.TestCase):
    def test_start_cmd_end_json_trace(self) -> None:
        code, out = _run("session:start", "--name", "pytest", "--trace")
        self.assertEqual(code, 0, out)
        meta = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(meta.get("status"), "ok")
        sid = meta["session_id"]
        self.assertTrue(meta.get("trace_enabled"))

        code2, out2 = _run("session:cmd", "--session", sid, "path:aspis.entry")
        self.assertEqual(code2, 0, out2)
        payload = json.loads(out2.strip().splitlines()[-1])
        self.assertEqual(payload.get("status"), "ok")

        code3, out3 = _run("session:end", "--session", sid, "--format", "json")
        self.assertEqual(code3, 0, out3)
        end = json.loads(out3.strip().splitlines()[-1])
        self.assertEqual(end.get("command_count"), 1)
        self.assertIn("aspis.entry", end.get("clauses_touched", []))
        self.assertIsNotNone(end.get("trace_path"))

        session_dir = Path(end["session_dir"])
        trace = session_dir / "trace.jsonl"
        self.assertTrue(trace.is_file())
        line = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[0])
        self.assertEqual(line.get("seq"), 1)
        self.assertIn("response_summary", line)
        self.assertIn("paths_by_id", line)

    def test_trace_cmd_strips_workspace_options_and_accepts_late_full_flag(self) -> None:
        code, out = _run("session:start", "--name", "trace-shape", "--trace")
        self.assertEqual(code, 0, out)
        meta = json.loads(out.strip().splitlines()[-1])
        sid = meta["session_id"]

        code2, out2 = _run(
            "session:cmd",
            "--session",
            sid,
            "path:aspis.entry",
            "--include-full-response",
            "--config",
            "aspis.yaml",
        )
        self.assertEqual(code2, 0, out2)

        trace = Path(meta["session_dir"]) / "trace.jsonl"
        line = json.loads(trace.read_text(encoding="utf-8").strip().splitlines()[0])
        self.assertEqual(line.get("cmd"), "path:aspis.entry")
        self.assertIn("full_response", line)

    def test_already_ended_and_not_active(self) -> None:
        code, out = _run("session:start", "--name", "e2", "--trace")
        self.assertEqual(code, 0, out)
        sid = json.loads(out.strip().splitlines()[-1])["session_id"]
        self.assertEqual(_run("session:end", "--session", sid, "--format", "json")[0], 0)
        code_bad, _ = _run("session:end", "--session", sid, "--format", "json")
        self.assertEqual(code_bad, 2)
        code_na, out_na = _run("session:cmd", "--session", sid, "path:aspis.entry")
        self.assertEqual(code_na, 2)
        err = json.loads(out_na.strip().splitlines()[-1])
        self.assertEqual(err["issues"][0]["code"], "SESSION_NOT_ACTIVE")

    def test_session_cmd_returns_config_mismatch_when_session_exists_on_other_surface(self) -> None:
        code, out = _run("session:start", "--name", "surface-mismatch", "--trace")
        self.assertEqual(code, 0, out)
        sid = json.loads(out.strip().splitlines()[-1])["session_id"]

        code_bad, out_bad = _run(
            "session:cmd",
            "--session",
            sid,
            "--design-docs-dir",
            "demo - ASPIS",
            "path:aspis.entry",
        )
        self.assertEqual(code_bad, 2)
        err = json.loads(out_bad.strip().splitlines()[-1])
        self.assertEqual(err["issues"][0]["code"], "SESSION_CONFIG_MISMATCH")

    def test_protocol_surface_resolution_uses_docs_root_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protocol_root = root / "ASPIS"
            protocol_root.mkdir()
            protocol_governance = protocol_root / "0.00 - Governance: Origin.md"
            protocol_governance.write_text("---\ndoc_id: aspis.doc.governance.origin\n---\n", encoding="utf-8")
            alternate_governance = protocol_root / "alt-governance.md"
            alternate_governance.write_text("# alt\n", encoding="utf-8")

            manifest = workspace_runtime.make_manifest(
                config_path=root / "aspis.yaml",
                workspace_name="tmp",
                protocol_root=protocol_root,
                protocol_governance_doc=protocol_governance,
                instances=[],
            )

            surface_kind, namespace = workspace_runtime.resolve_authority_surface_for_session(
                manifest,
                protocol_root,
                alternate_governance,
            )
            self.assertEqual(surface_kind, "protocol")
            self.assertEqual(namespace, "aspis")


if __name__ == "__main__":
    unittest.main()
