#!/usr/bin/env python3
"""Incremental trace.jsonl reads and merged path edges for graphviz / APIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


def paths_edges_from_trace_file(trace_path: Path) -> Tuple[Set[str], Set[Tuple[str, str]]]:
    """Collect vertices and directed edges from paths_by_id in a trace file."""
    edges: Set[Tuple[str, str]] = set()
    vertices: Set[str] = set()
    if not trace_path.is_file():
        return vertices, edges
    for raw_line in trace_path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        for from_id, to_list in (obj.get("paths_by_id") or {}).items():
            if from_id:
                vertices.add(str(from_id))
            if not isinstance(to_list, list):
                continue
            for to_id in to_list:
                vertices.add(str(to_id))
                edges.add((str(from_id), str(to_id)))
    return vertices, edges


def graphviz_dot_from_trace_file(trace_path: Path) -> str:
    vertices, edges = paths_edges_from_trace_file(trace_path)
    lines = ["digraph aspis_session {", '  rankdir="LR";']
    for v in sorted(vertices):
        safe = v.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  "{safe}";')
    for a, b in sorted(edges):
        sa = a.replace("\\", "\\\\").replace('"', '\\"')
        sb = b.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  "{sa}" -> "{sb}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _parse_trace_objects(trace_path: Path) -> List[Dict[str, Any]]:
    if not trace_path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        text = trace_path.read_text(encoding="utf-8")
    except OSError:
        return []
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def read_trace_lines_since(trace_path: Path, after_seq: int, limit: int) -> Tuple[List[Dict[str, Any]], int]:
    """
    Parse JSONL, compute max_seq over all events, return events with seq > after_seq
    sorted by seq ascending, at most `limit` items.
    """
    objs = _parse_trace_objects(trace_path)
    max_seq = 0
    keyed: List[Tuple[int, Dict[str, Any]]] = []
    for obj in objs:
        try:
            s = int(obj.get("seq", 0))
        except (TypeError, ValueError):
            continue
        if s > max_seq:
            max_seq = s
        keyed.append((s, obj))
    keyed.sort(key=lambda t: t[0])
    events = [obj for s, obj in keyed if s > after_seq][: max(0, limit)]
    return events, max_seq
