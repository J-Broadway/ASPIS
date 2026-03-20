# ASPIS CLI v1 Contract Specification

**Status:** Locked (v1 contract finalized). Implementation: `tools/aspis.py`, `tools/clause.py`.

## Overview

Minimal deterministic clause router and resolver. Clause-only routing with strict `paths` semantics and stable JSON envelope for agent consumption.

## CLI Contract (v1)

### Supported Invocation Forms

All forms resolve to clause resolution:

| Form | Example |
|------|---------|
| `aspis.py clause <id...>` | `aspis.py clause aspis.policy.doc aspis.clause.schema` |
| `aspis.py clause:<id> [clause:<id>...]` | `aspis.py clause:aspis.policy.doc clause:aspis.clause.schema` |
| `aspis.py path:<id> [path:<id>...]` | `aspis.py path:aspis.policy.doc` |
| `aspis.py in:<id> [in:<id>...]` | `aspis.py in:aspis.policy.doc` |

### Route Registry

- `default_route`: `"clause"`
- `aliases`: `{"clause": "clause", "path": "clause", "in": "clause"}`
- `custom`: `{}` (reserved extension point for future non-clause routes)

### Normalized Request Model

Before resolution, tokens are normalized to:

```json
[
  {"route": "clause", "id": "aspis.policy.doc", "raw": "path:aspis.policy.doc"},
  {"route": "clause", "id": "aspis.clause.schema", "raw": "clause:aspis.clause.schema"}
]
```

### Fail-Closed Behavior

- Mixed invalid positional tokens (e.g., `clause:id1 unknown:id2`) → error, exit 2
- Unknown prefix (e.g., `foo:bar`) → error, exit 2
- Malformed token (e.g., `clause:` with no id) → error, exit 2

### Path Resolution

- Find `aspis.yaml` from cwd upward
- Read `paths.design_docs`, `paths.governance_doc` when present
- Fallback: `docs_root` = cwd/ASPIS or cwd/ASPIS Docs; `governance_doc` = first .md with "Governance" in name

## Response Contract (JSON Envelope)

### Top-Level Structure

```json
{
  "status": "ok" | "error",
  "blocking": true | false,
  "issues": [{"code": "...", "message": "..."}],
  "next_actions": ["..."],
  "context": {...},
  "source_authority": {"source_surfaces": [...]},
  "results_by_id": {
    "<canonical_id>": { ... }
  }
}
```

### Per-Result Entry

```json
{
  "status": "ok" | "error",
  "blocking": true | false,
  "issues": [{"code": "...", "message": "..."}],
  "next_actions": ["..."],
  "clause": {
    "id": "...",
    "meta": true | false,
    "kind": "...",
    "status": "...",
    "owner_doc": "...",
    "paths": ["...", "..."],
    "content": "..."
  }
}
```

`registry_slots` is included only when the clause body declares registry slots.

### Determinism

- Preserve request order in `results_by_id` keys
- Canonicalized IDs as map keys
- Consistent error shapes for: invalid syntax, unknown clause, malformed headers, `refs` usage (rejected)

## Clause Directive Schema (paths-only)

### Required Keys

- `kind`
- `status`
- `owner_doc`
- `paths` (list of clause/path identifiers)

### Optional Keys

- `id`
- `meta`
- `yield`

### Rejected

- `refs` in directive headers → FAIL (paths-only semantics)

## Lint Targeting Contract

- Invocation: `aspis.py lint <doc_domain>` (or `aspis.py lint --target <doc_domain>`)
- Target resolution: derive namespace from selector and resolve exactly one matching instance from `aspis.yaml` `instances[]`
- Scope: lint builds effective registry from protocol + selected instance only
- Registry ownership: write generated registry to `<instance-root>/.aspis/aspis.registry.yaml`
- Reference validation: second pass scans clause-section body references (outside fenced code blocks) and emits blocking `UNRESOLVED_DOMAIN_REFERENCE` / `DUPLICATE_DOMAIN_REFERENCE` findings

### Authority Selection Contract

- `aspis.entry` routing for mutation/registration work starts with authority orientation and target selection before schema traversal.
- Namespace ownership model:
  - `aspis.*` -> protocol authority surface
  - `<namespace>.*` -> instance authority surface
- Default mutation target policy:
  - project/instance registration defaults to selected instance namespace
  - protocol mutation requires explicit protocol intent (never inferred from project context)

### Deterministic Selection Behavior

- Selection precedence:
  1) explicit `doc_domain`/namespace selector
  2) inferred single-instance fallback when exactly one instance exists
  3) fail-closed ambiguity when multiple instances exist without explicit selector
- When multiple instances exist and no target is provided, lint returns blocking configuration failure and does not guess a target namespace.
- Lint payload includes `authority_context.surface_kind`, `authority_context.target_namespace`, and `authority_context.selection_source` for automation and remediation routing.
