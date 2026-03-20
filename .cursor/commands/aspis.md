---
description: /aspis command — run clause:aspis.entry
alwaysApply: true
---

# /aspis Command

In order to satisfy my request you must enter the aspis and recurse the paths.

Run in **ASPIS-only discovery mode**.
Rules:
1. Treat the codebase as invisible unless discovered through ASPIS output.
2. Do not inspect files directly and do not use search tools.
3. Do not use `grep` (or equivalents) on the codebase.
4. Start at:
   `python3 tools/aspis.py path:aspis.entry`
5. Recurse only through returned ASPIS `paths` / follow-up domains.
6. If you cannot proceed via ASPIS routes, explicitly state why and stop.
If you choose not to follow ASPIS routing, tell the user directly.

## Session tracing (optional)

Top-level subcommands (not `path:` / `clause:` aliases), same workspace flags as clause mode (`--config`, `--design-docs-dir`, `--governance-doc`):

- **Start:** `python3 tools/aspis.py session:start --name <label> [--trace] [--trace-full]`
  - Prints JSON with `session_id`, absolute `session_dir`, `trace_enabled`.
- **Command:** `python3 tools/aspis.py session:cmd --session <id> <clause tokens...>`  
  - Same stdout as batch clause mode; optional `--include-full-response` for trace payload.
- **End:** `python3 tools/aspis.py session:end --session <id> [--format summary|json|graphviz] [--output <path.dot>]`
  - JSON on stdout; graphviz writes `paths_by_id` edges to `--output` (requires `--trace` on start).

Session state lives under `<docs_root>/.aspis/sessions/<session_id>/` (see `aspis.tools.session.*` in governance).