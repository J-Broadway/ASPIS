#!/usr/bin/env python3
"""Full registry clause graph as JSON (nodes + path edges)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import clause as clause_runtime

REGISTRY_GRAPH_SCHEMA_VERSION = "aspis.registry_graph.v1"


def build_registry_graph_document(
    docs_root: Path,
    *,
    include_content: bool = False,
) -> Dict[str, Any]:
    by_id, issues, _mtimes = clause_runtime.load_registry_index(docs_root)
    root_key = docs_root.resolve().as_posix()
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []

    for cid in sorted(by_id.keys()):
        clause = by_id[cid]
        payload = clause_runtime._public_clause_payload(clause)
        if not include_content:
            payload.pop("content", None)
        nodes.append(payload)

    for cid in sorted(by_id.keys()):
        clause = by_id[cid]
        paths = clause.get("paths") or []
        if not isinstance(paths, list):
            continue
        from_id = str(cid).strip().lower()
        for p in paths:
            edges.append({"from": from_id, "to": str(p).strip()})

    return {
        "schema_version": REGISTRY_GRAPH_SCHEMA_VERSION,
        "docs_root": root_key,
        "issues": list(issues),
        "nodes": nodes,
        "edges": edges,
    }
