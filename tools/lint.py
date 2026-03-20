#!/usr/bin/env python3
"""
ASPIS workspace linter and registry builder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import clause as clause_runtime
import workspace as workspace_runtime

DEFAULT_NEXT_ACTION = "review lint findings and correct the governing authority surface"
UNRESOLVED_DOMAIN_REFERENCE = "UNRESOLVED_DOMAIN_REFERENCE"
DUPLICATE_DOMAIN_REFERENCE = "DUPLICATE_DOMAIN_REFERENCE"
INVALID_REFERENCE_SCAN_SCOPE = "INVALID_REFERENCE_SCAN_SCOPE"
UNRESOLVED_FOLLOW_UP_DOMAINS = [
    "aspis.entry",
    "aspis.clause.section",
    "aspis.clause.schema",
    "aspis.registry.shape.schema",
]
DUPLICATE_FOLLOW_UP_DOMAINS = [
    "aspis.entry",
    "aspis.clause.section",
    "aspis.clause.schema",
]
INVALID_SCOPE_FOLLOW_UP_DOMAINS = [
    "aspis.clause.section",
    "aspis.clause.schema",
]
NON_DOMAIN_SUFFIXES = {
    "md",
    "markdown",
    "txt",
    "rst",
    "json",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "py",
    "js",
    "ts",
    "sh",
}


def _rel_from_root(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _issue(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"code": code, "message": message}
    payload.update({key: value for key, value in extra.items() if value not in ("", None, [], {})})
    return payload


def _sort_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _key_value(issue: Dict[str, Any], key: str) -> str:
        value = issue.get(key, "")
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)

    return sorted(
        issues,
        key=lambda item: (
            _key_value(item, "code"),
            _key_value(item, "file"),
            _key_value(item, "clause_id"),
            _key_value(item, "reference"),
            _key_value(item, "message"),
        ),
    )


def _surface_payload(surface: workspace_runtime.AuthoritySurface, workspace_root: Path) -> Dict[str, Any]:
    return {
        "surface_kind": surface.surface_kind,
        "namespace": surface.namespace,
        "root": _rel_from_root(workspace_root, surface.docs_root),
        "governance_doc": _rel_from_root(workspace_root, surface.governance_doc),
        "lineage": dict(surface.lineage),
    }


def _validate_surface_identity(
    surface: workspace_runtime.AuthoritySurface,
    workspace_root: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    issues: List[Dict[str, Any]] = []
    governance_text = surface.governance_doc.read_text(encoding="utf-8")
    frontmatter = clause_runtime.parse_frontmatter(governance_text)
    doc_id = str(frontmatter.get("doc_id", "")).strip()
    doc_class = str(frontmatter.get("doc_class", "")).strip().lower()
    policy_role = str(frontmatter.get("policy_role", "")).strip().lower()

    if surface.surface_kind == "protocol":
        expected_doc_id = workspace_runtime.protocol_origin_doc_id()
        expected_instance_type = "protocol_origin"
    else:
        expected_doc_id = workspace_runtime.instance_origin_doc_id(surface.namespace)
        expected_instance_type = "aspis_instance"

    if doc_id != expected_doc_id:
        issues.append(_issue(
            "INVALID_GOVERNANCE_ORIGIN_DOC_ID",
            f"Governance origin doc_id '{doc_id}' does not match expected '{expected_doc_id}'.",
            file=_rel_from_root(workspace_root, surface.governance_doc),
        ))
    if doc_class != "governance":
        issues.append(_issue(
            "INVALID_GOVERNANCE_DOC_CLASS",
            f"Governance origin must declare doc_class: governance, found '{doc_class or 'missing'}'.",
            file=_rel_from_root(workspace_root, surface.governance_doc),
        ))
    if policy_role != "owner":
        issues.append(_issue(
            "INVALID_GOVERNANCE_POLICY_ROLE",
            f"Governance origin must declare policy_role: owner, found '{policy_role or 'missing'}'.",
            file=_rel_from_root(workspace_root, surface.governance_doc),
        ))

    lineage = dict(surface.lineage)
    instance_type = str(lineage.get("instance_type", "")).strip() or expected_instance_type
    if instance_type != expected_instance_type:
        issues.append(_issue(
            "INVALID_LINEAGE_INSTANCE_TYPE",
            f"Surface '{surface.namespace}' must declare lineage.instance_type '{expected_instance_type}', found '{instance_type}'.",
            file=_rel_from_root(workspace_root, surface.governance_doc),
        ))

    return issues, {
        "doc_id": doc_id,
        "doc_class": doc_class,
        "policy_role": policy_role,
    }


def _validate_surface_namespaces(
    clauses: Dict[str, Dict[str, Any]],
    source_to_surface: Dict[str, workspace_runtime.AuthoritySurface],
    workspace_root: Path,
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for clause_id, clause in clauses.items():
        source_file = str(clause.get("source_file", ""))
        surface = source_to_surface.get(source_file)
        if surface is None:
            issues.append(_issue(
                "UNKNOWN_AUTHORITY_SURFACE",
                f"Clause '{clause_id}' could not be mapped to an authority surface.",
                file=_rel_from_root(workspace_root, Path(source_file)) if source_file else "",
            ))
            continue
        clause_namespace = clause_id.split(".", 1)[0]
        if clause_namespace != surface.namespace:
            issues.append(_issue(
                "INVALID_CLAUSE_NAMESPACE",
                f"Clause '{clause_id}' must use namespace '{surface.namespace}' for the '{surface.surface_kind}' surface.",
                file=_rel_from_root(workspace_root, Path(source_file)),
            ))
    return issues


def _registry_entry(
    clause: Dict[str, Any],
    surface: workspace_runtime.AuthoritySurface,
    workspace_root: Path,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "id": clause.get("id"),
        "namespace": surface.namespace,
        "surface_kind": surface.surface_kind,
        "owner_doc": clause.get("owner_doc"),
        "source_doc_id": clause.get("source_doc_id"),
        "source_file": _rel_from_root(workspace_root, Path(str(clause.get("source_file", "")))),
        "kind": clause.get("kind"),
        "status": clause.get("status"),
        "meta": bool(clause.get("meta", False)),
        "yield": bool(clause.get("yield", False)),
    }
    paths = clause.get("paths", [])
    if paths:
        entry["paths"] = list(paths)
    keywords = clause.get("keywords", [])
    if keywords:
        entry["keywords"] = list(keywords)
    registry_slots = clause.get("registry_slots", {})
    if registry_slots:
        entry["registry_slots"] = registry_slots
    return entry


def build_registry_payload(
    manifest: workspace_runtime.WorkspaceManifest,
    target_instance: workspace_runtime.AuthoritySurface,
    target_registry_path: Path,
    surface_details: Dict[str, Dict[str, str]],
    clauses: Dict[str, Dict[str, Any]],
    source_to_surface: Dict[str, workspace_runtime.AuthoritySurface],
) -> Dict[str, Any]:
    protocol_surface = workspace_runtime.resolve_protocol_surface(manifest)
    entries: List[Dict[str, Any]] = []
    for clause_id in sorted(clauses):
        clause = clauses[clause_id]
        surface = source_to_surface[str(clause.get("source_file", ""))]
        entries.append(_registry_entry(clause, surface, manifest.workspace_root))

    payload: Dict[str, Any] = {
        "workspace": {
            "name": manifest.workspace_name,
            "protocol_root": _rel_from_root(manifest.workspace_root, manifest.protocol_root),
        },
        "registry": {
            "generated": True,
            "path": _rel_from_root(manifest.workspace_root, target_registry_path),
        },
        "protocol": {
            **_surface_payload(protocol_surface, manifest.workspace_root),
            "origin_doc_id": surface_details.get("protocol", {}).get("doc_id", ""),
        },
        "instances": [{
            **_surface_payload(target_instance, manifest.workspace_root),
            "origin_doc_id": surface_details.get(target_instance.namespace, {}).get("doc_id", ""),
        }],
        "entries": entries,
    }
    return payload


def _build_lint_result(
    manifest: workspace_runtime.WorkspaceManifest,
    surfaces: List[workspace_runtime.AuthoritySurface],
    target_instance: workspace_runtime.AuthoritySurface,
    target_registry_path: Path,
    issues: List[Dict[str, Any]],
    doc_paths: List[Path],
    clauses: Dict[str, Dict[str, Any]],
    target_selector: Optional[str],
) -> Dict[str, Any]:
    sorted_issues = _sort_issues(issues)
    blocking = bool(sorted_issues)
    selector = (target_selector or "").strip()
    if selector:
        selection_source = "explicit_target"
    elif len(manifest.instances) == 1:
        selection_source = "inferred_single_instance"
    else:
        selection_source = "unresolved"
    authority_context = {
        "surface_kind": target_instance.surface_kind,
        "target_namespace": target_instance.namespace,
        "selection_source": selection_source,
    }
    return {
        "status": "error" if blocking else "ok",
        "blocking": blocking,
        "issues": sorted_issues,
        "next_actions": DEFAULT_NEXT_ACTION,
        "registry_path": _rel_from_root(manifest.workspace_root, target_registry_path),
        "authority_context": authority_context,
        "summary": {
            "protocol_surfaces": 1,
            "instance_surfaces": 1,
            "documents": len(doc_paths),
            "registered_clauses": len(clauses),
            "namespaces": sorted(surface.namespace for surface in surfaces),
            "target_namespace": target_instance.namespace,
            "authority_context": authority_context,
        },
        "source_authority": {
            "source_surfaces": [_surface_payload(surface, manifest.workspace_root) for surface in surfaces],
        },
    }


def _validate_reference_resolution(
    clauses: Dict[str, Dict[str, Any]],
    effective_registry_ids: Set[str],
    workspace_root: Path,
) -> List[Dict[str, Any]]:
    def _is_navigable_domain_token(token: str) -> bool:
        parts = [part for part in token.split(".") if part]
        if len(parts) < 2:
            return False
        # Ignore numeric version-like tokens (e.g. 0.00).
        if parts[0].isdigit():
            return False
        # Ignore file-like tokens (e.g. aspis.py, aspis.yaml, origin.md).
        if len(parts) == 2 and parts[1] in NON_DOMAIN_SUFFIXES:
            return False
        # Ignore config-field style paths (e.g. workspace.protocol_root).
        if len(parts) == 2 and "_" in parts[1]:
            return False
        return True

    issues: List[Dict[str, Any]] = []
    for clause_id in sorted(clauses):
        clause = clauses[clause_id]
        reference_scan = clause.get("references")
        if not isinstance(reference_scan, dict):
            continue
        source_file = str(clause.get("source_file", ""))
        source_rel = _rel_from_root(workspace_root, Path(source_file)) if source_file else ""
        clause_identity = str(clause.get("id", "")).strip().lower()

        scan_error_raw = reference_scan.get("scan_error")
        scan_error = scan_error_raw.strip() if isinstance(scan_error_raw, str) else ""
        if scan_error:
            issues.append(_issue(
                INVALID_REFERENCE_SCAN_SCOPE,
                f"Clause '{clause_identity}' reference scan state is invalid ({scan_error}).",
                reason_code=INVALID_REFERENCE_SCAN_SCOPE,
                clause_id=clause_identity,
                file=source_rel,
                follow_up_domains=INVALID_SCOPE_FOLLOW_UP_DOMAINS,
            ))
            continue

        occurrences_raw = reference_scan.get("occurrences", [])
        if not isinstance(occurrences_raw, list):
            issues.append(_issue(
                INVALID_REFERENCE_SCAN_SCOPE,
                f"Clause '{clause_identity}' reference scan occurrences are malformed.",
                reason_code=INVALID_REFERENCE_SCAN_SCOPE,
                clause_id=clause_identity,
                file=source_rel,
                follow_up_domains=INVALID_SCOPE_FOLLOW_UP_DOMAINS,
            ))
            continue
        token_counts: Dict[str, int] = {}
        for occurrence in occurrences_raw:
            if not isinstance(occurrence, dict):
                continue
            token = str(occurrence.get("token", "")).strip().lower()
            if not token:
                continue
            token_counts[token] = token_counts.get(token, 0) + 1

        for token in sorted(token_counts):
            if token == clause_identity:
                continue
            if not _is_navigable_domain_token(token):
                continue
            if token_counts[token] > 1:
                issues.append(_issue(
                    DUPLICATE_DOMAIN_REFERENCE,
                    f"Clause '{clause_identity}' repeats domain reference '{token}' within one scan scope.",
                    reason_code=DUPLICATE_DOMAIN_REFERENCE,
                    clause_id=clause_identity,
                    reference=token,
                    file=source_rel,
                    follow_up_domains=DUPLICATE_FOLLOW_UP_DOMAINS,
                ))
            if token not in effective_registry_ids:
                issues.append(_issue(
                    UNRESOLVED_DOMAIN_REFERENCE,
                    f"Clause '{clause_identity}' references '{token}' but no effective registry entry resolves it.",
                    reason_code=UNRESOLVED_DOMAIN_REFERENCE,
                    clause_id=clause_identity,
                    reference=token,
                    file=source_rel,
                    follow_up_domains=UNRESOLVED_FOLLOW_UP_DOMAINS,
                ))
    return issues


def run_lint(config: Optional[str], cwd: Path, target: Optional[str] = None) -> Dict[str, Any]:
    manifest = workspace_runtime.load_workspace_manifest(config, cwd)
    protocol_surface = workspace_runtime.resolve_protocol_surface(manifest)
    target_instance = workspace_runtime.select_target_instance(manifest, target)
    target_registry_path = workspace_runtime.instance_registry_path(target_instance)
    surfaces = [protocol_surface, target_instance]

    issues: List[Dict[str, Any]] = []
    namespaces_seen: Dict[str, str] = {}
    source_to_surface: Dict[str, workspace_runtime.AuthoritySurface] = {}
    doc_paths: List[Path] = []
    surface_details: Dict[str, Dict[str, str]] = {}

    for surface in surfaces:
        if surface.namespace in namespaces_seen:
            issues.append(_issue(
                "DUPLICATE_NAMESPACE",
                f"Namespace '{surface.namespace}' is declared by multiple authority surfaces.",
                file=_rel_from_root(manifest.workspace_root, surface.governance_doc),
            ))
        namespaces_seen[surface.namespace] = surface.surface_kind

        if not surface.docs_root.exists():
            issues.append(_issue(
                "MISSING_DOCS_ROOT",
                f"Docs root does not exist: {surface.docs_root}",
                file=_rel_from_root(manifest.workspace_root, surface.docs_root),
            ))
            continue
        if not surface.governance_doc.exists():
            issues.append(_issue(
                "MISSING_GOVERNANCE_DOC",
                f"Governance doc does not exist: {surface.governance_doc}",
                file=_rel_from_root(manifest.workspace_root, surface.governance_doc),
            ))
            continue

        surface_issues, detail = _validate_surface_identity(surface, manifest.workspace_root)
        issues.extend(surface_issues)
        detail_key = "protocol" if surface.surface_kind == "protocol" else surface.namespace
        surface_details[detail_key] = detail

        for doc_path in clause_runtime.iter_markdown_docs(surface.docs_root):
            doc_paths.append(doc_path)
            source_to_surface[doc_path.resolve().as_posix()] = surface

    clauses, clause_issues, _ = clause_runtime.index_documents(doc_paths)
    for issue in clause_issues:
        file_path = str(issue.get("file", "")).strip()
        if file_path:
            issue = dict(issue)
            issue["file"] = _rel_from_root(manifest.workspace_root, Path(file_path))
        issues.append(issue)
    issues.extend(_validate_surface_namespaces(clauses, source_to_surface, manifest.workspace_root))
    issues.extend(_validate_reference_resolution(clauses, set(clauses.keys()), manifest.workspace_root))

    can_build_registry = ("protocol" in surface_details) and (target_instance.namespace in surface_details)
    if can_build_registry:
        registry_payload = build_registry_payload(
            manifest,
            target_instance,
            target_registry_path,
            surface_details,
            clauses,
            source_to_surface,
        )
        workspace_runtime.write_yaml_file(target_registry_path, registry_payload)

    return _build_lint_result(
        manifest,
        surfaces,
        target_instance,
        target_registry_path,
        issues,
        doc_paths,
        clauses,
        target,
    )


def _parse_args(argv: List[str]) -> Dict[str, Optional[str]]:
    options: Dict[str, Optional[str]] = {"config": None, "target": None}
    positionals: List[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--config":
            if index + 1 >= len(argv):
                raise ValueError("Option '--config' requires a value.")
            options["config"] = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--config="):
            options["config"] = arg.partition("=")[2].strip()
            index += 1
            continue
        if arg.startswith("-"):
            raise ValueError(f"Unknown option: '{arg}'")
        positionals.append(arg)
        index += 1
    if len(positionals) > 1:
        raise ValueError("lint accepts at most one positional target selector.")
    if positionals:
        options["target"] = positionals[0]
    return options


def _write_json(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        options = _parse_args(raw_argv)
        payload = run_lint(options.get("config"), Path.cwd(), options.get("target"))
    except (FileNotFoundError, OSError, ValueError) as exc:
        payload = {
            "status": "error",
            "blocking": True,
            "issues": [_issue("LINT_CONFIGURATION_ERROR", str(exc))],
            "next_actions": DEFAULT_NEXT_ACTION,
            "authority_context": {
                "surface_kind": "unknown",
                "target_namespace": "unknown",
                "selection_source": "unresolved",
            },
        }
    _write_json(payload)
    if payload.get("status") == "error" and payload.get("blocking"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
