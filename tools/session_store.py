#!/usr/bin/env python3
"""
Shared session directory resolution and path validation for CLI and visual server.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import workspace as workspace_runtime


def normalize_path_key(path: Path) -> str:
    return path.resolve().as_posix()


def trace_file_path(session_dir: Path) -> Path:
    return (session_dir / "trace.jsonl").resolve()


def session_paths_match(
    state: Dict[str, Any],
    config_path: Path,
    docs_root: Path,
    governance_doc: Path,
) -> bool:
    return (
        normalize_path_key(Path(str(state.get("config_path", "")))) == normalize_path_key(config_path)
        and normalize_path_key(Path(str(state.get("docs_root", "")))) == normalize_path_key(docs_root)
        and normalize_path_key(Path(str(state.get("governance_doc", "")))) == normalize_path_key(governance_doc)
    )


def candidate_session_dirs(
    manifest: workspace_runtime.WorkspaceManifest,
    session_id: str,
) -> List[Path]:
    candidates = [workspace_runtime.session_directory(manifest.protocol_root, session_id)]
    candidates.extend(
        workspace_runtime.session_directory(surface.docs_root, session_id) for surface in manifest.instances
    )
    unique: List[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = normalize_path_key(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def locate_session_dir(
    manifest: workspace_runtime.WorkspaceManifest,
    docs_root: Path,
    session_id: str,
) -> Tuple[Optional[Path], bool]:
    expected = workspace_runtime.session_directory(docs_root, session_id)
    if expected.is_dir() and (expected / "session.json").is_file():
        return expected, False
    for candidate in candidate_session_dirs(manifest, session_id):
        if candidate == expected:
            continue
        if candidate.is_dir() and (candidate / "session.json").is_file():
            return candidate, True
    return None, False
