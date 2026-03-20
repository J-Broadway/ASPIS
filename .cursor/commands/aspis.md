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