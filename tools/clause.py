#!/usr/bin/env python3
"""
Read-only clause query layer. Paths-only semantics.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REGISTRY_MEMORY: Dict[str, Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]], Dict[str, float]]] = {}

DOC_PREFIX_RE = re.compile(r"^(\d+\.\d+)\s*-\s*")
SCHEMA_ID_RE = re.compile(r"^[a-z0-9_-]+(?:\.[a-z0-9_-]+)+\.(?:schema|interface)$", re.IGNORECASE)
CLAUSE_ID_RE = re.compile(r"^[a-z0-9_-]+(?:\.[a-z0-9_-]+)+$", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+")
TEMPLATE_TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
REFERENCE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])([a-z0-9_-]+(?:\.[a-z0-9_-]+)+)(?![A-Za-z0-9_/\-])(?!\.[a-z0-9_-])",
    re.IGNORECASE,
)
ALLOWED_CLAUSE_KINDS = {"contract", "workflow", "guidance", "information", "specification", "route", "rule"}
CLAUSE_REASON_CODE = "COMPLIANCE_CRITERIA_UNMET"
MALFORMED_HEADER_CODE = "MALFORMED_HEADER"
UNKNOWN_CLAUSE_CODE = "UNKNOWN_CLAUSE"
DEFAULT_NEXT_ACTION = "seek paths in context. Match to user's request and follow them accordingly."


def _strip_yaml_scalar(value: str) -> str:
    return value.strip().strip('"').strip("'")


def parse_frontmatter(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return data
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep:
            data[key.strip().lower()] = _strip_yaml_scalar(value)
    return data


def _parse_doc_identity(doc_path: Path, text: str) -> str:
    frontmatter = parse_frontmatter(text)
    doc_id = str(frontmatter.get("doc_id", "")).strip()
    if doc_id:
        return doc_id
    match = DOC_PREFIX_RE.match(doc_path.name)
    if match:
        return match.group(1)
    return doc_path.stem


def _parse_bool(raw: str) -> Optional[bool]:
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def _normalize_clause_identity(raw: str) -> str:
    return raw.strip().lower()


def _is_valid_clause_identity(identity: str) -> bool:
    return bool(CLAUSE_ID_RE.fullmatch(identity.strip()))


def _extract_heading_tokens(line: str) -> List[str]:
    return [token.strip() for token in re.findall(r"`([^`]+)`", line)]


def _heading_level(line: str) -> Optional[int]:
    match = HEADING_RE.match(line)
    if not match:
        return None
    return len(match.group(1))


def _code_fence_marker(line: str) -> Optional[str]:
    stripped = line.strip()
    if stripped.startswith("```"):
        return "`"
    if stripped.startswith("~~~"):
        return "~"
    return None


def _next_fence_state(current_marker: Optional[str], line: str) -> Optional[str]:
    marker = _code_fence_marker(line)
    if marker is None:
        return current_marker
    if current_marker is None:
        return marker
    if marker == current_marker:
        return None
    return current_marker


def _heading_identity_context(lines: List[str], header_start_idx: int) -> Tuple[str, Optional[str], Optional[str]]:
    heading_line = ""
    for idx in range(header_start_idx - 1, -1, -1):
        if _heading_level(lines[idx].strip()) is not None:
            heading_line = lines[idx].strip()
            break
    if not heading_line:
        return "not_inferable", None, None

    tokens = [token.lower() for token in _extract_heading_tokens(heading_line) if token.strip()]
    if not tokens:
        return "not_inferable", None, None

    invalid_tokens = [token for token in tokens if not _is_valid_clause_identity(token)]
    if invalid_tokens:
        return "ambiguous", None, f"Heading identity token '{invalid_tokens[0]}' does not satisfy clause identity grammar."

    if len(tokens) > 1:
        return "ambiguous", None, "Heading contains multiple clause identity candidates."

    token = tokens[0]
    if SCHEMA_ID_RE.fullmatch(token) or CLAUSE_ID_RE.fullmatch(token):
        return "inferable", token, None
    return "not_inferable", None, None


def _value_contains_template(raw: str) -> bool:
    value = raw.strip()
    return ("{" in value) or ("}" in value)


def _resolve_owner_doc(raw_owner_doc: str, owner_doc_id: str) -> Tuple[str, Optional[str]]:
    owner_doc_raw = raw_owner_doc.strip()
    if not owner_doc_raw:
        return "", None
    if not _value_contains_template(owner_doc_raw):
        return owner_doc_raw, None
    token_matches = TEMPLATE_TOKEN_RE.findall(owner_doc_raw)
    if not token_matches:
        return "", "owner_doc template token grammar is invalid."
    normalized = [token.strip().lower() for token in token_matches if token.strip()]
    if len(normalized) != 1 or owner_doc_raw != f"{{{token_matches[0]}}}":
        return "", "owner_doc templating must be a single deterministic token expression."
    token = normalized[0]
    if token != "doc_id":
        return "", f"owner_doc template token '{token}' is unresolved."
    if not owner_doc_id.strip():
        return "", "owner_doc template token '{doc_id}' is unresolved."
    return owner_doc_id.strip(), None


def _parse_clause_directive_block(
    block_lines: List[str],
    owner_doc_id: str,
    *,
    inferred_clause_identity: Optional[str],
    header_identity_state: str,
    header_identity_issue: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    """Parse <!-- aspis:clause ... --> block. Supports paths and optional keywords; FAIL on refs."""
    issues: List[Dict[str, str]] = []
    data: Dict[str, Any] = {"paths": [], "keywords": []}
    current_list: Optional[str] = None

    for raw in block_lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- "):
            if current_list not in {"paths", "keywords"}:
                continue
            data[current_list].append(line[2:].strip())
            continue
        if ":" not in line:
            issues.append({"code": CLAUSE_REASON_CODE, "message": f"Invalid clause directive line '{line}'."})
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "refs":
            issues.append({
                "code": CLAUSE_REASON_CODE,
                "message": "Clause directive uses 'refs'; paths-only semantics required. Use 'paths' instead.",
            })
            continue
        if key == "paths":
            current_list = "paths"
            data["paths"] = []
            continue
        if key == "keywords":
            current_list = None
            data["keywords"] = [value] if value else []
            if not value:
                current_list = "keywords"
            continue
        current_list = None
        data[key] = value

    explicit_clause_id_raw = str(data.get("id", "")).strip()
    kind = str(data.get("kind", "")).strip().lower()
    status = str(data.get("status", "")).strip().lower()
    owner_doc_raw = str(data.get("owner_doc", "")).strip()
    raw_yield = str(data.get("yield", "")).strip()
    raw_meta = str(data.get("meta", "")).strip()
    inferred_clause_id = _normalize_clause_identity(inferred_clause_identity or "")
    explicit_clause_id = _normalize_clause_identity(explicit_clause_id_raw)
    owner_doc, owner_doc_issue = _resolve_owner_doc(owner_doc_raw, owner_doc_id)
    clause_yield = False
    clause_meta = False
    effective_clause_id = ""

    if header_identity_issue:
        issues.append({"code": CLAUSE_REASON_CODE, "message": header_identity_issue})
    if header_identity_state == "ambiguous":
        issues.append({"code": CLAUSE_REASON_CODE, "message": "Ambiguous header-derived clause identity."})

    for non_template_field in ("id", "kind", "status", "yield", "meta"):
        raw_value = str(data.get(non_template_field, "")).strip()
        if raw_value and _value_contains_template(raw_value):
            issues.append({
                "code": CLAUSE_REASON_CODE,
                "message": f"Template tokens are not allowed in clause field '{non_template_field}'.",
            })
    for path_raw in data.get("paths", []):
        if _value_contains_template(str(path_raw)):
            issues.append({
                "code": CLAUSE_REASON_CODE,
                "message": "Template tokens are not allowed in clause field 'paths'.",
            })

    if owner_doc_issue:
        issues.append({"code": CLAUSE_REASON_CODE, "message": owner_doc_issue})
    if raw_yield:
        parsed_yield = _parse_bool(raw_yield)
        if parsed_yield is None:
            issues.append({"code": CLAUSE_REASON_CODE, "message": "Clause yield must be true or false."})
        else:
            clause_yield = parsed_yield
    if raw_meta:
        parsed_meta = _parse_bool(raw_meta)
        if parsed_meta is None:
            issues.append({"code": CLAUSE_REASON_CODE, "message": "Clause meta must be true or false."})
        else:
            clause_meta = parsed_meta
    if explicit_clause_id:
        if not _is_valid_clause_identity(explicit_clause_id):
            issues.append({"code": CLAUSE_REASON_CODE, "message": f"Invalid explicit clause identity '{explicit_clause_id_raw}'."})
    if inferred_clause_id:
        if not _is_valid_clause_identity(inferred_clause_id):
            issues.append({"code": CLAUSE_REASON_CODE, "message": f"Invalid inferred clause identity '{inferred_clause_id}'."})
        elif explicit_clause_id and explicit_clause_id != inferred_clause_id:
            issues.append({
                "code": CLAUSE_REASON_CODE,
                "message": f"Explicit clause id '{explicit_clause_id}' does not match inferred header identity '{inferred_clause_id}'.",
            })
    if explicit_clause_id:
        effective_clause_id = explicit_clause_id
    elif inferred_clause_id:
        effective_clause_id = inferred_clause_id
    else:
        issues.append({"code": CLAUSE_REASON_CODE, "message": "Clause directive is missing required field 'id' when heading identity is not inferable."})

    if not kind:
        issues.append({"code": CLAUSE_REASON_CODE, "message": "Clause directive is missing required field 'kind'."})
    elif kind not in ALLOWED_CLAUSE_KINDS:
        issues.append({"code": CLAUSE_REASON_CODE, "message": f"Unsupported clause kind '{kind}'."})
    if not status:
        issues.append({"code": CLAUSE_REASON_CODE, "message": "Clause directive is missing required field 'status'."})
    if not owner_doc_raw:
        issues.append({"code": CLAUSE_REASON_CODE, "message": "Clause directive is missing required field 'owner_doc'."})
    elif not owner_doc:
        issues.append({"code": CLAUSE_REASON_CODE, "message": "Clause owner_doc is unresolved."})

    paths_out: List[str] = []
    for path_raw in data.get("paths", []):
        p = str(path_raw).strip()
        if p and _is_valid_clause_identity(p):
            paths_out.append(p.lower())
        elif p:
            issues.append({"code": CLAUSE_REASON_CODE, "message": f"Invalid path identifier '{path_raw}'."})
    if not paths_out:
        issues.append({"code": CLAUSE_REASON_CODE, "message": "Clause directive is missing required field 'paths' (non-empty list)."})
    keywords_out: List[str] = []
    for keyword_raw in data.get("keywords", []):
        keyword = str(keyword_raw).strip().lower()
        if keyword:
            keywords_out.append(keyword)

    clause = {
        "id": effective_clause_id,
        "meta": clause_meta,
        "kind": kind,
        "status": status,
        "owner_doc": owner_doc,
        "yield": clause_yield,
        "paths": paths_out,
        "header_identity_state": header_identity_state,
        "inferred_clause_identity": inferred_clause_id or None,
        "effective_clause_identity": effective_clause_id or None,
        "resolved_owner_doc": owner_doc or None,
    }
    if keywords_out:
        clause["keywords"] = keywords_out
    if not effective_clause_id:
        return None, issues
    return clause, issues


def _parse_registry_slot_value(inline: str, nested_lines: List[str]) -> Any:
    if not nested_lines:
        return inline
    dedented = textwrap.dedent("\n".join(nested_lines)).strip("\n")
    if inline:
        dedented = f"{inline}\n{dedented}" if dedented else inline
    normalized_lines = [line.rstrip() for line in dedented.splitlines() if line.strip()]
    if normalized_lines and all(line.lstrip().startswith("- ") for line in normalized_lines):
        return [line.lstrip()[2:].strip() for line in normalized_lines]
    return dedented.strip()


def _extract_registry_slots(body_lines: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    start = -1
    end = -1
    for idx, line in enumerate(body_lines):
        stripped = line.strip()
        if stripped == "<!-- aspis:registry-slots -->":
            start = idx
        elif stripped == "<!-- /aspis:registry-slots -->" and start != -1:
            end = idx
            break
    if start == -1 or end == -1 or end < start:
        return {}, body_lines

    slot_lines = body_lines[start + 1 : end]
    slots: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_inline = ""
    current_nested: List[str] = []

    def flush_current() -> None:
        nonlocal current_key, current_inline, current_nested
        if current_key is None:
            return
        slots[current_key] = _parse_registry_slot_value(current_inline, current_nested)
        current_key = None
        current_inline = ""
        current_nested = []

    for raw_line in slot_lines:
        stripped = raw_line.strip()
        top_match = re.match(r"^- ([A-Za-z0-9_.\-\[\]]+):(.*)$", stripped)
        if top_match:
            flush_current()
            current_key = top_match.group(1)
            current_inline = top_match.group(2).strip()
            continue
        if current_key is not None:
            current_nested.append(raw_line)
    flush_current()

    remaining = body_lines[:start] + body_lines[end + 1 :]
    return slots, remaining


def _scan_clause_body_references(body_lines: List[str]) -> Dict[str, Any]:
    occurrences: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    inside_fenced_block: Optional[str] = None
    for line_index, raw_line in enumerate(body_lines, start=1):
        next_fence_state = _next_fence_state(inside_fenced_block, raw_line)
        if next_fence_state != inside_fenced_block:
            inside_fenced_block = next_fence_state
            continue
        if inside_fenced_block:
            continue
        for match in REFERENCE_TOKEN_RE.finditer(raw_line):
            token = match.group(1).strip().lower()
            if not _is_valid_clause_identity(token):
                continue
            occurrences.append({
                "token": token,
                "line": line_index,
                "column": match.start(1) + 1,
            })
            counts[token] = counts.get(token, 0) + 1

    duplicates = sorted(token for token, count in counts.items() if count > 1)
    return {
        "scope": "clause_section_body",
        "occurrences": occurrences,
        "tokens": [entry["token"] for entry in occurrences],
        "duplicates": duplicates,
        "scan_error": "unterminated_fenced_code_block" if inside_fenced_block is not None else None,
    }


def _extract_clause_body(
    lines: List[str],
    header_start_idx: int,
    body_start_idx: int,
) -> Tuple[List[str], int]:
    section_level: Optional[int] = None
    for idx in range(header_start_idx - 1, -1, -1):
        level = _heading_level(lines[idx].strip())
        if level is not None:
            section_level = level
            break

    body_end_idx = len(lines)
    inside_fenced_block: Optional[str] = None
    for idx in range(body_start_idx, len(lines)):
        stripped = lines[idx].strip()
        next_fence_state = _next_fence_state(inside_fenced_block, lines[idx])
        if next_fence_state != inside_fenced_block:
            inside_fenced_block = next_fence_state
            continue
        if inside_fenced_block:
            continue
        if stripped == "<!-- aspis:clause":
            body_end_idx = idx
            break
        level = _heading_level(stripped)
        if level is not None and section_level is not None and level <= section_level:
            body_end_idx = idx
            break
    return lines[body_start_idx:body_end_idx], body_end_idx


def _extract_clauses_from_doc(
    doc_path: Path,
    text: str,
    *,
    doc_id: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    clauses: List[Dict[str, Any]] = []
    issues: List[Dict[str, str]] = []
    lines = text.splitlines()
    idx = 0
    inside_fenced_block: Optional[str] = None
    while idx < len(lines):
        stripped = lines[idx].strip()
        next_fence_state = _next_fence_state(inside_fenced_block, lines[idx])
        if next_fence_state != inside_fenced_block:
            inside_fenced_block = next_fence_state
            idx += 1
            continue
        if inside_fenced_block or stripped != "<!-- aspis:clause":
            idx += 1
            continue
        header_start_idx = idx
        idx += 1
        block: List[str] = []
        while idx < len(lines) and lines[idx].strip() != "-->":
            block.append(lines[idx])
            idx += 1
        if idx >= len(lines):
            issues.append({
                "code": MALFORMED_HEADER_CODE,
                "message": "Clause directive header is missing closing '-->' terminator.",
                "file": doc_path.as_posix(),
            })
            break
        header_identity_state, inferred_clause_identity, header_identity_issue = _heading_identity_context(lines, header_start_idx)
        clause, parse_issues = _parse_clause_directive_block(
            block,
            owner_doc_id=doc_id,
            inferred_clause_identity=inferred_clause_identity,
            header_identity_state=header_identity_state,
            header_identity_issue=header_identity_issue,
        )
        body_lines, next_idx = _extract_clause_body(lines, header_start_idx, idx + 1)
        registry_slots, content_lines = _extract_registry_slots(body_lines)
        content = "\n".join(content_lines).strip()
        for issue in parse_issues:
            issue_with_source = dict(issue)
            issue_with_source["file"] = doc_path.as_posix()
            issues.append(issue_with_source)
        if clause is not None:
            reference_scan = _scan_clause_body_references(content_lines)
            clause["source_file"] = doc_path.as_posix()
            clause["registry_slots"] = registry_slots
            clause["content"] = content
            clause["references"] = reference_scan
            clauses.append(clause)
        idx = next_idx
    return clauses, issues


def iter_markdown_docs(docs_root: Path) -> List[Path]:
    return sorted(path for path in docs_root.rglob("*.md") if path.is_file())


def _index_doc_ids(docs_root: Path) -> Dict[str, List[str]]:
    doc_ids: Dict[str, List[str]] = {}
    for doc in iter_markdown_docs(docs_root):
        doc_id = _parse_doc_identity(doc, doc.read_text(encoding="utf-8"))
        doc_ids.setdefault(doc_id, []).append(doc.as_posix())
    return doc_ids


def index_documents(doc_paths: List[Path]) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]], Dict[str, List[str]]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    issues: List[Dict[str, str]] = []
    doc_id_index: Dict[str, List[str]] = {}
    doc_cache: Dict[str, Tuple[Path, str, str]] = {}
    for doc in sorted(path.resolve() for path in doc_paths if path.is_file()):
        text = doc.read_text(encoding="utf-8")
        doc_id = _parse_doc_identity(doc, text)
        doc_cache[doc.as_posix()] = (doc, text, doc_id)
        doc_id_index.setdefault(doc_id, []).append(doc.as_posix())

    for doc_path, (doc, text, doc_id) in doc_cache.items():
        clauses, parse_issues = _extract_clauses_from_doc(doc, text, doc_id=doc_id)
        issues.extend(parse_issues)
        for clause in clauses:
            clause["source_doc_id"] = doc_id
            owner_doc = str(clause.get("owner_doc", "")).strip()
            if owner_doc:
                owner_hits = doc_id_index.get(owner_doc, [])
                if not owner_hits:
                    issues.append({
                        "code": CLAUSE_REASON_CODE,
                        "message": f"Clause owner_doc '{owner_doc}' does not resolve to a governed document.",
                        "file": clause.get("source_file", ""),
                    })
                elif len(owner_hits) > 1:
                    issues.append({
                        "code": CLAUSE_REASON_CODE,
                        "message": f"Clause owner_doc '{owner_doc}' resolves ambiguously to multiple documents.",
                        "file": clause.get("source_file", ""),
                    })
            clause_id = str(clause.get("id", "")).strip().lower()
            if clause_id in by_id:
                issues.append({
                    "code": CLAUSE_REASON_CODE,
                    "message": f"Duplicate clause id '{clause_id}' detected.",
                    "file": clause.get("source_file", ""),
                })
            else:
                by_id[clause_id] = clause
    return by_id, issues, doc_id_index


def _index_clauses(docs_root: Path) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]:
    by_id, issues, _ = index_documents(iter_markdown_docs(docs_root))
    return by_id, issues


def collect_registry_mtimes(docs_root: Path) -> Dict[str, float]:
    """Absolute normalized path -> mtime (epoch seconds) for markdown files under docs_root."""
    mtimes: Dict[str, float] = {}
    for doc in iter_markdown_docs(docs_root):
        resolved = doc.resolve()
        mtimes[resolved.as_posix()] = resolved.stat().st_mtime
    return mtimes


def load_registry_index(
    docs_root: Path,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]], Dict[str, float]]:
    by_id, issues = _index_clauses(docs_root)
    mtimes = collect_registry_mtimes(docs_root)
    return by_id, issues, mtimes


def registry_memory_put(
    session_id: str,
    by_id: Dict[str, Dict[str, Any]],
    issues: List[Dict[str, str]],
    mtimes: Dict[str, float],
) -> None:
    _REGISTRY_MEMORY[session_id] = (by_id, issues, mtimes)


def registry_memory_get(
    session_id: str,
) -> Optional[Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]], Dict[str, float]]]:
    return _REGISTRY_MEMORY.get(session_id)


def registry_memory_clear(session_id: str) -> None:
    _REGISTRY_MEMORY.pop(session_id, None)


def _rel_from_root(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _source_surfaces(
    governance_doc: Path,
    docs_root: Path,
    instance_root: Path,
    additional: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    base = [
        {"surface": "governance_doc", "path": _rel_from_root(instance_root, governance_doc)},
        {"surface": "docs_root", "path": _rel_from_root(instance_root, docs_root)},
    ]
    if additional:
        base.extend(additional)
    return base


def _public_clause_payload(clause: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "id": clause.get("id"),
        "meta": bool(clause.get("meta", False)),
        "kind": clause.get("kind"),
        "status": clause.get("status"),
        "owner_doc": clause.get("owner_doc"),
        "paths": clause.get("paths", []),
        "content": clause.get("content", ""),
    }
    keywords = clause.get("keywords", [])
    if keywords:
        payload["keywords"] = list(keywords)
    registry_slots = clause.get("registry_slots", {})
    if registry_slots:
        payload["registry_slots"] = registry_slots
    return payload


def resolve_batch(
    ids: List[str],
    *,
    docs_root: Path,
    governance_doc: Path,
    preloaded: Optional[Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]] = None,
) -> Dict[str, Any]:
    """
    Resolve batch of clause IDs. Returns deterministic JSON envelope.
    """
    instance_root = governance_doc.parent.parent if governance_doc.parent else Path.cwd()
    if preloaded is not None:
        clauses, clause_parse_issues = preloaded[0], preloaded[1]
    else:
        clauses, clause_parse_issues = _index_clauses(docs_root)

    top_level_issues: List[Dict[str, str]] = []
    seen_issue_keys: set = set()
    for issue in clause_parse_issues:
        code = str(issue.get("code", "")).strip()
        message = str(issue.get("message", "")).strip()
        dedupe_key = (code, message)
        if code and message and dedupe_key not in seen_issue_keys:
            seen_issue_keys.add(dedupe_key)
            top_level_issues.append({"code": code, "message": message})

    results_by_id: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    seen: set = set()
    for raw_id in ids:
        canonical_id = raw_id.strip().lower()
        if canonical_id not in seen:
            seen.add(canonical_id)
            order.append(canonical_id)

    for canonical_id in order:
        if canonical_id in clauses:
            clause = clauses[canonical_id]
            if top_level_issues:
                results_by_id[canonical_id] = {
                    "status": "error",
                    "issues": top_level_issues,
                    "clause": _public_clause_payload(clause),
                }
            else:
                results_by_id[canonical_id] = {
                    "status": "ok",
                    "clause": _public_clause_payload(clause),
                }
        else:
            results_by_id[canonical_id] = {
                "status": "error",
                "issues": [{"code": UNKNOWN_CLAUSE_CODE, "message": f"Unknown clause id '{canonical_id}'."}],
                "clause": None,
            }

    blocking = any(result.get("status") == "error" for result in results_by_id.values())
    payload: Dict[str, Any] = {
        "status": "ok" if not blocking else "error",
        "blocking": blocking,
        "next_actions": DEFAULT_NEXT_ACTION,
        "context": {"requested_ids": ids},
        "source_authority": {"source_surfaces": _source_surfaces(governance_doc, docs_root, instance_root)},
        "results_by_id": results_by_id,
    }
    if top_level_issues:
        payload["issues"] = top_level_issues
    return payload
