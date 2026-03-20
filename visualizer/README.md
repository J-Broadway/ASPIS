# ASPIS Visualizer

Vite + TypeScript + Three.js browser client for the full ASPIS registry clause graph and optional session trace animation.

## Prerequisites

- Node 18+
- `python3 tools/serve_aspis_visual.py` running (default `http://127.0.0.1:8765`)

## Configuration

| Env | Default | Purpose |
|-----|---------|---------|
| `VITE_ASPIS_API_BASE` | `http://127.0.0.1:8765` | HTTP bridge base URL |

Workspace flags (`config`, `design_docs_dir`, `governance_doc`) are read from the page URL and forwarded to every API request, matching CLI semantics.

## Scripts

```bash
npm install
npm run dev    # dev server
npm run build  # production bundle to dist/
```

## URL parameters

- `?session=<32-hex>` — repeat to track multiple traced sessions
- `?config=...&governance_doc=...` — workspace resolution for the bridge

Graph content is loaded with `GET /api/graph?include_content=true`.
