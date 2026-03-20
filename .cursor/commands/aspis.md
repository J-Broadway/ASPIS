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
4. Recurse only through returned ASPIS `paths` / follow-up domains.
5. If you cannot proceed via ASPIS routes, explicitly state why and stop.
6. If you choose not to follow ASPIS routing, tell the user directly.

## Startup — always use a traced session

Every `/aspis` invocation MUST use session tracing so the visualizer can display the crawl live. Follow these steps in order:

### 1. Start a traced session

```
python3 tools/aspis.py session:start --name <label> --trace --config aspis.yaml
```

- `<label>`: a short descriptive name for this crawl (e.g. `explore`, `auth-review`, or derived from the user's request).
- Parse the JSON output and extract the `session_id` (32-char hex string).
- **Immediately tell the user** the session ID so they can paste it into the visualizer's session input field (top-right corner of the UI). Format:
  > **Traced session started.** Paste this ID into the visualizer to watch live:
  > `<session_id>`

### 2. Use `session:cmd` for every command (not bare `path:`)

Instead of `python3 tools/aspis.py path:aspis.entry`, run:

```
python3 tools/aspis.py session:cmd --session <session_id> path:aspis.entry --config aspis.yaml
```

This writes trace events to `trace.jsonl`, which the visualizer polls.

All subsequent clause resolutions must also use `session:cmd --session <session_id>`:

```
python3 tools/aspis.py session:cmd --session <session_id> path:<clause.id> --config aspis.yaml
```

### 3. End the session when done

When you have finished crawling (or the user's request is satisfied), end the session:

```
python3 tools/aspis.py session:end --session <session_id> --format summary --config aspis.yaml
```

## Reference — session subcommands

Top-level subcommands, same workspace flags as clause mode (`--config`, `--design-docs-dir`, `--governance-doc`):

- **Start:** `python3 tools/aspis.py session:start --name <label> [--trace] [--trace-full]`
  - Prints JSON with `session_id`, absolute `session_dir`, `trace_enabled`.
- **Command:** `python3 tools/aspis.py session:cmd --session <id> <clause tokens...>`
  - Same stdout as batch clause mode; optional `--include-full-response` for trace payload.
- **End:** `python3 tools/aspis.py session:end --session <id> [--format summary|json|graphviz] [--output <path.dot>]`
  - JSON on stdout; graphviz writes `paths_by_id` edges to `--output` (requires `--trace` on start).

Session state lives under `<docs_root>/.aspis/sessions/<session_id>/` (see `aspis.tools.session.*` in governance).