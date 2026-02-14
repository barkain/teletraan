# Publishing Reports

Teletraan can automatically publish analysis reports as self-contained HTML pages.
Three publishing methods are available, controlled by the `PUBLISH_METHOD` setting
in your `backend/.env` file.

## Overview

- **Persistent Reports** -- Completed analysis tasks are stored as reports with full insight details, phases completed, and market regime context
- **Self-Contained HTML** -- Reports render as dark-themed, fully portable HTML pages with all CSS inlined and a financial disclaimer (not financial advice, no liability)
- **Flexible Publishing** -- Reports can be published to GitHub Pages, a local directory (for nginx/S3/Netlify), or kept local-only

## Publishing Methods

### 1. GitHub Pages (default)

Pushes reports to a `gh-pages` branch on your GitHub repository. GitHub Pages
serves them as a static site.

```env
PUBLISH_METHOD=github_pages
GITHUB_PAGES_ENABLED=true
GITHUB_PAGES_REPO=your-username/your-repo
GITHUB_PAGES_BASE_URL=https://your-username.github.io/your-repo
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_PAGES_ENABLED` | Yes | `false` | Must be `true` to enable publishing |
| `GITHUB_PAGES_REPO` | No | *(auto-detected)* | `org/repo` override. Auto-detected from git remote if omitted |
| `GITHUB_PAGES_BRANCH` | No | `gh-pages` | Branch name |
| `GITHUB_PAGES_BASE_URL` | No | *(derived from repo)* | Public URL prefix. Derived from repo name if omitted |

**How it works:**
1. Clones (or creates) the `gh-pages` branch into a temp directory
2. Writes the report HTML to `reports/{date}-{HHMM}-{regime}.html`
3. Writes a JSON metadata sidecar to `reports/meta/`
4. Regenerates `index.html` with all report cards
5. Commits and pushes to the remote

**Requirements:** `git` must be available on `$PATH`. The `gh` CLI is used
(best-effort) to auto-enable GitHub Pages on first publish.

### 2. Static Directory

Copies report files to a local directory. This is useful when you serve
that directory via nginx, sync it to S3, deploy it through Netlify or
Cloudflare Pages, or any other static hosting setup.

```env
PUBLISH_METHOD=static_dir
PUBLISH_DIR=/var/www/teletraan-reports
PUBLISH_URL=https://reports.example.com
```

| Variable | Required | Description |
|---|---|---|
| `PUBLISH_DIR` | Yes | Absolute path to the local directory where reports are written |
| `PUBLISH_URL` | No | Public base URL for constructing published URLs. If omitted, the local file path is returned instead |

**How it works:**
1. Creates `reports/` and `reports/meta/` inside `PUBLISH_DIR` if they don't exist
2. Writes the report HTML and JSON metadata sidecar
3. Regenerates `index.html` at the root of `PUBLISH_DIR`
4. Returns `{PUBLISH_URL}/reports/{filename}` as the published URL

**Example: nginx**

```nginx
server {
    listen 80;
    server_name reports.example.com;
    root /var/www/teletraan-reports;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

**Example: S3 sync (cron)**

```bash
# In .env:
# PUBLISH_METHOD=static_dir
# PUBLISH_DIR=/tmp/teletraan-reports
# PUBLISH_URL=https://my-bucket.s3.amazonaws.com

# Sync to S3 every 5 minutes
*/5 * * * * aws s3 sync /tmp/teletraan-reports s3://my-bucket/ --delete
```

### 3. None (disabled)

Disables publishing entirely. Reports are still generated and accessible
via the API (`GET /api/v1/reports/{task_id}/html`), but they are not
published to any external destination.

```env
PUBLISH_METHOD=none
```

## Common Settings

The `PUBLISH_URL` variable works across all methods. When set, it overrides
the auto-derived base URL for constructing published report links. This is
useful when your reports are behind a CDN or reverse proxy with a different
public URL than the hosting origin.

```env
# Works with github_pages to override the default github.io URL:
PUBLISH_METHOD=github_pages
PUBLISH_URL=https://reports.mycompany.com
GITHUB_PAGES_ENABLED=true

# Works with static_dir:
PUBLISH_METHOD=static_dir
PUBLISH_DIR=/opt/reports
PUBLISH_URL=https://cdn.mycompany.com/reports
```

## Directory Structure

Regardless of publishing method, the report directory structure is:

```
{root}/
  index.html              # Auto-generated index page with report cards
  .nojekyll               # Prevents Jekyll processing (GitHub Pages)
  reports/
    2026-02-13-0544-transitional.html
    2026-02-12-1830-bullish.html
    ...
    meta/
      2026-02-13-0544-transitional.json   # Metadata sidecar
      2026-02-12-1830-bullish.json
      ...
```

## Fork Safety

Publishing is **disabled by default**. Forks will not accidentally publish to
the original repo. You must explicitly set your own configuration before
publishing works.

## API Endpoints

- `GET /api/v1/reports` -- List completed analysis reports (paginated)
- `GET /api/v1/reports/{task_id}` -- Get full report with insights
- `GET /api/v1/reports/{task_id}/html` -- Get self-contained HTML report
- `POST /api/v1/reports/{task_id}/publish` -- Publish report using configured method

Auto-publishing also runs automatically after autonomous deep analysis completes
(if publishing is enabled). Manual publishing is available via the REST API endpoint.

## Backward Compatibility

The default configuration (`PUBLISH_METHOD=github_pages`) preserves the original
behaviour. Existing `.env` files that only set `GITHUB_PAGES_ENABLED`,
`GITHUB_PAGES_REPO`, and `GITHUB_PAGES_BASE_URL` will continue to work without
any changes.

## Disclaimer

All published reports include a financial disclaimer stating that the content is not financial advice and carries no liability.
