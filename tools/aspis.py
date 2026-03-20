#!/usr/bin/env python3
"""
ASPIS CLI for clause resolution, instance bootstrapping, and linting.
"""

from __future__ import annotations

import json
import os
import pickle
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import clause as clause_runtime
import lint as lint_runtime
import workspace as workspace_runtime

aliases = {
    "clause": "clause",
    "path": "clause",
    "in": "clause",
    "contract": "clause",
    "domain": "clause",
}
custom: Dict[str, str] = {}
DEFAULT_NEXT_ACTION = "follow paths that match user intent"
TYPED_TOKEN_RE = re.compile(r"^([^:]+):(.*)$", re.IGNORECASE)
CLAUSE_ID_RE = re.compile(r"^[a-z0-9_-]+(?:\.[a-z0-9_-]+)+$", re.IGNORECASE)


def _write_json(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _error_payload(code: str, message: str) -> Dict[str, Any]:
    return {
        "status": "error",
        "blocking": True,
        "issues": [{"code": code, "message": message}],
        "next_actions": DEFAULT_NEXT_ACTION,
    }


def _lint_error_payload(message: str) -> Dict[str, Any]:
    payload = _error_payload("LINT_CONFIGURATION_ERROR", message)
    payload["next_actions"] = lint_runtime.DEFAULT_NEXT_ACTION
    payload["authority_context"] = {
        "surface_kind": "unknown",
        "target_namespace": "unknown",
        "selection_source": "unresolved",
    }
    return payload


def _rel_or_abs(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _resolve_clause_runtime_paths_with_manifest(
    design_docs_dir: Optional[str],
    governance_doc: Optional[str],
    config: Optional[str],
    cwd: Path,
) -> Tuple[workspace_runtime.WorkspaceManifest, Path, Path]:
    manifest = workspace_runtime.load_workspace_manifest(config, cwd)
    docs_root = manifest.protocol_root
    governance_doc_path = manifest.protocol_governance_doc
    if design_docs_dir:
        anchor = manifest.config_path.parent if manifest.config_path.exists() else cwd
        docs_root = workspace_runtime.resolve_path_anchored(design_docs_dir, anchor)
    if governance_doc:
        anchor = manifest.config_path.parent if manifest.config_path.exists() else cwd
        governance_doc_path = workspace_runtime.resolve_path_anchored(governance_doc, anchor)
    if not docs_root.exists() or not docs_root.is_dir():
        raise FileNotFoundError(f"Docs root does not exist: {docs_root}")
    if not governance_doc_path.exists() or not governance_doc_path.is_file():
        raise FileNotFoundError(f"Governance doc does not exist: {governance_doc_path}")
    return manifest, docs_root.resolve(), governance_doc_path.resolve()


def _resolve_clause_runtime_paths(
    design_docs_dir: Optional[str],
    governance_doc: Optional[str],
    config: Optional[str],
    cwd: Path,
) -> Tuple[Path, Path]:
    _, docs_root, governance_doc_path = _resolve_clause_runtime_paths_with_manifest(
        design_docs_dir, governance_doc, config, cwd
    )
    return docs_root, governance_doc_path


def _normalize_clause_tokens(argv: List[str]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    if not argv:
        return None, _error_payload("INVALID_INPUT", "No clause IDs provided.")

    requests: List[Dict[str, Any]] = []
    positional = [token for token in argv if not token.startswith("-")]
    if positional and positional[0].lower() == "clause":
        ids = positional[1:]
        if not ids:
            return None, _error_payload("INVALID_INPUT", "clause requires at least one id.")
        for raw_id in ids:
            canonical = raw_id.strip().lower()
            if not CLAUSE_ID_RE.fullmatch(canonical):
                return None, _error_payload("INVALID_TOKEN", f"Invalid clause id format: '{raw_id}'")
            requests.append({"route": "clause", "id": canonical, "raw": raw_id})
        return requests, None

    for token in positional:
        match = TYPED_TOKEN_RE.match(token)
        if not match:
            return None, _error_payload("INVALID_TOKEN", f"Invalid positional token: '{token}'")
        prefix = match.group(1).strip().lower()
        raw_id = match.group(2).strip()
        route = aliases.get(prefix) or custom.get(prefix)
        if not route:
            return None, _error_payload("UNKNOWN_PREFIX", f"Unknown prefix: '{prefix}'")
        if not raw_id:
            return None, _error_payload("MALFORMED_TOKEN", f"Token missing id: '{token}'")
        canonical = raw_id.lower()
        if not CLAUSE_ID_RE.fullmatch(canonical):
            return None, _error_payload("INVALID_TOKEN", f"Invalid clause id format: '{raw_id}'")
        requests.append({"route": route, "id": canonical, "raw": token})
    return requests, None


def _parse_clause_args(argv: List[str]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]], Dict[str, Any]]:
    options: Dict[str, Any] = {"config": None, "design_docs_dir": None, "governance_doc": None}
    option_map = {
        "--config": "config",
        "--design-docs-dir": "design_docs_dir",
        "--governance-doc": "governance_doc",
    }
    remaining: List[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in option_map:
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, _error_payload("MISSING_OPTION_VALUE", f"Option '{arg}' requires a value."), options
            options[option_map[arg]] = argv[index + 1]
            index += 2
            continue
        matched_inline = False
        for option_name, option_key in option_map.items():
            prefix = f"{option_name}="
            if arg.startswith(prefix):
                value = arg[len(prefix):].strip()
                if not value:
                    return None, _error_payload("MISSING_OPTION_VALUE", f"Option '{option_name}' requires a value."), options
                options[option_key] = value
                matched_inline = True
                break
        if matched_inline:
            index += 1
            continue
        if arg.startswith("-"):
            return None, _error_payload("UNKNOWN_OPTION", f"Unknown option: '{arg}'"), options
        remaining.append(arg)
        index += 1
    requests, err = _normalize_clause_tokens(remaining)
    return requests, err, options


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _registry_cache_path(session_dir: Path) -> Path:
    return (session_dir / "registry.cache").resolve()


def _trace_path(session_dir: Path) -> Path:
    return (session_dir / "trace.jsonl").resolve()


def _normalize_path_key(path: Path) -> str:
    return path.resolve().as_posix()


def _mtimes_dirty(stored: Optional[Dict[str, Any]], current: Dict[str, float]) -> bool:
    if not stored:
        return True
    for path, mtime in current.items():
        if path not in stored:
            return True
        if float(stored[path]) != float(mtime):
            return True
    for path in stored:
        if path not in current:
            return True
    return False


def _float_mtimes(m: Dict[str, float]) -> Dict[str, float]:
    return {k: float(v) for k, v in m.items()}


def _build_response_summary(trace_payload: Dict[str, Any]) -> Dict[str, Any]:
    status = str(trace_payload.get("status", ""))
    blocking = bool(trace_payload.get("blocking", False))
    ctx = trace_payload.get("context") or {}
    requested = list(ctx.get("requested_ids") or [])
    results = trace_payload.get("results_by_id") or {}
    clauses_resolved: List[str] = []
    paths_seen: List[str] = []
    seen_path: Set[str] = set()
    for rid in requested:
        rid_l = str(rid).strip().lower()
        entry = results.get(rid_l) or results.get(rid)
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "ok":
            continue
        clauses_resolved.append(rid_l)
        clause_block = entry.get("clause") or {}
        paths = clause_block.get("paths") or []
        if isinstance(paths, list):
            for p in paths:
                ps = str(p)
                if ps not in seen_path:
                    seen_path.add(ps)
                    paths_seen.append(ps)
    return {
        "status": status,
        "clauses_resolved": clauses_resolved,
        "paths_returned": paths_seen,
        "blocking": blocking,
    }


def _build_paths_by_id(trace_payload: Dict[str, Any]) -> Dict[str, List[str]]:
    ctx = trace_payload.get("context") or {}
    requested = list(ctx.get("requested_ids") or [])
    results = trace_payload.get("results_by_id") or {}
    out: Dict[str, List[str]] = {}
    for rid in requested:
        rid_l = str(rid).strip().lower()
        entry = results.get(rid_l) or results.get(rid)
        if not isinstance(entry, dict) or entry.get("status") != "ok":
            out[rid_l] = []
            continue
        clause_block = entry.get("clause") or {}
        paths = clause_block.get("paths") or []
        if isinstance(paths, list):
            out[rid_l] = [str(p) for p in paths]
        else:
            out[rid_l] = []
    return out


def _merge_clauses_touched_success(
    existing: List[str],
    trace_payload: Dict[str, Any],
) -> List[str]:
    merged = {str(x).strip().lower() for x in existing if str(x).strip()}
    if trace_payload.get("status") == "ok":
        ctx = trace_payload.get("context") or {}
        requested = list(ctx.get("requested_ids") or [])
        results = trace_payload.get("results_by_id") or {}
        for rid in requested:
            rid_l = str(rid).strip().lower()
            entry = results.get(rid_l) or results.get(rid)
            if isinstance(entry, dict) and entry.get("status") == "ok":
                merged.add(rid_l)
    return sorted(merged)


def _graphviz_dot_from_trace_file(trace_path: Path) -> str:
    edges: Set[Tuple[str, str]] = set()
    vertices: Set[str] = set()
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


def _parse_session_start_argv(argv: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    options: Dict[str, Any] = {
        "config": None,
        "design_docs_dir": None,
        "governance_doc": None,
        "name": None,
        "trace": False,
        "trace_full": False,
    }
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--name":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--name' requires a value."
            options["name"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--name="):
            options["name"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--trace":
            options["trace"] = True
            index += 1
            continue
        if arg == "--trace-full":
            options["trace_full"] = True
            index += 1
            continue
        if arg == "--config":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--config' requires a value."
            options["config"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--config="):
            options["config"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--design-docs-dir":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--design-docs-dir' requires a value."
            options["design_docs_dir"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--design-docs-dir="):
            options["design_docs_dir"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--governance-doc":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--governance-doc' requires a value."
            options["governance_doc"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--governance-doc="):
            options["governance_doc"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg.startswith("-"):
            return None, f"Unknown option: '{arg}'"
        return None, f"Unexpected positional argument: '{arg}'"
    return options, None


def _parse_session_cmd_argv(
    argv: List[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[List[str]]]:
    options: Dict[str, Any] = {
        "config": None,
        "design_docs_dir": None,
        "governance_doc": None,
        "session": None,
        "include_full_response": False,
    }
    index = 0
    rest: List[str] = []
    while index < len(argv):
        arg = argv[index]
        if arg == "--session":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--session' requires a value.", None
            options["session"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--session="):
            options["session"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--include-full-response":
            options["include_full_response"] = True
            index += 1
            continue
        rest.append(arg)
        index += 1
    return options, None, rest


def _parse_session_end_argv(argv: List[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    options: Dict[str, Any] = {
        "config": None,
        "design_docs_dir": None,
        "governance_doc": None,
        "session": None,
        "format": "summary",
        "output": None,
    }
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--session":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--session' requires a value."
            options["session"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--session="):
            options["session"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--format":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--format' requires a value."
            options["format"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--format="):
            options["format"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--output":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--output' requires a value."
            options["output"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--output="):
            options["output"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--config":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--config' requires a value."
            options["config"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--config="):
            options["config"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--design-docs-dir":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--design-docs-dir' requires a value."
            options["design_docs_dir"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--design-docs-dir="):
            options["design_docs_dir"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg == "--governance-doc":
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                return None, "Option '--governance-doc' requires a value."
            options["governance_doc"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--governance-doc="):
            options["governance_doc"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg.startswith("-"):
            return None, f"Unknown option: '{arg}'"
        return None, f"Unexpected positional argument: '{arg}'"
    return options, None


def _parse_simple_subcommand_args(argv: List[str], option_names: Dict[str, str]) -> Dict[str, Optional[str]]:
    options: Dict[str, Optional[str]] = {value: None for value in option_names.values()}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in option_names:
            if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                raise ValueError(f"Option '{arg}' requires a value.")
            options[option_names[arg]] = argv[index + 1]
            index += 2
            continue
        matched_inline = False
        for option_name, option_key in option_names.items():
            prefix = f"{option_name}="
            if arg.startswith(prefix):
                options[option_key] = arg[len(prefix):].strip()
                matched_inline = True
                break
        if matched_inline:
            index += 1
            continue
        raise ValueError(f"Unknown option: '{arg}'")
    return options


def _render_clause_cmd(argv: List[str]) -> str:
    workspace_options = {"--config", "--design-docs-dir", "--governance-doc"}
    tokens: List[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in workspace_options:
            index += 2
            continue
        if any(arg.startswith(f"{option}=") for option in workspace_options):
            index += 1
            continue
        tokens.append(arg)
        index += 1
    return " ".join(tokens)


def _load_or_create_manifest(config: Optional[str], cwd: Path) -> workspace_runtime.WorkspaceManifest:
    config_path = Path(config).resolve() if config else workspace_runtime.find_config(cwd)
    if config_path is None:
        config_path = (cwd / "aspis.yaml").resolve()
    if not config_path.exists():
        payload = workspace_runtime.default_manifest(config_path)
        workspace_runtime.write_yaml_file(config_path, payload)
    return workspace_runtime.load_workspace_manifest(str(config_path), cwd)


def _handle_init(argv: List[str]) -> int:
    try:
        options = _parse_simple_subcommand_args(argv, {
            "--config": "config",
            "--namespace": "namespace",
            "--dir": "dir",
            "--name": "name",
        })
        namespace_raw = str(options.get("namespace") or "").strip()
        if not namespace_raw:
            raise ValueError("Option '--namespace' is required.")
        namespace = workspace_runtime.normalize_namespace(namespace_raw)
        manifest = _load_or_create_manifest(options.get("config"), Path.cwd())
        protocol_surface = workspace_runtime.resolve_protocol_surface(manifest)
        existing_namespaces = {protocol_surface.namespace, *(surface.namespace for surface in manifest.instances)}
        if namespace in existing_namespaces:
            raise ValueError(f"Namespace '{namespace}' is already registered.")

        target_dir = manifest.workspace_root if not options.get("dir") else workspace_runtime.resolve_path_anchored(str(options.get("dir")), manifest.workspace_root)
        folder_name = str(options.get("name") or workspace_runtime.default_instance_folder_name(namespace)).strip()
        if not folder_name:
            raise ValueError("Instance folder name cannot be empty.")
        docs_root = (target_dir / folder_name).resolve()
        governance_doc = docs_root / "0.00 - Governance: Origin.md"
        if docs_root.exists():
            raise FileExistsError(f"Instance root already exists: {docs_root}")

        docs_root.mkdir(parents=True, exist_ok=False)
        governance_doc.write_text(workspace_runtime.instance_origin_template(namespace), encoding="utf-8")

        instance_surface = workspace_runtime.AuthoritySurface(
            surface_kind="instance",
            namespace=namespace,
            docs_root=docs_root,
            governance_doc=governance_doc,
            lineage={"instance_type": "aspis_instance"},
        )
        updated_manifest = workspace_runtime.make_manifest(
            config_path=manifest.config_path,
            workspace_name=manifest.workspace_name,
            protocol_root=manifest.protocol_root,
            protocol_governance_doc=manifest.protocol_governance_doc,
            instances=[*manifest.instances, instance_surface],
        )
        workspace_runtime.save_workspace_manifest(updated_manifest)
        payload = {
            "status": "ok",
            "blocking": False,
            "instance": {
                "namespace": namespace,
                "root": _rel_or_abs(updated_manifest.workspace_root, docs_root),
                "governance_doc": _rel_or_abs(updated_manifest.workspace_root, governance_doc),
                "doc_id": workspace_runtime.instance_origin_doc_id(namespace),
            },
        }
        _write_json(payload)
        return 0
    except (FileNotFoundError, FileExistsError, OSError, ValueError) as exc:
        _write_json(_error_payload("INIT_ERROR", str(exc)))
        return 2


def _handle_lint(argv: List[str]) -> int:
    try:
        options: Dict[str, Optional[str]] = {"config": None, "target": None}
        positionals: List[str] = []
        index = 0
        while index < len(argv):
            arg = argv[index]
            if arg == "--config":
                if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                    raise ValueError("Option '--config' requires a value.")
                options["config"] = argv[index + 1]
                index += 2
                continue
            if arg == "--target":
                if index + 1 >= len(argv) or argv[index + 1].startswith("-"):
                    raise ValueError("Option '--target' requires a value.")
                options["target"] = argv[index + 1]
                index += 2
                continue
            if arg.startswith("--config="):
                options["config"] = arg.partition("=")[2].strip()
                index += 1
                continue
            if arg.startswith("--target="):
                options["target"] = arg.partition("=")[2].strip()
                index += 1
                continue
            if arg.startswith("-"):
                raise ValueError(f"Unknown option: '{arg}'")
            positionals.append(arg)
            index += 1

        if options.get("target") and positionals:
            raise ValueError("Use either positional target or --target, not both.")
        if len(positionals) > 1:
            raise ValueError("lint accepts at most one positional target selector.")
        target = options.get("target") or (positionals[0] if positionals else None)
        payload = lint_runtime.run_lint(options.get("config"), Path.cwd(), target)
    except (FileNotFoundError, OSError, ValueError) as exc:
        payload = _lint_error_payload(str(exc))
    _write_json(payload)
    if payload.get("status") == "error" and payload.get("blocking"):
        return 2
    return 0


def _session_paths_match(
    state: Dict[str, Any],
    config_path: Path,
    docs_root: Path,
    governance_doc: Path,
) -> bool:
    return (
        _normalize_path_key(Path(str(state.get("config_path", "")))) == _normalize_path_key(config_path)
        and _normalize_path_key(Path(str(state.get("docs_root", "")))) == _normalize_path_key(docs_root)
        and _normalize_path_key(Path(str(state.get("governance_doc", "")))) == _normalize_path_key(governance_doc)
    )


def _candidate_session_dirs(
    manifest: workspace_runtime.WorkspaceManifest,
    session_id: str,
) -> List[Path]:
    candidates = [workspace_runtime.session_directory(manifest.protocol_root, session_id)]
    candidates.extend(workspace_runtime.session_directory(surface.docs_root, session_id) for surface in manifest.instances)
    unique: List[Path] = []
    seen: Set[str] = set()
    for path in candidates:
        key = _normalize_path_key(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _locate_session_dir(
    manifest: workspace_runtime.WorkspaceManifest,
    docs_root: Path,
    session_id: str,
) -> Tuple[Optional[Path], bool]:
    expected = workspace_runtime.session_directory(docs_root, session_id)
    if expected.is_dir() and (expected / "session.json").is_file():
        return expected, False
    for candidate in _candidate_session_dirs(manifest, session_id):
        if candidate == expected:
            continue
        if candidate.is_dir() and (candidate / "session.json").is_file():
            return candidate, True
    return None, False


def _load_registry_for_session(
    session_id: str,
    session_dir: Path,
    docs_root: Path,
    state: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, str]], bool]:
    current_mtimes = clause_runtime.collect_registry_mtimes(docs_root)
    current_mtimes = _float_mtimes(current_mtimes)
    stored_mtimes = state.get("registry_index_mtimes")
    dirty = _mtimes_dirty(stored_mtimes, current_mtimes)
    cache_path = _registry_cache_path(session_dir)
    mem = clause_runtime.registry_memory_get(session_id)
    if not dirty and mem is not None:
        by_id, issues, _mem_m = mem
        return by_id, issues, False
    if not dirty and cache_path.is_file():
        try:
            with cache_path.open("rb") as handle:
                by_id, issues = pickle.load(handle)
            clause_runtime.registry_memory_put(session_id, by_id, issues, current_mtimes)
            return by_id, issues, False
        except (OSError, pickle.PickleError, EOFError, AttributeError):
            pass
    try:
        by_id, issues, mtimes = clause_runtime.load_registry_index(docs_root)
    except (OSError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    mtimes_dict = _float_mtimes(mtimes)
    try:
        with cache_path.open("wb") as handle:
            pickle.dump((by_id, issues), handle)
    except OSError:
        pass
    clause_runtime.registry_memory_put(session_id, by_id, issues, mtimes_dict)
    return by_id, issues, True


def _handle_session_start(argv: List[str]) -> int:
    opts, err = _parse_session_start_argv(argv)
    if err:
        _write_json(_error_payload("INVALID_INPUT", err))
        return 2
    assert opts is not None
    name = str(opts.get("name") or "").strip()
    if not name:
        _write_json(_error_payload("INVALID_INPUT", "Option '--name' is required."))
        return 2
    cwd = Path.cwd()
    try:
        manifest, docs_root, governance_doc = _resolve_clause_runtime_paths_with_manifest(
            opts.get("design_docs_dir"),
            opts.get("governance_doc"),
            opts.get("config"),
            cwd,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        _write_json(_error_payload("PATH_RESOLUTION", str(exc)))
        return 2
    try:
        surface_kind, namespace = workspace_runtime.resolve_authority_surface_for_session(
            manifest, docs_root, governance_doc
        )
    except ValueError:
        _write_json(_error_payload(
            "SESSION_AUTHORITY_AMBIGUOUS",
            "Could not map docs root and governance doc to exactly one protocol or instance surface.",
        ))
        return 2

    session_id = uuid.uuid4().hex
    session_dir = workspace_runtime.session_directory(docs_root, session_id)
    if session_dir.exists():
        _write_json(_error_payload("SESSION_ERROR", f"Session directory already exists: {session_dir}"))
        return 2
    session_dir.mkdir(parents=True, exist_ok=False)

    trace_enabled = bool(opts.get("trace"))
    trace_full_default = bool(opts.get("trace_full"))
    config_path = manifest.config_path.resolve()

    try:
        by_id, issues, mtimes = clause_runtime.load_registry_index(docs_root)
    except (OSError, ValueError) as exc:
        _write_json(_error_payload("SESSION_REGISTRY_RELOAD_FAILED", str(exc)))
        try:
            os.rmdir(session_dir)
        except OSError:
            pass
        return 2
    mtimes_dict = _float_mtimes(mtimes)
    try:
        with _registry_cache_path(session_dir).open("wb") as handle:
            pickle.dump((by_id, issues), handle)
    except OSError:
        pass
    clause_runtime.registry_memory_put(session_id, by_id, issues, mtimes_dict)

    if trace_enabled:
        _trace_path(session_dir).write_text("", encoding="utf-8")

    started_at = _utc_now_iso()
    state: Dict[str, Any] = {
        "session_id": session_id,
        "name": name,
        "started_at": started_at,
        "lifecycle": "active",
        "ended_at": None,
        "next_seq": 1,
        "surface_kind": surface_kind,
        "namespace": namespace,
        "config_path": _normalize_path_key(config_path),
        "docs_root": _normalize_path_key(docs_root),
        "governance_doc": _normalize_path_key(governance_doc),
        "trace_enabled": trace_enabled,
        "trace_full_default": trace_full_default,
        "command_count": 0,
        "clauses_touched_success": [],
        "workspace_root": _normalize_path_key(manifest.workspace_root),
        "registry_index_mtimes": mtimes_dict,
    }
    workspace_runtime.write_json_atomic(session_dir / "session.json", state)

    payload = {
        "status": "ok",
        "session_id": session_id,
        "session_dir": _normalize_path_key(session_dir),
        "trace_enabled": trace_enabled,
    }
    _write_json(payload)
    return 0


def _handle_session_cmd(argv: List[str]) -> int:
    opts, err, rest = _parse_session_cmd_argv(argv)
    if err:
        _write_json(_error_payload("INVALID_INPUT", err))
        return 2
    assert opts is not None
    session_id = str(opts.get("session") or "").strip()
    if not session_id:
        _write_json(_error_payload("INVALID_INPUT", "Option '--session' is required."))
        return 2

    requests, error_payload, _clause_opts = _parse_clause_args(rest)
    if error_payload is not None:
        _write_json(error_payload)
        return 2
    if not requests:
        _write_json(_error_payload("INVALID_INPUT", "No clause tokens provided for session:cmd."))
        return 2
    clause_opts = _clause_opts

    cwd = Path.cwd()
    try:
        manifest, docs_root, governance_doc = _resolve_clause_runtime_paths_with_manifest(
            clause_opts.get("design_docs_dir"),
            clause_opts.get("governance_doc"),
            clause_opts.get("config"),
            cwd,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        _write_json(_error_payload("PATH_RESOLUTION", str(exc)))
        return 2

    config_path = manifest.config_path.resolve()
    session_dir, found_elsewhere = _locate_session_dir(manifest, docs_root, session_id)
    if found_elsewhere:
        _write_json(_error_payload(
            "SESSION_CONFIG_MISMATCH",
            "Current workspace flags do not match the session authority snapshot.",
        ))
        return 2
    if session_dir is None:
        session_dir = workspace_runtime.session_directory(docs_root, session_id)
    session_json_path = session_dir / "session.json"
    if not session_dir.is_dir() or not session_json_path.is_file():
        _write_json(_error_payload("SESSION_NOT_FOUND", f"No session state at {session_dir}."))
        return 2

    try:
        state = workspace_runtime.read_json_file(session_json_path)
    except (OSError, json.JSONDecodeError) as exc:
        _write_json(_error_payload("SESSION_NOT_FOUND", str(exc)))
        return 2

    if not _session_paths_match(state, config_path, docs_root, governance_doc):
        _write_json(_error_payload(
            "SESSION_CONFIG_MISMATCH",
            "Current workspace flags do not match the session authority snapshot.",
        ))
        return 2

    if str(state.get("lifecycle", "")) != "active":
        _write_json(_error_payload("SESSION_NOT_ACTIVE", "Session is not active."))
        return 2

    ids = [request["id"] for request in requests]
    try:
        by_id, issues, cache_reloaded = _load_registry_for_session(session_id, session_dir, docs_root, state)
    except RuntimeError as exc:
        _write_json(_error_payload("SESSION_REGISTRY_RELOAD_FAILED", str(exc)))
        return 2

    cmd_display = _render_clause_cmd(rest)

    started = time.perf_counter()
    payload = clause_runtime.resolve_batch(
        ids=ids,
        docs_root=docs_root,
        governance_doc=governance_doc,
        preloaded=(by_id, issues),
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    trace_enabled = bool(state.get("trace_enabled"))
    trace_full = bool(state.get("trace_full_default")) or bool(opts.get("include_full_response"))

    next_seq = int(state.get("next_seq") or 1)
    command_count = int(state.get("command_count") or 0)
    clauses_prior = list(state.get("clauses_touched_success") or [])

    if trace_enabled:
        trace_line: Dict[str, Any] = {
            "ts": _utc_now_iso(),
            "seq": next_seq,
            "cmd": cmd_display,
            "elapsed_ms": elapsed_ms,
            "response_summary": _build_response_summary(payload),
            "paths_by_id": _build_paths_by_id(payload),
        }
        ctx_trace: Dict[str, Any] = {"namespace": str(state.get("namespace", ""))}
        if cache_reloaded:
            ctx_trace["cache_reloaded"] = True
        trace_line["context"] = ctx_trace
        if trace_full:
            trace_line["full_response"] = payload
        workspace_runtime.append_jsonl_line(_trace_path(session_dir), trace_line)
        next_seq += 1

    command_count += 1
    clauses_merged = _merge_clauses_touched_success(clauses_prior, payload)
    state["next_seq"] = next_seq
    state["command_count"] = command_count
    state["clauses_touched_success"] = clauses_merged
    state["registry_index_mtimes"] = _float_mtimes(clause_runtime.collect_registry_mtimes(docs_root))
    workspace_runtime.write_json_atomic(session_json_path, state)

    _write_json(payload)
    if payload.get("status") == "error" and payload.get("blocking"):
        return 2
    return 0


def _handle_session_end(argv: List[str]) -> int:
    opts, err = _parse_session_end_argv(argv)
    if err:
        _write_json(_error_payload("INVALID_INPUT", err))
        return 2
    assert opts is not None
    session_id = str(opts.get("session") or "").strip()
    if not session_id:
        _write_json(_error_payload("INVALID_INPUT", "Option '--session' is required."))
        return 2

    fmt = str(opts.get("format") or "summary").strip().lower()
    if fmt not in {"summary", "json", "graphviz"}:
        _write_json(_error_payload("INVALID_INPUT", f"Unsupported --format '{fmt}'."))
        return 2

    cwd = Path.cwd()
    try:
        manifest, docs_root, governance_doc = _resolve_clause_runtime_paths_with_manifest(
            opts.get("design_docs_dir"),
            opts.get("governance_doc"),
            opts.get("config"),
            cwd,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        _write_json(_error_payload("PATH_RESOLUTION", str(exc)))
        return 2

    config_path = manifest.config_path.resolve()
    session_dir, found_elsewhere = _locate_session_dir(manifest, docs_root, session_id)
    if found_elsewhere:
        _write_json(_error_payload(
            "SESSION_CONFIG_MISMATCH",
            "Current workspace flags do not match the session authority snapshot.",
        ))
        return 2
    if session_dir is None:
        session_dir = workspace_runtime.session_directory(docs_root, session_id)
    session_json_path = session_dir / "session.json"
    if not session_dir.is_dir() or not session_json_path.is_file():
        _write_json(_error_payload("SESSION_NOT_FOUND", f"No session state at {session_dir}."))
        return 2

    try:
        state = workspace_runtime.read_json_file(session_json_path)
    except (OSError, json.JSONDecodeError) as exc:
        _write_json(_error_payload("SESSION_NOT_FOUND", str(exc)))
        return 2

    if not _session_paths_match(state, config_path, docs_root, governance_doc):
        _write_json(_error_payload(
            "SESSION_CONFIG_MISMATCH",
            "Current workspace flags do not match the session authority snapshot.",
        ))
        return 2

    if str(state.get("lifecycle", "")) == "ended":
        _write_json(_error_payload("SESSION_ALREADY_ENDED", "Session has already ended."))
        return 2

    trace_enabled = bool(state.get("trace_enabled"))
    if fmt == "graphviz":
        if not opts.get("output"):
            _write_json(_error_payload("INVALID_INPUT", "Option '--output' is required for graphviz format."))
            return 2
        if not trace_enabled:
            _write_json(_error_payload("TRACE_REQUIRED", "Graphviz output requires trace to have been enabled at session:start."))
            return 2

    ended_at = _utc_now_iso()
    state["lifecycle"] = "ended"
    state["ended_at"] = ended_at
    workspace_runtime.write_json_atomic(session_json_path, state)
    clause_runtime.registry_memory_clear(session_id)

    session_dir_abs = _normalize_path_key(session_dir)
    trace_file = _trace_path(session_dir)
    trace_path_str = _normalize_path_key(trace_file) if trace_enabled and trace_file.is_file() else None

    command_count = int(state.get("command_count") or 0)
    clauses_touched = list(state.get("clauses_touched_success") or [])

    if fmt == "summary":
        lines = [
            f"ASPIS session {session_id}",
            f"Commands completed: {command_count}",
            f"Clauses touched (success): {len(clauses_touched)}",
            f"Ended at: {ended_at}",
        ]
        if clauses_touched:
            lines.append("Clause ids: " + ", ".join(clauses_touched))
        summary_text = "\n".join(lines) + "\n"
        out = {
            "status": "ok",
            "session_id": session_id,
            "format": "summary",
            "summary_text": summary_text,
            "command_count": command_count,
            "clauses_touched_count": len(clauses_touched),
            "ended_at": ended_at,
        }
        _write_json(out)
        return 0

    if fmt == "json":
        out = {
            "status": "ok",
            "session_id": session_id,
            "session_dir": session_dir_abs,
            "trace_path": trace_path_str,
            "command_count": command_count,
            "clauses_touched": clauses_touched,
            "ended_at": ended_at,
        }
        _write_json(out)
        return 0

    out_path = Path(str(opts.get("output"))).expanduser()
    if not out_path.is_absolute():
        out_path = (cwd / out_path).resolve()
    else:
        out_path = out_path.resolve()
    dot_body = _graphviz_dot_from_trace_file(trace_file)
    out_path.write_text(dot_body, encoding="utf-8")
    payload = {
        "status": "ok",
        "session_id": session_id,
        "dot_path": _normalize_path_key(out_path),
        "ended_at": ended_at,
    }
    _write_json(payload)
    return 0


def _handle_clause(argv: List[str]) -> int:
    requests, error_payload, options = _parse_clause_args(argv)
    if error_payload is not None:
        _write_json(error_payload)
        return 2

    assert requests is not None
    ids = [request["id"] for request in requests]
    try:
        docs_root, governance_doc = _resolve_clause_runtime_paths(
            options.get("design_docs_dir"),
            options.get("governance_doc"),
            options.get("config"),
            Path.cwd(),
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        _write_json(_error_payload("PATH_RESOLUTION", str(exc)))
        return 2

    payload = clause_runtime.resolve_batch(ids=ids, docs_root=docs_root, governance_doc=governance_doc)
    _write_json(payload)
    if payload.get("status") == "error" and payload.get("blocking"):
        return 2
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0].lower() == "init":
        return _handle_init(argv[1:])
    if argv and argv[0].lower() == "lint":
        return _handle_lint(argv[1:])
    if argv and argv[0].lower() == "session:start":
        return _handle_session_start(argv[1:])
    if argv and argv[0].lower() == "session:cmd":
        return _handle_session_cmd(argv[1:])
    if argv and argv[0].lower() == "session:end":
        return _handle_session_end(argv[1:])
    return _handle_clause(argv)


if __name__ == "__main__":
    raise SystemExit(main())
