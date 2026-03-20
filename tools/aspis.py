#!/usr/bin/env python3
"""
ASPIS CLI for clause resolution, instance bootstrapping, and linting.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def _resolve_clause_runtime_paths(
    design_docs_dir: Optional[str],
    governance_doc: Optional[str],
    config: Optional[str],
    cwd: Path,
) -> Tuple[Path, Path]:
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
    return _handle_clause(argv)


if __name__ == "__main__":
    raise SystemExit(main())
