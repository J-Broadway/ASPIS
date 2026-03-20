#!/usr/bin/env python3
"""
Workspace manifest helpers for ASPIS protocol + instance discovery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

NAMESPACE_TOKEN_RE = re.compile(r"^[a-z0-9_-]+$", re.IGNORECASE)
IDENTITY_RE = re.compile(r"^[a-z0-9_-]+(?:\.[a-z0-9_-]+)+$", re.IGNORECASE)


@dataclass(frozen=True)
class AuthoritySurface:
    surface_kind: str
    namespace: str
    docs_root: Path
    governance_doc: Path
    lineage: Dict[str, Any]


@dataclass(frozen=True)
class WorkspaceManifest:
    config_path: Path
    workspace_root: Path
    workspace_name: str
    protocol_root: Path
    protocol_governance_doc: Path
    instances: List[AuthoritySurface]


def _strip_quotes(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _parse_scalar(value: str) -> Any:
    raw = value.strip()
    if raw == "":
        return ""
    if raw == "[]":
        return []
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return _strip_quotes(raw)


def _preprocess_yaml(text: str) -> List[Tuple[int, str]]:
    lines: List[Tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        stripped = raw_line.lstrip(" ")
        if stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(stripped)
        lines.append((indent, stripped.rstrip()))
    return lines


def _parse_mapping(lines: List[Tuple[int, str]], start: int, indent: int) -> Tuple[Dict[str, Any], int]:
    result: Dict[str, Any] = {}
    index = start
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"Unexpected indentation near '{content}'.")
        if content.startswith("- "):
            break
        key, sep, raw_value = content.partition(":")
        if not sep:
            raise ValueError(f"Invalid mapping line '{content}'.")
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            result[key] = _parse_scalar(raw_value)
            index += 1
            continue
        index += 1
        if index >= len(lines) or lines[index][0] <= indent:
            result[key] = {}
            continue
        next_indent, next_content = lines[index]
        if next_content.startswith("- "):
            value, index = _parse_list(lines, index, next_indent)
        else:
            value, index = _parse_mapping(lines, index, next_indent)
        result[key] = value
    return result, index


def _parse_list(lines: List[Tuple[int, str]], start: int, indent: int) -> Tuple[List[Any], int]:
    items: List[Any] = []
    index = start
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent or not content.startswith("- "):
            break
        remainder = content[2:].strip()
        if remainder == "":
            index += 1
            if index >= len(lines) or lines[index][0] <= indent:
                items.append("")
                continue
            next_indent, next_content = lines[index]
            if next_content.startswith("- "):
                value, index = _parse_list(lines, index, next_indent)
            else:
                value, index = _parse_mapping(lines, index, next_indent)
            items.append(value)
            continue
        if ":" in remainder:
            key, sep, raw_value = remainder.partition(":")
            item: Dict[str, Any] = {}
            if not sep:
                raise ValueError(f"Invalid list item '{content}'.")
            key = key.strip()
            raw_value = raw_value.strip()
            if raw_value:
                item[key] = _parse_scalar(raw_value)
                index += 1
            else:
                index += 1
                if index >= len(lines) or lines[index][0] <= indent:
                    item[key] = {}
                else:
                    next_indent, next_content = lines[index]
                    if next_content.startswith("- "):
                        value, index = _parse_list(lines, index, next_indent)
                    else:
                        value, index = _parse_mapping(lines, index, next_indent)
                    item[key] = value
            child_indent = indent + 2
            while index < len(lines):
                next_indent = lines[index][0]
                if next_indent < child_indent:
                    break
                if next_indent != child_indent or lines[index][1].startswith("- "):
                    break
                nested_mapping, index = _parse_mapping(lines, index, child_indent)
                item.update(nested_mapping)
            items.append(item)
            continue
        items.append(_parse_scalar(remainder))
        index += 1
    return items, index


def parse_yaml_subset(text: str) -> Dict[str, Any]:
    lines = _preprocess_yaml(text)
    if not lines:
        return {}
    parsed, index = _parse_mapping(lines, 0, 0)
    if index != len(lines):
        raise ValueError("Unable to parse complete YAML manifest.")
    return parsed


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    raw = str(value)
    if raw == "" or any(ch in raw for ch in [":", "#", '"', "'"]) or raw.strip() != raw:
        return f'"{raw}"'
    return raw


def _dump_yaml_lines(value: Any, indent: int = 0) -> List[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: List[str] = []
        for key, item in value.items():
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{prefix}{key}: {{}}")
                    continue
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            elif isinstance(item, list):
                if not item:
                    lines.append(f"{prefix}{key}: []")
                    continue
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, nested in item.items():
                    if isinstance(nested, (dict, list)):
                        if first:
                            lines.append(f"{prefix}- {key}:")
                            lines.extend(_dump_yaml_lines(nested, indent + 4))
                            first = False
                            continue
                        lines.append(f"{prefix}  {key}:")
                        lines.extend(_dump_yaml_lines(nested, indent + 4))
                        continue
                    if first:
                        lines.append(f"{prefix}- {key}: {_yaml_scalar(nested)}")
                        first = False
                    else:
                        lines.append(f"{prefix}  {key}: {_yaml_scalar(nested)}")
                if first:
                    lines.append(f"{prefix}- {{}}")
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_dump_yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{_yaml_scalar(value)}"]


def dump_yaml_subset(value: Dict[str, Any]) -> str:
    return "\n".join(_dump_yaml_lines(value)) + "\n"


def write_yaml_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml_subset(payload), encoding="utf-8")


def find_config(start: Path) -> Optional[Path]:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / "aspis.yaml"
        if candidate.exists():
            return candidate
    return None


def resolve_path_anchored(value: str, anchor_dir: Path) -> Path:
    path = Path(str(value).strip())
    if path.is_absolute():
        return path.resolve()
    return (anchor_dir / path).resolve()


def discover_governance_doc(docs_root: Path) -> Path:
    if not docs_root.exists():
        raise FileNotFoundError(f"Docs root does not exist: {docs_root}")
    candidates = sorted(
        path for path in docs_root.rglob("*.md")
        if path.is_file() and "Governance" in path.name
    )
    if not candidates:
        raise FileNotFoundError(f"No governance doc found in {docs_root}")
    return candidates[0]


def protocol_origin_doc_id() -> str:
    return "aspis.doc.governance.origin"


def instance_origin_doc_id(namespace: str) -> str:
    normalized = normalize_namespace(namespace)
    return f"{normalized}.doc.governance.origin"


def normalize_namespace(namespace: str) -> str:
    normalized = namespace.strip().lower()
    if not normalized or not NAMESPACE_TOKEN_RE.fullmatch(normalized):
        raise ValueError(f"Invalid namespace '{namespace}'. Use lowercase letters, numbers, hyphens, or underscores.")
    return normalized


def namespace_from_doc_domain(doc_domain_or_namespace: str) -> str:
    raw = doc_domain_or_namespace.strip().lower()
    if not raw:
        raise ValueError("doc_domain/namespace selector cannot be empty.")
    if NAMESPACE_TOKEN_RE.fullmatch(raw):
        return raw
    if not IDENTITY_RE.fullmatch(raw):
        raise ValueError(
            f"Invalid doc_domain/namespace selector '{doc_domain_or_namespace}'. "
            "Expected a namespace token or dotted domain identity."
        )
    return raw.split(".", 1)[0]


def select_target_instance(
    manifest: WorkspaceManifest,
    doc_domain_or_namespace: Optional[str],
) -> AuthoritySurface:
    if not manifest.instances:
        raise ValueError("aspis lint requires at least one configured instance in aspis.yaml.")

    if doc_domain_or_namespace is None or not str(doc_domain_or_namespace).strip():
        if len(manifest.instances) == 1:
            return manifest.instances[0]
        raise ValueError(
            "aspis lint requires a target doc_domain/namespace when multiple instances are configured."
        )

    namespace = namespace_from_doc_domain(doc_domain_or_namespace)
    matches = [surface for surface in manifest.instances if surface.namespace == namespace]
    if len(matches) != 1:
        raise ValueError(
            f"doc_domain/namespace selector '{doc_domain_or_namespace}' resolves to {len(matches)} "
            "instance(s); expected exactly one."
        )
    return matches[0]


def instance_registry_path(instance_surface: AuthoritySurface) -> Path:
    if instance_surface.surface_kind != "instance":
        raise ValueError("instance_registry_path requires an instance authority surface.")
    return (instance_surface.docs_root / ".aspis" / "aspis.registry.yaml").resolve()


def default_instance_folder_name(namespace: str) -> str:
    return f"{normalize_namespace(namespace)} - ASPIS"


def instance_origin_template(namespace: str) -> str:
    normalized = normalize_namespace(namespace)
    doc_id = instance_origin_doc_id(normalized)
    return "\n".join([
        "---",
        "status: canonical",
        "doc_class: governance",
        "policy_role: owner",
        f"doc_id: {doc_id}",
        "---",
        "",
        "## Purpose",
        "",
        f"{normalized} is an ASPIS instance governance surface built on the ASPIS protocol.",
        "",
        f"This document is the canonical owner contract for the {normalized} instance. It implements the ASPIS protocol surface from `ASPIS/` and must not redefine protocol-owned contracts.",
        "",
    ])


def _legacy_manifest_payload(config_path: Path, cwd: Path) -> Dict[str, Any]:
    root = config_path.parent if config_path else cwd.resolve()
    return {
        "workspace": {
            "name": root.name,
            "protocol_root": "ASPIS",
        },
        "instances": [],
    }


def _normalize_surface_entry(
    entry: Dict[str, Any],
    anchor_dir: Path,
) -> AuthoritySurface:
    namespace = normalize_namespace(str(entry.get("namespace", "")).strip())
    root_raw = str(entry.get("root", "")).strip()
    if not root_raw:
        raise ValueError(f"Instance '{namespace}' is missing required field 'root'.")
    docs_root = resolve_path_anchored(root_raw, anchor_dir)
    governance_raw = str(entry.get("governance_doc", "")).strip()
    governance_doc = resolve_path_anchored(governance_raw, anchor_dir) if governance_raw else discover_governance_doc(docs_root)
    lineage = entry.get("lineage", {})
    if not isinstance(lineage, dict):
        raise ValueError(f"Instance '{namespace}' lineage must be a mapping.")
    normalized_lineage = dict(lineage)
    normalized_lineage.setdefault("instance_type", "aspis_instance")
    return AuthoritySurface(
        surface_kind="instance",
        namespace=namespace,
        docs_root=docs_root,
        governance_doc=governance_doc,
        lineage=normalized_lineage,
    )


def default_manifest(config_path: Path) -> Dict[str, Any]:
    return {
        "workspace": {
            "name": config_path.parent.name,
            "protocol_root": "ASPIS",
        },
        "instances": [],
    }


def load_workspace_manifest(config: Optional[str], cwd: Path) -> WorkspaceManifest:
    config_path = Path(config).resolve() if config else find_config(cwd)
    if config and config_path and not config_path.exists():
        raise FileNotFoundError(f"Config file does not exist: {config_path}")
    if config_path is None:
        config_path = (cwd / "aspis.yaml").resolve()
        raw_payload = default_manifest(config_path)
    else:
        raw_text = config_path.read_text(encoding="utf-8")
        parsed = parse_yaml_subset(raw_text)
        if "workspace" not in parsed and "project" in parsed:
            parsed = _legacy_manifest_payload(config_path, cwd)
        raw_payload = parsed

    anchor_dir = config_path.parent.resolve()
    workspace_block = raw_payload.get("workspace", {})
    if not isinstance(workspace_block, dict):
        raise ValueError("aspis.yaml field 'workspace' must be a mapping.")

    workspace_name = str(workspace_block.get("name", anchor_dir.name)).strip() or anchor_dir.name
    protocol_root_raw = str(workspace_block.get("protocol_root", "ASPIS")).strip() or "ASPIS"
    protocol_root = resolve_path_anchored(protocol_root_raw, anchor_dir)

    protocol_governance_raw = str(workspace_block.get("protocol_governance_doc", "")).strip()
    if protocol_governance_raw:
        protocol_governance_doc = resolve_path_anchored(protocol_governance_raw, anchor_dir)
    else:
        protocol_governance_doc = discover_governance_doc(protocol_root) if protocol_root.exists() else (protocol_root / "0.00 - Governance: Origin.md").resolve()

    instances_raw = raw_payload.get("instances", [])
    if not isinstance(instances_raw, list):
        raise ValueError("aspis.yaml field 'instances' must be a list.")
    instances = [_normalize_surface_entry(item, anchor_dir) for item in instances_raw if isinstance(item, dict)]

    return WorkspaceManifest(
        config_path=config_path,
        workspace_root=anchor_dir,
        workspace_name=workspace_name,
        protocol_root=protocol_root,
        protocol_governance_doc=protocol_governance_doc,
        instances=instances,
    )


def resolve_protocol_surface(manifest: WorkspaceManifest) -> AuthoritySurface:
    return AuthoritySurface(
        surface_kind="protocol",
        namespace="aspis",
        docs_root=manifest.protocol_root,
        governance_doc=manifest.protocol_governance_doc,
        lineage={"instance_type": "protocol_origin"},
    )


def manifest_to_payload(manifest: WorkspaceManifest) -> Dict[str, Any]:
    def rel(path: Path) -> str:
        try:
            return path.resolve().relative_to(manifest.workspace_root.resolve()).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    payload: Dict[str, Any] = {
        "workspace": {
            "name": manifest.workspace_name,
            "protocol_root": rel(manifest.protocol_root),
            "protocol_governance_doc": rel(manifest.protocol_governance_doc),
        },
        "instances": [],
    }
    for surface in manifest.instances:
        entry: Dict[str, Any] = {
            "namespace": surface.namespace,
            "root": rel(surface.docs_root),
            "governance_doc": rel(surface.governance_doc),
        }
        if surface.lineage:
            entry["lineage"] = dict(surface.lineage)
        payload["instances"].append(entry)
    return payload


def save_workspace_manifest(manifest: WorkspaceManifest) -> None:
    write_yaml_file(manifest.config_path, manifest_to_payload(manifest))


def make_manifest(
    config_path: Path,
    workspace_name: str,
    protocol_root: Path,
    protocol_governance_doc: Path,
    instances: Iterable[AuthoritySurface],
) -> WorkspaceManifest:
    return WorkspaceManifest(
        config_path=config_path.resolve(),
        workspace_root=config_path.parent.resolve(),
        workspace_name=workspace_name,
        protocol_root=protocol_root.resolve(),
        protocol_governance_doc=protocol_governance_doc.resolve(),
        instances=list(instances),
    )
