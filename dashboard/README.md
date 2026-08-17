# Dashboard

The dashboard is a static, read-only publication built for GitHub Pages. It consumes processed versioned data and links every displayed result to source run IDs and manifests.

The current MVP is a dependency-free static page in [`index.html`](index.html). It reads [`../adapters/preflight-v1.1.json`](../adapters/preflight-v1.1.json), [`../adapters/condition-readiness-v1.1.json`](../adapters/condition-readiness-v1.1.json), and the generated [`../analysis/processed-results-v1.1.json`](../analysis/processed-results-v1.1.json), falls back to bounded blocked/no-results states when data is unavailable, and adds no analytics or user tracking.

Open locally with any static server from the repository root, for example:

```bash
python3 -m http.server 8000
```

Then visit `http://localhost:8000/dashboard/`. The page is intentionally honest before pilot collection: it shows readiness and the condition matrix, not invented results.
