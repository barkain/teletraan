# Publishing Reports

Teletraan can publish analysis reports to GitHub Pages as self-contained HTML pages.

## Overview

- **Persistent Reports** -- Completed analysis tasks are stored as reports with full insight details, phases completed, and market regime context
- **Self-Contained HTML** -- Reports render as dark-themed, fully portable HTML pages with all CSS inlined and a financial disclaimer (not financial advice, no liability)
- **GitHub Pages Publishing** -- Reports publish to the `gh-pages` branch; auto-publish runs after autonomous deep analysis (if enabled), manual publish available via `POST /reports/{task_id}/publish`

## Configuration

Publishing is **disabled by default** for fork safety. To enable, set the following in `backend/.env`:

```env
GITHUB_PAGES_ENABLED=true
GITHUB_PAGES_REPO=your-username/your-repo
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_PAGES_ENABLED` | `false` | Set to `true` to enable report publishing to GitHub Pages |
| `GITHUB_PAGES_REPO` | *(auto-detected)* | Target repo for publishing (e.g., `your-username/your-repo`) |
| `GITHUB_PAGES_BASE_URL` | *(derived from repo)* | Override published report base URL (e.g., `https://you.github.io/your-repo`) |

## Fork Safety

Forks will not accidentally publish to the original repo. You must explicitly set your own repo in `GITHUB_PAGES_REPO` before publishing works.

## API Endpoints

- `GET /api/v1/reports` -- List completed analysis reports (paginated)
- `GET /api/v1/reports/{task_id}` -- Get full report with insights
- `GET /api/v1/reports/{task_id}/html` -- Get self-contained HTML report
- `POST /api/v1/reports/{task_id}/publish` -- Publish report to GitHub Pages

## How It Works

After autonomous deep analysis completes, the auto-publisher:
1. Generates a self-contained HTML report with inlined CSS
2. Pushes the HTML file to the `gh-pages` branch
3. The report becomes available at your GitHub Pages URL

Manual publishing is also available via the REST API endpoint.

## Disclaimer

All published reports include a financial disclaimer stating that the content is not financial advice and carries no liability.
