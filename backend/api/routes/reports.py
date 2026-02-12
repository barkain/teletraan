"""Reports API routes — read-only views over AnalysisTask + DeepInsight data."""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from models.analysis_task import AnalysisTask, AnalysisTaskStatus
from models.deep_insight import DeepInsight
from schemas.report import (
    ReportDetail,
    ReportInsight,
    ReportListResponse,
    ReportSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Resolve the repository root directory (two levels up from this file)
# ---------------------------------------------------------------------------
_REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


# ---------------------------------------------------------------------------
# Report filename helpers
# ---------------------------------------------------------------------------


def _sanitize_regime(regime: str | None) -> str:
    """Sanitize a market regime string for use in filenames.

    Converts to lowercase, replaces spaces/underscores with hyphens,
    and removes any non-alphanumeric/hyphen characters.
    """
    if not regime:
        return "unknown"
    result = regime.lower().strip()
    result = re.sub(r"[\s_]+", "-", result)
    result = re.sub(r"[^a-z0-9-]", "", result)
    result = re.sub(r"-+", "-", result).strip("-")
    return result or "unknown"


def _report_filename(task: AnalysisTask) -> str:
    """Generate a human-readable report filename from task metadata.

    Format: ``{date}-{HHMM}-{regime}.html``
    (e.g. ``2026-02-10-0544-transitional.html``)
    """
    if task.created_at:
        date_str = task.created_at.strftime("%Y-%m-%d")
        time_str = task.created_at.strftime("%H%M")
    elif task.started_at:
        date_str = task.started_at.strftime("%Y-%m-%d")
        time_str = task.started_at.strftime("%H%M")
    else:
        date_str = "undated"
        time_str = "0000"

    regime = _sanitize_regime(task.market_regime)
    return f"{date_str}-{time_str}-{regime}.html"


# ---------------------------------------------------------------------------
# Markdown-to-HTML converter
# ---------------------------------------------------------------------------


def _markdown_to_html(text: str) -> str:
    """Convert markdown text to styled HTML.

    Handles:
    - ``## Heading`` -> ``<h3>`` with styled class
    - ``**bold**`` -> ``<strong>``
    - ``- item`` or ``* item`` -> ``<ul><li>`` (consecutive lines)
    - ``1. item`` -> ``<ol><li>`` (consecutive lines)
    - Blank lines -> paragraph breaks
    - ``Key: Value`` patterns -> styled key-value display
    - Numbers with +/- and % -> green/red highlighted spans
    """
    if not text:
        return ""

    # Escape HTML first
    escaped = _esc(text)

    # Bold
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)

    # Highlight percentages: +15.75% in green, -2.30% in red
    escaped = re.sub(
        r"(\+\d+(?:\.\d+)?%)",
        r'<span class="num-positive">\1</span>',
        escaped,
    )
    escaped = re.sub(
        r"(-\d+(?:\.\d+)?%)",
        r'<span class="num-negative">\1</span>',
        escaped,
    )

    lines = escaped.split("\n")
    result_parts: list[str] = []
    in_ul = False
    in_ol = False

    def _close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            result_parts.append("</ul>")
            in_ul = False
        if in_ol:
            result_parts.append("</ol>")
            in_ol = False

    for line in lines:
        stripped = line.strip()

        # Blank line -> close lists, add spacing
        if not stripped:
            _close_lists()
            continue

        # Headings: ## Heading or ### Heading
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading_match:
            _close_lists()
            result_parts.append(
                f'<h3 class="md-heading">{heading_match.group(2)}</h3>'
            )
            continue

        # Unordered list: - item or * item
        ul_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if ul_match:
            if in_ol:
                result_parts.append("</ol>")
                in_ol = False
            if not in_ul:
                result_parts.append('<ul class="md-list">')
                in_ul = True
            result_parts.append(f"<li>{ul_match.group(1)}</li>")
            continue

        # Ordered list: 1. item
        ol_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if ol_match:
            if in_ul:
                result_parts.append("</ul>")
                in_ul = False
            if not in_ol:
                result_parts.append('<ol class="md-list">')
                in_ol = True
            result_parts.append(f"<li>{ol_match.group(1)}</li>")
            continue

        # Close any open lists for non-list lines
        _close_lists()

        # Key: Value pattern (e.g., "Market Regime: Transitional")
        kv_match = re.match(r"^([A-Z][A-Za-z\s&/]+?):\s+(.+)$", stripped)
        if kv_match:
            result_parts.append(
                f'<div class="md-kv">'
                f'<span class="md-kv-key">{kv_match.group(1)}:</span> '
                f'<span class="md-kv-value">{kv_match.group(2)}</span>'
                f'</div>'
            )
            continue

        # Regular paragraph
        result_parts.append(f'<p class="md-para">{stripped}</p>')

    _close_lists()
    return "\n".join(result_parts)


# ---------------------------------------------------------------------------
# GitHub Pages publishing helpers
# ---------------------------------------------------------------------------


def _resolve_executable(name: str) -> str:
    """Resolve an executable name to its full absolute path via ``shutil.which``.

    Raises ``RuntimeError`` if the executable cannot be found.
    """
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(
            f"'{name}' executable is not available on this system. "
            f"Install {name} to enable GitHub Pages publishing."
        )
    return path


def _git_run(
    args: list[str],
    *,
    git_path: str,
    cwd: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a git command using the fully-resolved executable path.

    All arguments are trusted internal constants (branch names, flags, etc.).
    """
    cmd = [git_path, *args]
    return subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        check=check,
    )


def _parse_github_org_repo(remote_url: str) -> tuple[str, str]:
    """Extract (org, repo) from a GitHub remote URL.

    Handles both HTTPS and SSH styles:
      - https://github.com/barkain/teletraan.git
      - git@github.com:barkain/teletraan.git
    """
    cleaned = remote_url.strip().replace(".git", "")
    if "github.com" in cleaned:
        # Split on github.com then grab the trailing path
        tail = cleaned.split("github.com")[-1].lstrip(":/")
        parts = tail.split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1]
    # Fallback
    return "barkain", "teletraan"


def _generate_index_html(report_files: list[str], org: str, repo: str) -> str:
    """Generate a dark-themed index page with enriched report cards.

    Parses filenames in ``{date}-{HHMM}-{regime}.html`` format to extract
    metadata and renders a responsive card grid with date+time, regime badge,
    and a "Latest" indicator on the most recent report.
    """
    cards = ""
    for idx, fname in enumerate(report_files):
        is_latest = idx == 0
        stem = fname.replace(".html", "")
        # Parse date-time-regime format: YYYY-MM-DD-HHMM-regime
        parts = stem.split("-")
        date_str = ""
        time_str = ""
        regime_raw = ""

        if len(parts) >= 5:
            # New format: YYYY-MM-DD-HHMM-regime...
            date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
            time_str = parts[3]
            regime_raw = "-".join(parts[4:])
        elif len(parts) >= 4:
            # Old format: YYYY-MM-DD-regime (no time)
            date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
            # Check if 4th part is a 4-digit time
            if re.match(r"^\d{4}$", parts[3]):
                time_str = parts[3]
                regime_raw = "-".join(parts[4:]) if len(parts) > 4 else ""
            else:
                regime_raw = "-".join(parts[3:])
        elif len(parts) == 3:
            date_str = stem
        else:
            date_str = stem

        # Format date + time nicely
        display_date = date_str
        display_time = ""
        try:
            from datetime import datetime
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            display_date = dt.strftime("%B %d, %Y")
        except (ValueError, ImportError):
            pass

        if time_str and len(time_str) == 4:
            hh = time_str[:2]
            mm = time_str[2:]
            display_time = f"at {hh}:{mm} UTC"

        # Format regime
        regime_display = regime_raw.replace("-", " ").title() if regime_raw else "Analysis"

        # Regime badge color
        regime_color = "#6366F1"
        rl = regime_raw.lower()
        if "bull" in rl or "expansion" in rl or "risk-on" in rl:
            regime_color = "#10B981"
        elif "bear" in rl or "contraction" in rl or "risk-off" in rl:
            regime_color = "#EF4444"
        elif "neutral" in rl or "mixed" in rl or "transitional" in rl:
            regime_color = "#F59E0B"

        latest_badge = ""
        if is_latest:
            latest_badge = '<span class="latest-badge">Latest</span>'

        cards += f"""
        <a href="reports/{fname}" class="report-card" data-date="{_esc(date_str)}">
          <div class="card-top-row">
            <div class="card-date">{_esc(display_date)}</div>
            {latest_badge}
          </div>
          <div class="card-time">{_esc(display_time)}</div>
          <span class="regime-badge" style="background:{regime_color}18;color:{regime_color};border-color:{regime_color}33;">
            {_esc(regime_display)}
          </span>
          <div class="card-filename">{_esc(stem)}</div>
        </a>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Teletraan Intelligence</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    background: #0B0F19;
    background-image: radial-gradient(ellipse at 50% 0%, rgba(99,102,241,0.08) 0%, transparent 60%);
    color: #E2E8F0;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.6;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }}
  .container {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 48px 24px;
  }}
  .header {{
    text-align: center;
    margin-bottom: 48px;
  }}
  .header h1 {{
    margin: 0 0 8px 0;
    font-size: 36px;
    font-weight: 800;
    background: linear-gradient(135deg, #6366F1, #8B5CF6, #A78BFA);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.5px;
  }}
  .header p {{
    margin: 0;
    color: #64748B;
    font-size: 15px;
    font-weight: 500;
  }}
  .card-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 20px;
  }}
  .report-card {{
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 24px;
    background: rgba(255,255,255,0.03);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    text-decoration: none;
    color: inherit;
    transition: all 0.25s ease;
    position: relative;
  }}
  .report-card:hover {{
    background: rgba(255,255,255,0.06);
    border-color: rgba(99,102,241,0.3);
    transform: translateY(-3px);
    box-shadow: 0 12px 40px rgba(99,102,241,0.12);
  }}
  .card-top-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }}
  .card-date {{
    font-size: 20px;
    font-weight: 700;
    color: #F1F5F9;
  }}
  .card-time {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    color: #64748B;
    font-weight: 500;
    margin-top: -2px;
  }}
  .latest-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background: rgba(99,102,241,0.15);
    color: #A5B4FC;
    border: 1px solid rgba(99,102,241,0.3);
    box-shadow: 0 0 12px rgba(99,102,241,0.2);
  }}
  .regime-badge {{
    display: inline-block;
    width: fit-content;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid;
  }}
  .card-filename {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #475569;
    margin-top: 4px;
  }}
  .empty-state {{
    text-align: center;
    padding: 80px 24px;
    color: #475569;
    font-size: 16px;
  }}
  .footer {{
    margin-top: 64px;
    padding-top: 24px;
    border-top: 1px solid rgba(255,255,255,0.06);
    text-align: center;
  }}
  .footer p {{
    margin: 0;
    color: #334155;
    font-size: 13px;
  }}
  .footer strong {{
    color: #475569;
  }}
  @keyframes fadeInUp {{
    from {{ opacity: 0; transform: translateY(16px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}
  .report-card {{
    animation: fadeInUp 0.4s ease both;
  }}
  .report-card:nth-child(2) {{ animation-delay: 0.05s; }}
  .report-card:nth-child(3) {{ animation-delay: 0.1s; }}
  .report-card:nth-child(4) {{ animation-delay: 0.15s; }}
  .report-card:nth-child(5) {{ animation-delay: 0.2s; }}
  .report-card:nth-child(6) {{ animation-delay: 0.25s; }}
  /* Date filter bar */
  .filter-bar {{
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 24px;
    padding: 16px 20px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
  }}
  .filter-bar label {{
    font-size: 13px;
    font-weight: 600;
    color: #94A3B8;
    white-space: nowrap;
  }}
  .filter-bar input[type="date"] {{
    color-scheme: dark;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 6px 10px;
    color: #E2E8F0;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    outline: none;
    transition: border-color 0.2s ease;
  }}
  .filter-bar input[type="date"]:focus {{
    border-color: rgba(99,102,241,0.5);
  }}
  .filter-bar input[type="date"]::-webkit-calendar-picker-indicator {{
    filter: invert(0.7);
    cursor: pointer;
  }}
  .filter-clear-btn {{
    background: rgba(99,102,241,0.12);
    color: #A5B4FC;
    border: 1px solid rgba(99,102,241,0.25);
    border-radius: 8px;
    padding: 6px 14px;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    white-space: nowrap;
  }}
  .filter-clear-btn:hover {{
    background: rgba(99,102,241,0.2);
    border-color: rgba(99,102,241,0.4);
  }}
  .filter-count {{
    margin-left: auto;
    font-size: 13px;
    color: #64748B;
    font-weight: 500;
    white-space: nowrap;
  }}
  .report-card.hidden-by-filter {{
    display: none;
  }}
  @media (max-width: 640px) {{
    .container {{ padding: 24px 16px; }}
    .header h1 {{ font-size: 28px; }}
    .card-grid {{ grid-template-columns: 1fr; }}
    .filter-bar {{
      flex-direction: column;
      align-items: stretch;
      gap: 10px;
    }}
    .filter-bar .filter-row {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .filter-bar input[type="date"] {{
      flex: 1;
    }}
    .filter-count {{
      margin-left: 0;
      text-align: center;
    }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Teletraan Intelligence</h1>
    <p>Published market analysis reports</p>
  </div>

  <div class="filter-bar" id="filterBar">
    <div class="filter-row">
      <label for="dateFrom">From</label>
      <input type="date" id="dateFrom" />
    </div>
    <div class="filter-row">
      <label for="dateTo">To</label>
      <input type="date" id="dateTo" />
    </div>
    <button class="filter-clear-btn" id="filterClear" type="button">Clear</button>
    <span class="filter-count" id="filterCount"></span>
  </div>

  <div class="card-grid" id="cardGrid">
    {cards if cards else '<div class="empty-state">No reports published yet.</div>'}
  </div>

  <div class="footer">
    <p>Generated by <strong>Teletraan</strong></p>
  </div>
</div>
<script>
(function() {{
  var fromEl = document.getElementById('dateFrom');
  var toEl = document.getElementById('dateTo');
  var clearBtn = document.getElementById('filterClear');
  var countEl = document.getElementById('filterCount');
  var cards = document.querySelectorAll('.report-card[data-date]');
  var total = cards.length;

  function updateCount(visible) {{
    if (visible === total) {{
      countEl.textContent = total + ' report' + (total !== 1 ? 's' : '');
    }} else {{
      countEl.textContent = 'Showing ' + visible + ' of ' + total + ' reports';
    }}
  }}

  function applyFilter() {{
    var fromVal = fromEl.value;
    var toVal = toEl.value;
    var visible = 0;
    for (var i = 0; i < cards.length; i++) {{
      var d = cards[i].getAttribute('data-date');
      var show = true;
      if (fromVal && d < fromVal) show = false;
      if (toVal && d > toVal) show = false;
      if (show) {{
        cards[i].classList.remove('hidden-by-filter');
        visible++;
      }} else {{
        cards[i].classList.add('hidden-by-filter');
      }}
    }}
    updateCount(visible);
  }}

  clearBtn.addEventListener('click', function() {{
    fromEl.value = '';
    toEl.value = '';
    applyFilter();
  }});

  fromEl.addEventListener('change', applyFilter);
  toEl.addEventListener('change', applyFilter);

  updateCount(total);
}})();
</script>
</body>
</html>"""


def _do_publish(task: AnalysisTask, html_content: str, repo_dir: str) -> str:
    """Synchronous helper that publishes an HTML report to the gh-pages branch.

    Uses human-readable filename ``{date}-{HHMM}-{regime}.html`` derived from
    the AnalysisTask metadata.  Runs inside ``run_in_executor`` so it does not
    block the event loop.

    Returns the published GitHub Pages URL on success.
    Raises ``RuntimeError`` on failure.
    """
    filename = _report_filename(task)

    # Resolve full path to git executable (raises RuntimeError if missing)
    git_path = _resolve_executable("git")

    # Determine remote URL and derive org/repo
    remote_result = _git_run(
        ["remote", "get-url", "origin"],
        git_path=git_path,
        cwd=repo_dir,
    )
    remote_url = remote_result.stdout.strip() if remote_result.returncode == 0 else ""
    org, repo = _parse_github_org_repo(remote_url) if remote_url else ("barkain", "teletraan")

    tmpdir = tempfile.mkdtemp(prefix="teletraan_ghpages_")
    try:
        # Check if gh-pages branch exists on remote
        ls_result = _git_run(
            ["ls-remote", "--heads", "origin", "gh-pages"],
            git_path=git_path,
            cwd=repo_dir,
        )
        gh_pages_exists = "gh-pages" in ls_result.stdout

        work_dir = os.path.join(tmpdir, "ghpages")

        if gh_pages_exists:
            # Clone only the gh-pages branch (shallow)
            clone_result = _git_run(
                [
                    "clone",
                    "--branch", "gh-pages",
                    "--single-branch",
                    "--depth", "1",
                    remote_url,
                    work_dir,
                ],
                git_path=git_path,
            )
            if clone_result.returncode != 0:
                raise RuntimeError(f"Failed to clone gh-pages: {clone_result.stderr}")
        else:
            # Create a new orphan branch
            os.makedirs(work_dir)
            _git_run(["init"], git_path=git_path, cwd=work_dir, check=True)
            _git_run(
                ["checkout", "--orphan", "gh-pages"],
                git_path=git_path,
                cwd=work_dir,
                check=True,
            )
            _git_run(
                ["remote", "add", "origin", remote_url],
                git_path=git_path,
                cwd=work_dir,
                check=True,
            )

        # Configure git identity for the commit
        _git_run(
            ["config", "user.email", "teletraan@automated.report"],
            git_path=git_path,
            cwd=work_dir,
        )
        _git_run(
            ["config", "user.name", "Teletraan Report Publisher"],
            git_path=git_path,
            cwd=work_dir,
        )

        # Write the report HTML
        reports_dir = os.path.join(work_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)

        report_path = os.path.join(reports_dir, filename)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(html_content)

        # Build / update the index page that lists all reports
        report_files = sorted(
            [f for f in os.listdir(reports_dir) if f.endswith(".html")],
            reverse=True,
        )
        index_html = _generate_index_html(report_files, org, repo)
        with open(os.path.join(work_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(index_html)

        # Ensure GitHub Pages serves raw HTML (disable Jekyll processing)
        nojekyll_path = os.path.join(work_dir, ".nojekyll")
        if not os.path.exists(nojekyll_path):
            with open(nojekyll_path, "w") as fh:
                pass

        # Stage, commit, and push
        _git_run(["add", "."], git_path=git_path, cwd=work_dir, check=True)

        slug = filename.replace(".html", "")
        commit_result = _git_run(
            ["commit", "-m", f"Publish report {slug}"],
            git_path=git_path,
            cwd=work_dir,
        )
        if commit_result.returncode != 0:
            raise RuntimeError(f"Git commit failed: {commit_result.stderr}")

        push_result = _git_run(
            ["push", "origin", "gh-pages"],
            git_path=git_path,
            cwd=work_dir,
        )
        if push_result.returncode != 0:
            # Retry with force push (e.g. history diverged due to manual edits)
            push_result = _git_run(
                ["push", "--force", "origin", "gh-pages"],
                git_path=git_path,
                cwd=work_dir,
            )
        if push_result.returncode != 0:
            raise RuntimeError(f"Git push failed: {push_result.stderr}")

        # Try to enable GitHub Pages via gh CLI (best-effort, non-fatal)
        gh_path = shutil.which("gh")
        if gh_path is not None:
            try:
                subprocess.run(  # noqa: S603
                    [
                        gh_path, "api",
                        f"repos/{org}/{repo}/pages",
                        "-X", "POST",
                        "-f", 'source={"branch":"gh-pages","path":"/"}',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except subprocess.TimeoutExpired:
                pass

        return f"https://{org}.github.io/{repo}/reports/{filename}"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _publish_to_ghpages(task: AnalysisTask, html_content: str, repo_dir: str) -> str:
    """Publish HTML report to gh-pages branch (async wrapper)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_publish, task, html_content, repo_dir)


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("", response_model=ReportListResponse)
async def list_reports(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
):
    """List completed analysis reports.

    Returns completed AnalysisTask records as report summaries,
    ordered by started_at descending.
    """
    base_query = select(AnalysisTask).where(
        AnalysisTask.status == AnalysisTaskStatus.COMPLETED.value
    )

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query) or 0

    # Fetch paginated results
    query = (
        base_query
        .order_by(desc(AnalysisTask.started_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    tasks = result.scalars().all()

    items = []
    for task in tasks:
        insight_count = len(task.result_insight_ids) if task.result_insight_ids else 0
        items.append(
            ReportSummary(
                id=task.id,
                started_at=task.started_at,
                completed_at=task.completed_at,
                elapsed_seconds=task.elapsed_seconds,
                market_regime=task.market_regime,
                top_sectors=task.top_sectors or [],
                discovery_summary=task.discovery_summary,
                insights_count=insight_count,
                published_url=task.published_url,
            )
        )

    return ReportListResponse(items=items, total=total)


@router.get("/{task_id}", response_model=ReportDetail)
async def get_report(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a full report for a completed analysis task.

    Loads the AnalysisTask and all associated DeepInsight records.
    """
    result = await db.execute(
        select(AnalysisTask).where(AnalysisTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Report not found")

    # Load associated insights
    insights: list[ReportInsight] = []
    if task.result_insight_ids:
        insight_result = await db.execute(
            select(DeepInsight).where(DeepInsight.id.in_(task.result_insight_ids))
        )
        db_insights = insight_result.scalars().all()
        # Maintain original order from result_insight_ids
        insight_map = {i.id: i for i in db_insights}
        for iid in task.result_insight_ids:
            ins = insight_map.get(iid)
            if ins:
                insights.append(
                    ReportInsight(
                        id=ins.id,
                        insight_type=ins.insight_type,
                        action=ins.action,
                        title=ins.title,
                        thesis=ins.thesis,
                        primary_symbol=ins.primary_symbol,
                        related_symbols=ins.related_symbols or [],
                        confidence=ins.confidence,
                        time_horizon=ins.time_horizon,
                        risk_factors=ins.risk_factors or [],
                        entry_zone=ins.entry_zone,
                        target_price=ins.target_price,
                        stop_loss=ins.stop_loss,
                        invalidation_trigger=ins.invalidation_trigger,
                        supporting_evidence=(
                            ins.supporting_evidence[0]
                            if ins.supporting_evidence and len(ins.supporting_evidence) == 1
                            else {"items": ins.supporting_evidence}
                            if ins.supporting_evidence
                            else None
                        ),
                        created_at=ins.created_at,
                    )
                )

    insight_count = len(task.result_insight_ids) if task.result_insight_ids else 0

    return ReportDetail(
        id=task.id,
        started_at=task.started_at,
        completed_at=task.completed_at,
        elapsed_seconds=task.elapsed_seconds,
        market_regime=task.market_regime,
        top_sectors=task.top_sectors or [],
        discovery_summary=task.discovery_summary,
        insights_count=insight_count,
        published_url=task.published_url,
        insights=insights,
        phases_completed=task.phases_completed or [],
    )


@router.get("/{task_id}/html")
async def get_report_html(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Generate a self-contained HTML report for a completed analysis.

    Returns a professional dark-theme HTML page with all CSS inlined.
    No external dependencies -- fully portable and printable.
    """
    result = await db.execute(
        select(AnalysisTask).where(AnalysisTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Report not found")

    # Load insights
    insights = []
    if task.result_insight_ids:
        insight_result = await db.execute(
            select(DeepInsight).where(DeepInsight.id.in_(task.result_insight_ids))
        )
        db_insights = insight_result.scalars().all()
        insight_map = {i.id: i for i in db_insights}
        for iid in task.result_insight_ids:
            ins = insight_map.get(iid)
            if ins:
                insights.append(ins)

    html = _build_report_html(task, insights)
    return Response(content=html, media_type="text/html")


@router.post("/{task_id}/publish")
async def publish_report(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Publish a completed analysis report to GitHub Pages.

    Generates a self-contained HTML report and pushes it to the
    ``gh-pages`` branch under ``reports/{date}-{HHMM}-{regime}.html``.
    An index page listing all published reports is maintained automatically.

    Returns the public URL of the published report.
    """
    # 1. Load the task -------------------------------------------------------
    result = await db.execute(
        select(AnalysisTask).where(AnalysisTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Report not found")

    if task.status != AnalysisTaskStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot publish a report with status '{task.status}'. "
            "Only completed reports can be published.",
        )

    # 2. Generate the HTML report (same logic as GET /{task_id}/html) --------
    insights: list[DeepInsight] = []
    if task.result_insight_ids:
        insight_result = await db.execute(
            select(DeepInsight).where(DeepInsight.id.in_(task.result_insight_ids))
        )
        db_insights = insight_result.scalars().all()
        insight_map = {i.id: i for i in db_insights}
        for iid in task.result_insight_ids:
            ins = insight_map.get(iid)
            if ins:
                insights.append(ins)

    html_content = _build_report_html(task, insights)

    # 3. Publish to gh-pages -------------------------------------------------
    try:
        published_url = await _publish_to_ghpages(task, html_content, _REPO_DIR)
    except RuntimeError as exc:
        logger.exception("GitHub Pages publish failed for task %s", task_id)
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    # 4. Persist the published URL on the task -------------------------------
    task.published_url = published_url
    await db.commit()

    logger.info("Published report %s to %s", task_id, published_url)
    return {"published_url": published_url, "task_id": task_id}


# ---------------------------------------------------------------------------
# HTML report builder — Interactive Dashboard theme
# ---------------------------------------------------------------------------

_ACTION_COLORS = {
    "STRONG_BUY": "#22C55E",
    "BUY": "#22C55E",
    "HOLD": "#EAB308",
    "SELL": "#EF4444",
    "STRONG_SELL": "#EF4444",
    "WATCH": "#3B82F6",
}

_ACTION_BG = {
    "STRONG_BUY": "rgba(34,197,94,0.12)",
    "BUY": "rgba(34,197,94,0.10)",
    "HOLD": "rgba(234,179,8,0.10)",
    "SELL": "rgba(239,68,68,0.10)",
    "STRONG_SELL": "rgba(239,68,68,0.12)",
    "WATCH": "rgba(59,130,246,0.10)",
}

_ACTION_GLOW = {
    "STRONG_BUY": "0 0 12px rgba(34,197,94,0.4)",
    "STRONG_SELL": "0 0 12px rgba(239,68,68,0.4)",
}

_ACTION_LABELS = {
    "STRONG_BUY": "Strong Buy",
    "BUY": "Buy",
    "HOLD": "Hold",
    "SELL": "Sell",
    "STRONG_SELL": "Strong Sell",
    "WATCH": "Watch",
}

_ACTION_BORDER_COLORS = {
    "STRONG_BUY": "#22C55E",
    "BUY": "#22C55E",
    "HOLD": "#EAB308",
    "SELL": "#EF4444",
    "STRONG_SELL": "#EF4444",
    "WATCH": "#3B82F6",
}

# ---------------------------------------------------------------------------
# Analyst type color system (matches frontend design system)
# ---------------------------------------------------------------------------

_ANALYST_COLORS: dict[str, str] = {
    "technical": "#3B82F6",        # blue
    "technical_focus": "#3B82F6",
    "macro": "#A855F7",            # purple
    "macro_impact": "#A855F7",
    "sector_rotator": "#10B981",   # emerald
    "sector_deep_dive": "#10B981",
    "risk": "#F43F5E",             # rose
    "risk_scenario": "#F43F5E",
    "correlation": "#F59E0B",      # amber
    "correlation_analysis": "#F59E0B",
    "sentiment": "#06B6D4",        # cyan
    "prediction_markets": "#8B5CF6",  # violet
    "synthesis": "#6366F1",        # indigo
}

_ANALYST_ICONS: dict[str, str] = {
    "technical": "&#128200;",        # chart increasing
    "technical_focus": "&#128200;",
    "macro": "&#127758;",            # globe
    "macro_impact": "&#127758;",
    "sector_rotator": "&#128202;",   # bar chart
    "sector_deep_dive": "&#128202;",
    "risk": "&#128737;",             # shield
    "risk_scenario": "&#128737;",
    "correlation": "&#128279;",      # link
    "correlation_analysis": "&#128279;",
    "sentiment": "&#128172;",        # speech bubble
    "prediction_markets": "&#127922;",  # game die
    "synthesis": "&#129520;",        # puzzle piece
}

_ANALYST_DISPLAY_NAMES: dict[str, str] = {
    "technical": "Technical Analysis",
    "technical_focus": "Technical Analysis",
    "macro": "Macro Analysis",
    "macro_impact": "Macro Analysis",
    "sector_rotator": "Sector Analysis",
    "sector_deep_dive": "Sector Analysis",
    "risk": "Risk Assessment",
    "risk_scenario": "Risk Assessment",
    "correlation": "Correlation Analysis",
    "correlation_analysis": "Correlation Analysis",
    "sentiment": "Sentiment Analysis",
    "prediction_markets": "Prediction Markets",
    "synthesis": "Synthesis",
}


# ---------------------------------------------------------------------------
# Layman language helper
# ---------------------------------------------------------------------------

def _extract_symbols(text: str) -> list[str]:
    """Extract stock ticker symbols from text."""
    import re as _re
    matches = _re.findall(r"\b[A-Z]{2,5}\b", text)
    stop_words = {
        "VaR", "RSI", "MACD", "SMA", "EMA", "GDP", "CPI",
        "THE", "AND", "FOR", "NOT", "BUT", "ALL", "WITH", "THIS", "THAT",
    }
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in stop_words and m not in seen:
            seen.add(m)
            result.append(m)
    return result


def _extract_percentages(text: str) -> list[str]:
    """Extract percentage values from text."""
    import re as _re
    return _re.findall(r"[\d.]+%", text)


# Sentence-level pattern rewrites: (compiled_regex, rewrite_function)
_SENTENCE_PATTERNS: list[tuple[re.Pattern[str], object]] = []


def _init_sentence_patterns() -> list[tuple[re.Pattern[str], object]]:
    """Build and cache the list of sentence-level pattern rewrites."""
    if _SENTENCE_PATTERNS:
        return _SENTENCE_PATTERNS

    patterns: list[tuple[str, object]] = [
        # Late/mid/early cycle with recession + stagflation
        (
            r"(late|mid|early)[- ]cycle.*?(\d+)%\s*(?:confidence|prob).*?(\d+)%\s*recession.*?(\d+)%\s*stagflation",
            lambda m, _t: (
                f"The economy looks like it's "
                f"{'running out of steam' if m.group(1).lower() == 'late' else 'in the middle of its growth phase' if m.group(1).lower() == 'mid' else 'in the early stages of recovery'}. "
                f"There's {'a coin-flip chance' if int(m.group(3)) == 50 else f'about a {m.group(3)}% chance'} we enter a recession, "
                f"and about 1-in-{round(100 / int(m.group(4)))} odds of stagflation "
                f"(prices rising while the economy stalls). Both scenarios would hit growth-oriented investments hardest."
            ),
        ),
        # Late/mid/early cycle with recession only
        (
            r"(late|mid|early)[- ]cycle.*?(\d+)%\s*recession",
            lambda m, _t: (
                f"The economy looks like it's "
                f"{'running out of steam' if m.group(1).lower() == 'late' else 'in the middle of its growth phase' if m.group(1).lower() == 'mid' else 'in the early stages of recovery'}, "
                f"with {'a coin-flip chance' if int(m.group(2)) == 50 else f'about a {m.group(2)}% chance'} of a recession."
            ),
        ),
        # VaR with range
        (
            r"VaR\s*([\d.]+)[-\u2013]([\d.]+)%",
            lambda m, t: (
                f"On a bad day, your portfolio could drop {m.group(1)}-{m.group(2)}%."
                + (" This is higher than normal because your investments are bunched together in similar stocks."
                   if re.search(r"concentrat|cluster|correlat", t, re.IGNORECASE) else
                   " This kind of loss happens roughly 1 in 20 trading days.")
            ),
        ),
        # VaR single value
        (
            r"VaR\s*([\d.]+)%",
            lambda m, _t: f"On a bad day, your portfolio could drop about {m.group(1)}%. This kind of loss happens roughly 1 in 20 trading days.",
        ),
        # Squeeze + parabolic = synchronized risk
        (
            r"squeeze.*?\(([^)]+)\).*?parabolic.*?\(([^)]+)\)",
            lambda m, _t: (
                f"{m.group(1).strip()} are coiling up for a big move — like a compressed spring. "
                f"Meanwhile, {m.group(2).strip()} have been rising at an unsustainable pace. "
                f"The risk is these all unwind at the same time."
            ),
        ),
        # Distribution + squeeze uncertainty
        (
            r"distribution\s+signals?\s*\(([^)]+)\).*?squeeze\s+(?:uncertainty|signals?)\s*\(([^)]+)\)",
            lambda m, _t: (
                f"It looks like big investors may be quietly selling {m.group(1).strip()} while prices are still high. "
                f"{m.group(2).strip()} are in a holding pattern where a big price swing is brewing, but the direction isn't clear yet."
            ),
        ),
        # Distribution signals with symbols
        (
            r"distribution\s+signals?\s*\(([^)]+)\)",
            lambda m, _t: f"It looks like big investors may be quietly selling {m.group(1).strip()} while prices are still high.",
        ),
        # RSI divergence + MACD crossover + support
        (
            r"RSI\s+divergence.*MACD\s+(?:bearish\s+)?crossover.*support\s+(?:at\s+)?\$?([\d,.]+)",
            lambda m, _t: (
                f"The stock's momentum is fading even as the price holds steady — a warning sign. "
                f"The trend indicators just flipped negative, and the price is at a critical floor of ${m.group(1)}. "
                f"If it drops below, expect a bigger decline."
            ),
        ),
        # RSI divergence + MACD (no support)
        (
            r"RSI\s+divergence.*MACD",
            lambda _m, _t: "The stock's momentum is fading while the price holds steady — a warning sign. The trend indicators are confirming the current move may be losing steam.",
        ),
        # RSI with value
        (
            r"RSI\s*(?:at|above|below|near|of|is)?\s*(\d+)",
            lambda m, _t: (
                f"The stock's momentum gauge reads {m.group(1)}/100 — it's been running hot and may be due for a pullback."
                if int(m.group(1)) >= 70
                else f"The stock's momentum gauge reads just {m.group(1)}/100 — it's been beaten down and may be due for a bounce."
                if int(m.group(1)) <= 30
                else f"The stock's momentum is in a neutral zone at {m.group(1)}/100, with no strong push in either direction."
            ),
        ),
        # MACD bearish
        (r"MACD\s+bearish", lambda _m, _t: "A key trend indicator just flipped negative — the upward momentum is fading and caution is warranted."),
        # MACD bullish/crossover
        (r"MACD\s+(?:bullish|cross)", lambda _m, _t: "A key trend indicator just flipped positive, suggesting the downward pressure is easing."),
        # MACD divergence
        (r"MACD\s+divergence", lambda _m, _t: "Price and a key trend indicator are telling different stories — this often signals a reversal is coming."),
        # Support level
        (
            r"support\s+(?:at|near|around|level|of)?\s*\$?([\d,.]+)",
            lambda m, _t: f"There's a price floor around ${m.group(1)} where buyers have historically stepped in. If it breaks, expect a sharper drop.",
        ),
        # Resistance level
        (
            r"resistance\s+(?:at|near|around|level|of)?\s*\$?([\d,.]+)",
            lambda m, _t: f"There's a price ceiling around ${m.group(1)} where sellers have historically cashed out. Breaking through would be bullish.",
        ),
        # Breakout
        (r"break(?:out|ing\s+out)\s+(?:above|from|through)", lambda _m, _t: "The price just broke through a key ceiling, which often attracts new buyers and leads to further gains."),
        # Breakdown
        (r"break(?:down|ing\s+down)\s+(?:below|from|through)", lambda _m, _t: "The price just fell through a key floor, which often triggers more selling."),
        # Squeeze with symbols
        (
            r"squeeze\s*\(([^)]+)\)",
            lambda m, _t: f"{m.group(1).strip()} are coiling up for a big move — like a compressed spring that could snap either way.",
        ),
        # Squeeze generic
        (r"squeeze", lambda _m, _t: "Price swings have gotten unusually small — like the calm before a storm. A big move is likely coming soon."),
        # Accumulation
        (r"accumulation", lambda _m, _t: "Large investors appear to be quietly buying, building positions while the price is still low."),
        # Distribution generic
        (r"distribution", lambda _m, _t: "Large investors appear to be quietly selling while prices are still high."),
        # Parabolic
        (r"parabolic", lambda _m, _t: "The price has been rising at an unsustainable pace. Like a ball thrown in the air, it will eventually come back down."),
        # Stagflation
        (r"stagflation", lambda _m, _t: "There's a risk of stagflation — prices keep rising while the economy stalls. It's tough for most investments."),
        # Late-cycle alone
        (r"late[- ]cycle", lambda _m, _t: "The economy appears to be in the later stages of its growth cycle. Historically, this is when markets become more volatile."),
        # Breadth narrowing
        (r"breadth\s+(?:narrowing|declining|weakening)", lambda _m, _t: "Fewer stocks are participating in the rally, which is a warning sign for the broader market."),
        # Breadth improving
        (r"breadth\s+(?:improving|expanding|strengthening)", lambda _m, _t: "More stocks are joining the rally — a healthy sign that the uptrend has staying power."),
        # Volatility expansion
        (r"volatility\s+(?:expansion|spike|surge)", lambda _m, _t: "Market swings are getting bigger — expect larger daily price moves in both directions."),
        # Volatility contraction
        (r"volatility\s+(?:contraction|compression|low)", lambda _m, _t: "The market has been unusually calm. This quiet often comes before a sharp move."),
        # Momentum fading
        (r"momentum\s+(?:divergence|weakening|fading|stalling)", lambda _m, _t: "The speed of price moves is slowing down — the stock is coasting and may be losing direction."),
        # Yield curve inverted
        (r"(?:yield\s+curve\s+)?invert(?:ed|ion)", lambda _m, _t: "Short-term bonds are paying more than long-term ones (unusual) — historically one of the most reliable recession warning signs."),
        # Yield curve steepening
        (r"yield\s+curve\s+steepening", lambda _m, _t: "The gap between short and long-term rates is widening, which typically signals expectations of stronger economic growth."),
        # Recession probability
        (
            r"(\d+)%\s*(?:recession|chance of recession)",
            lambda m, _t: (
                f"There's a {m.group(1)}% chance of a recession — the economy may shrink, which would be bad for most investments."
                if int(m.group(1)) >= 70
                else f"There's a meaningful {m.group(1)}% chance of recession — not certain, but high enough to warrant caution."
                if int(m.group(1)) >= 40
                else f"Recession risk is relatively low at {m.group(1)}%."
            ),
        ),
        # Mean reversion
        (r"mean\s+reversion", lambda _m, _t: "Prices have stretched far from their average and may snap back, like a rubber band being pulled."),
        # Head and shoulders
        (r"head\s+and\s+shoulders", lambda _m, _t: "The price chart has formed a pattern that often appears before a significant downturn."),
        # Golden cross
        (r"golden\s+cross", lambda _m, _t: "A rare bullish signal: the short-term trend crossed above the long-term trend, suggesting upward momentum."),
        # Death cross
        (r"death\s+cross", lambda _m, _t: "A bearish signal: the short-term trend crossed below the long-term trend, suggesting downward momentum."),
        # Double top
        (r"double\s+top", lambda _m, _t: "The price tried to break higher twice and failed both times — this often signals the stock has hit its ceiling."),
        # Double bottom
        (r"double\s+bottom", lambda _m, _t: "The price bounced off the same floor twice — this often signals the worst is over."),
        # Regime shift
        (r"regime\s+(?:change|shift|transition)", lambda _m, _t: "The overall market environment is fundamentally changing. Strategies that worked recently may stop working."),
        # Overbought
        (r"overbought", lambda _m, _t: "The stock has risen fast and may be stretched too high — it could be due for a pullback."),
        # Oversold
        (r"oversold", lambda _m, _t: "The stock has fallen fast and may have been pushed too low — it could be due for a bounce."),
        # Hawkish
        (r"hawkish", lambda _m, _t: "The central bank is leaning toward raising interest rates to fight inflation, which can slow down the economy and weigh on stocks."),
        # Dovish
        (r"dovish", lambda _m, _t: "The central bank is leaning toward keeping rates low to support growth, which is generally good for stocks."),
    ]

    for pattern_str, rewrite_fn in patterns:
        _SENTENCE_PATTERNS.append((re.compile(pattern_str, re.IGNORECASE), rewrite_fn))

    return _SENTENCE_PATTERNS


def generate_layman_explanation(analyst_type: str, technical_text: str) -> str:
    """Generate a complete plain-English rewrite of a technical finding.

    Instead of inserting ``term = definition`` glossary entries, this function
    detects the overall meaning of the sentence and produces a fully rewritten
    explanation in conversational English.

    The *analyst_type* is used for Tier 2 contextual framing when no specific
    sentence pattern matches.

    Returns a string suitable for display under each analyst finding, or an
    empty string when no meaningful simplification is possible.
    """
    if not technical_text:
        return ""

    patterns = _init_sentence_patterns()

    # Tier 1: Full-sentence pattern rewrites
    for compiled, rewrite_fn in patterns:
        m = compiled.search(technical_text)
        if m:
            return rewrite_fn(m, technical_text)

    # Tier 2: Analyst-type contextual rewrite with extracted data
    symbols = _extract_symbols(technical_text)
    percentages = _extract_percentages(technical_text)

    symbol_phrase = f" for {', '.join(symbols[:3])}" if symbols else ""
    pct_phrase = f" Key numbers: {', '.join(percentages[:3])}." if percentages else ""

    at = analyst_type.lower()
    if "technical" in at:
        return f"The chart patterns and price trends{symbol_phrase} are showing a notable signal.{pct_phrase} This is worth watching as it may indicate where the price is headed next."
    elif "macro" in at:
        return f"Looking at the broader economy, conditions are shifting in a way that could affect your investments{symbol_phrase}.{pct_phrase}"
    elif "risk" in at:
        return f"From a risk perspective, there are signals{symbol_phrase} that warrant attention.{pct_phrase} This doesn't mean something bad will happen, but it's worth being prepared."
    elif "sector" in at:
        return f"Industry-level trends are signaling a shift{symbol_phrase}.{pct_phrase} Some sectors are gaining favor while others are falling out."
    elif "correlation" in at:
        return f"Looking at how these investments move together{symbol_phrase}, an unusual pattern has emerged.{pct_phrase}"
    elif "sentiment" in at:
        return f"Market sentiment{symbol_phrase} is sending a signal worth noting.{pct_phrase} What other investors think can influence where prices head next."

    # Tier 3: Generic fallback
    if symbols or percentages:
        data_parts: list[str] = []
        if symbols:
            data_parts.append(f"involving {', '.join(symbols[:3])}")
        if percentages:
            data_parts.append(f"with key figures of {' and '.join(percentages[:2])}")
        return f"This analyst spotted something noteworthy {', '.join(data_parts)}."

    return ""


def _esc(text: str | None) -> str:
    """Escape HTML entities."""
    if text is None:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "N/A"
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _confidence_color(confidence: float) -> str:
    """Return color for confidence gauge: green >0.8, yellow 0.6-0.8, red <0.6."""
    if confidence >= 0.8:
        return "#10B981"
    elif confidence >= 0.6:
        return "#F59E0B"
    return "#EF4444"


def _regime_color(regime: str) -> str:
    """Return a color for a market regime string."""
    rl = regime.lower()
    if "bull" in rl or "expansion" in rl or "risk-on" in rl:
        return "#10B981"
    elif "bear" in rl or "contraction" in rl or "risk-off" in rl:
        return "#EF4444"
    elif "neutral" in rl or "mixed" in rl or "transitional" in rl:
        return "#F59E0B"
    return "#6366F1"


def _build_insight_data_json(insights: list[DeepInsight]) -> str:
    """Build a JSON array of insight metadata for use by JavaScript filters."""
    data = []
    for i, ins in enumerate(insights):
        data.append({
            "index": i,
            "action": ins.action or "WATCH",
            "confidence": ins.confidence or 0,
        })
    return json.dumps(data)


def _extract_sectors_from_summary(result_summary: str | None) -> list[str]:
    """Extract sector data from executive summary text as a fallback.

    Looks for patterns like:
    - ``Sectors Scanned:`` followed by ``- SectorName: +X.X% ...``
    - ``Sector Focus:`` followed by ``- SectorName (RS: +X.X%)``
    - Inline ``SectorName: +X.X%`` or ``SectorName (+X.X%)``

    Returns a list like ``["Energy +0.7%", "Technology +1.6%"]``.
    """
    if not result_summary:
        return []

    sectors: list[str] = []

    # Known GICS sector names to look for
    known_sectors = [
        "Technology", "Financials", "Energy", "Healthcare", "Health Care",
        "Consumer Discretionary", "Consumer Staples", "Industrials",
        "Materials", "Utilities", "Real Estate", "Communication Services",
        "Communications", "Telecom",
    ]

    # Pattern 1: Lines after "Sectors Scanned:" or "Sector Focus:"
    # e.g. "- Technology: +1.6% (1D), breadth 70%"
    # e.g. "- Energy (RS: +15.8%)"
    section_pattern = re.compile(
        r"(?:Sectors?\s+(?:Scanned|Focus|Rotation|Analysis))[\s:]*\n",
        re.IGNORECASE,
    )
    section_match = section_pattern.search(result_summary)
    if section_match:
        after = result_summary[section_match.end():]
        for line in after.split("\n"):
            stripped = line.strip()
            if not stripped:
                break
            # Stop if we hit a new heading
            if re.match(r"^#{1,4}\s+", stripped) or re.match(r"^[A-Z][a-z].*:$", stripped):
                break
            # "- SectorName: +X.X% ..." or "- SectorName (+X.X%)"
            line_match = re.match(
                r"^[-*]\s+(.+?)(?::\s*|\s*\()([+-]?\d+(?:\.\d+)?)%",
                stripped,
            )
            if line_match:
                name = line_match.group(1).strip().rstrip("(")
                val = line_match.group(2)
                sign = "+" if not val.startswith("-") and not val.startswith("+") else ""
                sectors.append(f"{name} {sign}{val}%")

    # If we found sectors from a section, return them
    if sectors:
        return sectors

    # Pattern 2: Scan entire text for "KnownSector: +X.X%" or "KnownSector (+X.X%)"
    for sector_name in known_sectors:
        # "Technology: +1.6%" or "Technology: -0.3%"
        p1 = re.search(
            rf"\b{re.escape(sector_name)}\s*:\s*([+-]?\d+(?:\.\d+)?)%",
            result_summary,
            re.IGNORECASE,
        )
        if p1:
            val = p1.group(1)
            sign = "+" if not val.startswith("-") and not val.startswith("+") else ""
            sectors.append(f"{sector_name} {sign}{val}%")
            continue
        # "Technology (+1.6%)" or "Technology (RS: +15.8%)"
        p2 = re.search(
            rf"\b{re.escape(sector_name)}\s*\([^)]*?([+-]?\d+(?:\.\d+)?)%\)",
            result_summary,
            re.IGNORECASE,
        )
        if p2:
            val = p2.group(1)
            sign = "+" if not val.startswith("-") and not val.startswith("+") else ""
            sectors.append(f"{sector_name} {sign}{val}%")

    return sectors


def _build_tldr_section(
    insights: list[DeepInsight],
    regime: str,
    sectors: list[str],
) -> str:
    """Build a TL;DR action-oriented summary box for the Executive Briefing.

    Generates plain-English bullet points telling the reader what to do based
    on the market regime, top opportunities, sector data, and confidence
    distribution.  Returns an HTML string ready to be inserted at the top of
    the Executive Briefing section.
    """
    bullets: list[str] = []

    # --- 1. Market regime action ---
    rl = regime.lower()
    if "bull" in rl or "expansion" in rl or "risk-on" in rl:
        bullets.append(
            "Market is <strong>bullish</strong> &mdash; consider "
            "increasing equity exposure and riding momentum."
        )
    elif "bear" in rl or "contraction" in rl or "risk-off" in rl:
        bullets.append(
            "Market is <strong>bearish</strong> &mdash; consider "
            "defensive positioning, raising cash, or hedging."
        )
    elif "transitional" in rl or "mixed" in rl or "neutral" in rl:
        bullets.append(
            "Market is <strong>transitional</strong> &mdash; be cautious "
            "with new positions and wait for clearer signals."
        )
    elif "volatile" in rl or "choppy" in rl:
        bullets.append(
            "Market is <strong>volatile</strong> &mdash; reduce position "
            "sizes and tighten stops."
        )
    else:
        bullets.append(
            f"Market regime is <strong>{_esc(regime)}</strong> &mdash; "
            "review the full briefing below for context."
        )

    # --- 2. Top opportunities (top 3 insights by confidence with symbols) ---
    symbol_insights = [
        ins for ins in insights if ins.primary_symbol and ins.action != "WATCH"
    ]
    # Sort by confidence descending
    symbol_insights.sort(key=lambda ins: ins.confidence or 0, reverse=True)
    top_symbols = []
    for ins in symbol_insights[:3]:
        action_label = _ACTION_LABELS.get(ins.action or "WATCH", ins.action or "WATCH")
        top_symbols.append(f"{_esc(ins.primary_symbol)} ({action_label})")
    if top_symbols:
        bullets.append(
            "<strong>Look into:</strong> " + ", ".join(top_symbols) + "."
        )
    elif insights:
        bullets.append(
            "No specific ticker opportunities surfaced &mdash; insights "
            "are thematic or macro-level."
        )

    # --- 3. Sector guidance ---
    positive_sectors: list[tuple[str, float]] = []
    negative_sectors: list[tuple[str, float]] = []
    for s in sectors:
        m = re.search(r"([+-]?\d+(?:\.\d+)?)%", s)
        if m:
            val = float(m.group(1))
            name = s[: m.start()].strip()
            if val > 0:
                positive_sectors.append((name, val))
            elif val < 0:
                negative_sectors.append((name, val))
    positive_sectors.sort(key=lambda x: x[1], reverse=True)
    negative_sectors.sort(key=lambda x: x[1])

    sector_parts: list[str] = []
    if positive_sectors:
        top_pos = [n for n, _ in positive_sectors[:3]]
        sector_parts.append(
            "<strong>Sectors favoring:</strong> " + ", ".join(top_pos)
        )
    if negative_sectors:
        top_neg = [n for n, _ in negative_sectors[:2]]
        sector_parts.append(
            "<strong>Caution:</strong> " + ", ".join(top_neg)
        )
    if sector_parts:
        bullets.append(". ".join(sector_parts) + ".")
    elif sectors:
        bullets.append(
            "Sector data available but no clear winners or losers."
        )

    # --- 4. Confidence summary ---
    if insights:
        confidences = [ins.confidence or 0 for ins in insights]
        avg_conf = sum(confidences) / len(confidences)
        high_count = sum(1 for c in confidences if c >= 0.8)
        total = len(confidences)
        if avg_conf >= 0.8:
            conf_note = "Analysis confidence is <strong>high</strong>"
        elif avg_conf >= 0.6:
            conf_note = "Analysis confidence is <strong>moderate</strong>"
        else:
            conf_note = "Analysis confidence is <strong>low</strong>"
        conf_note += (
            f" &mdash; {high_count} of {total} insights above 80% confidence."
        )
        bullets.append(conf_note)

    if not bullets:
        return ""

    items_html = "\n".join(f"      <li>{b}</li>" for b in bullets)

    return f"""
    <div class="tldr-box">
      <div class="tldr-header">
        <span class="tldr-icon">&#9889;</span>
        <span class="tldr-title">TL;DR &mdash; What Should You Do?</span>
      </div>
      <ul class="tldr-list">
{items_html}
      </ul>
    </div>
"""


def _build_sector_bars(sectors: list[str]) -> str:
    """Build sector bars with visual relative-strength indicators.

    Parses sector strings like 'Energy +15.8%' into name + value bars.
    Bars grow from a center zero-line: right for positive, left for negative.
    Falls back to simple badges if no numeric value is found.
    """
    if not sectors:
        return '<div style="color:#475569;font-size:14px;">No sector data.</div>'

    parsed: list[tuple[str, float | None, str]] = []
    max_abs = 0.0
    for s in sectors:
        # Try to extract a percentage like "+15.8%" or "-4.8%"
        m = re.search(r"([+-]?\d+(?:\.\d+)?)%", s)
        if m:
            val = float(m.group(1))
            name = s[:m.start()].strip()
            raw_pct = m.group(0)
            parsed.append((name, val, raw_pct))
            if abs(val) > max_abs:
                max_abs = abs(val)
        else:
            parsed.append((s, None, ""))

    if max_abs == 0:
        max_abs = 1.0

    # Build bar rows.  Each bar track is split into left (negative) and right
    # (positive) halves around a center zero-line.  The fill width is relative
    # to max_abs so the largest bar spans 50% of the track (one full half).
    items = ""
    for name, val, raw_pct in parsed:
        if val is not None:
            # half_pct: 0-50 representing how much of the half to fill
            half_pct = min(int(abs(val) / max_abs * 50), 50)
            if val >= 0:
                color = "#10B981"
                num_cls = "num-positive"
                # Positive: bar in right half, starts at 50%, grows right
                fill_style = (
                    f"left:50%;width:{half_pct}%;background:{color};"
                    f"border-radius:0 4px 4px 0;"
                )
            else:
                color = "#EF4444"
                num_cls = "num-negative"
                # Negative: bar in left half, ends at 50%, grows left
                fill_style = (
                    f"right:50%;width:{half_pct}%;background:{color};"
                    f"border-radius:4px 0 0 4px;"
                )
            items += f"""
            <div class="sector-bar-row">
              <span class="sector-bar-name">{_esc(name)}</span>
              <div class="sector-bar-track">
                <div class="sector-bar-zero"></div>
                <div class="sector-bar-fill" style="{fill_style}"></div>
              </div>
              <span class="sector-bar-val {num_cls}">{_esc(raw_pct)}</span>
            </div>"""
        else:
            items += f"""
            <div class="sector-bar-row">
              <span class="sector-bar-name">{_esc(name)}</span>
            </div>"""

    # Rounded scale label for axis edges
    scale_label = f"{max_abs:.1f}".rstrip("0").rstrip(".")

    return f"""<div class="sector-bars">
      <div class="sector-bars-subtitle">
        1-Day Price Change&nbsp;&mdash;&nbsp;
        <span style="color:#10B981;">&#9632;</span> positive&nbsp;&nbsp;
        <span style="color:#EF4444;">&#9632;</span> negative
      </div>
      {items}
      <div class="sector-bar-axis">
        <span class="sector-bar-name"></span>
        <div class="sector-bar-axis-track">
          <span class="sector-bar-axis-label" style="left:0;">-{scale_label}%</span>
          <span class="sector-bar-axis-label" style="left:50%;transform:translateX(-50%);">0%</span>
          <span class="sector-bar-axis-label" style="right:0;">+{scale_label}%</span>
        </div>
        <span class="sector-bar-val"></span>
      </div>
    </div>"""


_PHASE_DESCRIPTIONS: dict[str, str] = {
    "macro_scan": "Scanned macroeconomic indicators including GDP, inflation, yields, and commodity prices to establish the current economic regime and identify macro-level trends.",
    "heatmap_fetch": "Fetched real-time market data across all tracked sectors and symbols, including price changes, volume, and breadth indicators.",
    "heatmap_analysis": "Analyzed sector heatmap data to identify rotation patterns, relative strength, and divergences between sectors.",
    "deep_dive": "Performed deep fundamental and technical analysis on selected high-opportunity stocks, examining catalysts, risks, and price targets.",
    "coverage_evaluation": "Evaluated analysis coverage to ensure portfolio holdings and key sectors received adequate attention.",
    "synthesis": "Synthesized findings from all phases into cohesive investment insights with actionable recommendations and confidence scores.",
    "sector_rotation": "Analyzed sector rotation dynamics to identify which sectors are gaining/losing momentum and where capital is flowing.",
    "opportunity_hunt": "Hunted for specific trading opportunities across the market based on identified patterns and sector dynamics.",
}

_PHASE_ICONS: dict[str, str] = {
    "macro_scan": "&#127758;",       # globe
    "heatmap_fetch": "&#128229;",    # inbox tray
    "heatmap_analysis": "&#128202;", # chart
    "deep_dive": "&#128269;",        # magnifying glass
    "coverage_evaluation": "&#9989;",# white check
    "synthesis": "&#129520;",        # puzzle piece
    "sector_rotation": "&#128260;",  # arrows cycle
    "opportunity_hunt": "&#127919;", # target
}


def _phase_display_name(phase: str) -> str:
    """Convert snake_case phase name to Title Case."""
    return phase.replace("_", " ").title()


def _build_phase_timeline(
    phases: list[str],
    phase_summaries: dict[str, str] | None = None,
) -> str:
    """Build a collapsible accordion for completed phases."""
    if not phases:
        return '<div style="color:#475569;font-size:14px;">No phase data available.</div>'

    summaries = phase_summaries or {}
    items = ""
    for i, phase in enumerate(phases):
        display = _phase_display_name(phase)
        icon = _PHASE_ICONS.get(phase, "&#9679;")
        step_num = i + 1
        real_summary = summaries.get(phase)
        if real_summary:
            desc_html = f'<p class="phase-desc">{_esc(real_summary)}</p>'
        else:
            fallback = _PHASE_DESCRIPTIONS.get(phase, "Completed successfully.")
            desc_html = (
                f'<p class="phase-desc phase-desc-fallback"'
                f' style="opacity:0.6;font-style:italic;">'
                f"{_esc(fallback)}"
                f"</p>"
            )
        items += f"""
        <div class="phase-accordion" data-phase="{_esc(phase)}">
          <button class="phase-header" onclick="togglePhase(this)" aria-expanded="false">
            <div class="phase-header-left">
              <span class="phase-step-num">{step_num}</span>
              <span class="phase-icon">{icon}</span>
              <span class="phase-name">{_esc(display)}</span>
            </div>
            <div class="phase-header-right">
              <span class="phase-status-badge">Completed</span>
              <svg class="phase-chevron" width="16" height="16" viewBox="0 0 24 24"
                   fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </div>
          </button>
          <div class="phase-content">
            {desc_html}
          </div>
        </div>
"""
    total = len(phases)
    return f"""
    <div class="phase-timeline-header">
      <span class="phase-count-badge">{total} / {total} phases</span>
      <button class="phase-expand-all-btn" onclick="toggleAllPhases()">Expand All</button>
    </div>
    <div class="phase-accordion-list">{items}</div>"""


def _ta_rating_explanation(rating: str) -> str:
    """Return a fallback explanation for a technical analysis rating (used only when data-driven explanation unavailable)."""
    explanations = {
        "strong buy": "Multiple technical indicators align bullish — a strong entry signal",
        "buy": "Most indicators lean positive — conditions favor buying",
        "neutral": "Mixed signals from indicators — no clear direction",
        "sell": "Most indicators lean negative — caution advised",
        "strong sell": "Multiple indicators align bearish — significant downside risk",
    }
    return explanations.get(rating.lower().strip(), "")


def _build_ta_data_driven_explanation(ta: dict) -> str:
    """Build a data-driven explanation referencing actual TA values."""
    parts: list[str] = []
    score = ta.get("composite_score")
    bd = ta.get("breakdown") or {}

    # Composite score context
    if score is not None:
        score_val = float(score)
        score_abs = abs(score_val)
        direction = "bullish" if score_val >= 0 else "bearish"
        strength = "strongly" if score_abs > 0.6 else "moderately" if score_abs > 0.3 else "mildly"
        parts.append(f"Composite score {score_val:+.2f} — {strength} {direction}")

    if bd:
        # Identify which dimensions are driving the rating
        drivers: list[str] = []
        for key in ("trend", "momentum", "volume"):
            val = bd.get(key)
            if val is not None and abs(float(val)) > 0.3:
                drivers.append(f"{key} at {float(val):+.2f}")
        if drivers:
            parts.append(f"Driven by {', '.join(drivers)}")

        # Divergence callouts
        trend_val = float(bd.get("trend", 0))
        momentum_val = float(bd.get("momentum", 0))
        volume_val = float(bd.get("volume", 0))
        volatility_val = float(bd.get("volatility", 0))

        divergences: list[str] = []
        if trend_val > 0.2 and momentum_val < -0.2:
            divergences.append("Trend is positive but momentum is fading — potential reversal risk")
        elif trend_val < -0.2 and momentum_val > 0.2:
            divergences.append("Momentum building despite weak trend — watch for breakout")
        if momentum_val > 0.3 and volume_val < -0.2:
            divergences.append("Momentum rising on declining volume — move may lack conviction")
        if volatility_val > 0.5:
            divergences.append(f"Volatility elevated at {volatility_val:+.2f} — expect outsized moves")
        if divergences:
            parts.append(". ".join(divergences))

    return ". ".join(parts) + "." if parts else ""


def _build_key_levels_explanation(ta: dict) -> str:
    """Build contextual explanation for key support/resistance levels."""
    kl = ta.get("key_levels") or {}
    support_list = kl.get("support", [])
    resistance_list = kl.get("resistance", [])
    parts: list[str] = []

    if isinstance(support_list, list) and support_list:
        nearest = max(float(s) for s in support_list)
        parts.append(f"Nearest support at ${nearest:,.2f} — a break below could accelerate selling")
    if isinstance(resistance_list, list) and resistance_list:
        nearest = min(float(r) for r in resistance_list)
        parts.append(f"Nearest resistance at ${nearest:,.2f} — needs a break above for continuation")
    if support_list and resistance_list:
        try:
            rng = min(float(r) for r in resistance_list) - max(float(s) for s in support_list)
            if rng > 0:
                parts.append(f"Trading range: ${rng:,.2f} between key support and resistance")
        except (TypeError, ValueError):
            pass

    return ". ".join(parts) + "." if parts else ""


def _ta_breakdown_meaning(key: str, val: float) -> str:
    """Return a short plain-English meaning for a TA breakdown metric."""
    if key == "trend":
        if val > 0.5:
            return "Strong upward price trend"
        if val > 0:
            return "Mild upward trend"
        if val > -0.5:
            return "Mild downward trend"
        return "Strong downward price trend"
    if key == "momentum":
        if val > 0.5:
            return "Strong buying pressure"
        if val > 0:
            return "Mild buying pressure"
        if val > -0.5:
            return "Mild selling pressure"
        return "Strong selling pressure"
    if key == "volatility":
        if val > 0.5:
            return "Very large price swings"
        if val > 0:
            return "Moderate price swings"
        if val > -0.5:
            return "Below-average price swings"
        return "Very low price swings"
    if key == "volume":
        if val > 0.5:
            return "Very high trading activity"
        if val > 0:
            return "Above-average trading activity"
        if val > -0.5:
            return "Below-average trading activity"
        return "Very low trading activity"
    return ""


def _build_analysis_sources_html(ins: DeepInsight) -> str:
    """Build a collapsible Analysis Sources section for an insight card.

    Renders available technical analysis, prediction market, and sentiment
    data in a compact expandable panel.  Returns an empty string when none
    of the three data fields are populated.
    """
    ta = ins.technical_analysis_data
    pred = ins.prediction_market_data
    sent = ins.sentiment_data

    if not ta and not pred and not sent:
        return ""

    sections: list[str] = []

    # --- Technical Analysis ---
    if ta and isinstance(ta, dict):
        score = ta.get("composite_score")
        rating = ta.get("rating", "")
        confidence = ta.get("confidence")
        breakdown = ta.get("breakdown") or {}

        # Score color: green positive, red negative, amber near zero
        score_val = float(score) if score is not None else 0.0
        if score_val > 0.2:
            score_color = "#10B981"
        elif score_val < -0.2:
            score_color = "#EF4444"
        else:
            score_color = "#F59E0B"

        score_display = f"{score_val:+.2f}" if score is not None else "N/A"
        rating_display = _esc(str(rating)) if rating else ""
        conf_display = (
            f"{int(float(confidence) * 100)}%"
            if confidence is not None
            else ""
        )

        # Data-driven explanation text (falls back to generic if no data)
        explain_text = _build_ta_data_driven_explanation(ta) or (
            _ta_rating_explanation(str(rating)) if rating else ""
        )

        # Breakdown mini-bars (trend, momentum, volatility, volume)
        breakdown_html = ""
        breakdown_keys = ["trend", "momentum", "volatility", "volume"]
        for key in breakdown_keys:
            val = breakdown.get(key)
            if val is None:
                continue
            bar_val = float(val)
            # Normalize to 0-100 range (values are typically -1 to 1)
            bar_pct = min(max(int((bar_val + 1) / 2 * 100), 0), 100)
            if bar_val > 0.2:
                bar_color = "#10B981"
            elif bar_val < -0.2:
                bar_color = "#EF4444"
            else:
                bar_color = "#F59E0B"
            meaning = _ta_breakdown_meaning(key, bar_val)
            breakdown_html += (
                f'<div class="src-breakdown-row">'
                f'<span class="src-breakdown-label">{_esc(key.title())}</span>'
                f'<div class="src-breakdown-track">'
                f'<div class="src-breakdown-center"></div>'
                f'<div class="src-breakdown-fill" style="width:{bar_pct}%;background:{bar_color};"></div>'
                f'</div>'
                f'<span class="src-breakdown-val" style="color:{bar_color};">{bar_val:+.2f}</span>'
                f'</div>'
            )
            if meaning:
                breakdown_html += (
                    f'<div class="src-breakdown-meaning">{_esc(meaning)}</div>'
                )

        ta_html = (
            f'<div class="src-section">'
            f'<div class="src-section-title">Technical Analysis</div>'
            f'<div class="src-ta-header">'
            f'<span class="src-ta-score" style="color:{score_color};">{score_display}</span>'
        )
        if rating_display:
            ta_html += f'<span class="src-ta-rating">{rating_display}</span>'
        if conf_display:
            ta_html += f'<span class="src-ta-conf">{conf_display} confidence</span>'
        ta_html += '</div>'
        if explain_text:
            ta_html += f'<div class="src-ta-explain">{_esc(explain_text)}</div>'
        if breakdown_html:
            ta_html += f'<div class="src-breakdown">{breakdown_html}</div>'

        # Key levels: support and resistance (handle both flat and nested key_levels format)
        key_levels = ta.get("key_levels") or {}
        support_list = key_levels.get("support", []) if isinstance(key_levels, dict) else []
        resistance_list = key_levels.get("resistance", []) if isinstance(key_levels, dict) else []
        pivot_val = key_levels.get("pivot") if isinstance(key_levels, dict) else None
        # Fallback to flat keys for older data format
        flat_support = ta.get("support")
        flat_resistance = ta.get("resistance")
        if not support_list and flat_support is not None:
            support_list = [flat_support]
        if not resistance_list and flat_resistance is not None:
            resistance_list = [flat_resistance]

        if support_list or resistance_list:
            ta_html += '<div class="src-key-levels">'
            if support_list:
                support_strs = ", ".join(f"${float(s):,.2f}" for s in support_list)
                ta_html += (
                    f'<span class="src-level">'
                    f'<span class="src-level-label">Support (floor):</span>'
                    f'<span class="src-level-val" style="color:#10B981;">{support_strs}</span>'
                    f'</span>'
                )
            if resistance_list:
                resistance_strs = ", ".join(f"${float(r):,.2f}" for r in resistance_list)
                ta_html += (
                    f'<span class="src-level">'
                    f'<span class="src-level-label">Resistance (ceiling):</span>'
                    f'<span class="src-level-val" style="color:#EF4444;">{resistance_strs}</span>'
                    f'</span>'
                )
            if pivot_val is not None:
                ta_html += (
                    f'<span class="src-level">'
                    f'<span class="src-level-label">Pivot:</span>'
                    f'<span class="src-level-val">${float(pivot_val):,.2f}</span>'
                    f'</span>'
                )
            ta_html += '</div>'

            # Contextual key levels explanation
            levels_explain = _build_key_levels_explanation(ta)
            if levels_explain:
                ta_html += f'<div class="src-ta-explain" style="margin-top:6px;">{_esc(levels_explain)}</div>'

        ta_html += '</div>'
        sections.append(ta_html)

    # --- Prediction Markets ---
    if pred and isinstance(pred, dict):
        cards: list[str] = []
        available_sources: list[str] = []

        # Fed rate probabilities (handle both old flat and new nested format)
        fed = pred.get("fed_rates") or pred.get("fed_rate")
        if isinstance(fed, dict):
            next_meeting = fed.get("next_meeting") or {}
            probabilities = next_meeting.get("probabilities") if isinstance(next_meeting, dict) else None
            fed_source = fed.get("source", "")
            meeting_date = next_meeting.get("date", "") if isinstance(next_meeting, dict) else ""

            if probabilities and isinstance(probabilities, dict):
                # New format: multiple probability entries
                available_sources.append("Fed rate probabilities")
                for action_name, prob_val in probabilities.items():
                    if prob_val is None:
                        continue
                    pval = float(prob_val)
                    pct = int(pval * 100) if pval <= 1 else int(pval)
                    bar_w = min(max(pct, 0), 100)
                    action_lower = action_name.lower()
                    # Color: rate cuts green (easing), hikes red (tightening), hold amber
                    if "cut" in action_lower:
                        val_color = "#10B981"
                    elif "hike" in action_lower or "raise" in action_lower:
                        val_color = "#EF4444"
                    else:
                        val_color = "#F59E0B"

                    # Data-driven explanation for each probability
                    if "cut" in action_lower:
                        if pct < 5:
                            explain = f"Markets see almost no chance of a rate cut ({pct}%)"
                        elif pct < 30:
                            explain = f"Rate cut unlikely at {pct}% — not priced in"
                        elif pct < 60:
                            explain = f"Moderate {pct}% chance of a rate cut — markets uncertain"
                        else:
                            explain = f"Markets pricing in a rate cut at {pct}%"
                    elif "hike" in action_lower or "raise" in action_lower:
                        if pct < 5:
                            explain = f"Rate hike virtually ruled out at {pct}%"
                        elif pct < 30:
                            explain = f"Small {pct}% chance of a rate hike — unlikely but not zero"
                        else:
                            explain = f"Rate hike probability at {pct}% — tightening risk"
                    elif "hold" in action_lower or "no change" in action_lower or "unchanged" in action_lower:
                        if pct > 80:
                            explain = f"Markets overwhelmingly ({pct}%) expect rates unchanged"
                        elif pct > 50:
                            explain = f"Rates likely unchanged at {pct}% — base case is hold"
                        else:
                            explain = f"Hold probability at {pct}% — mixed expectations"
                    else:
                        explain = f"{pct}% probability"

                    source_label = f" ({_esc(fed_source)})" if fed_source else ""
                    card_html = (
                        f'<div class="src-pred-card">'
                        f'<div class="src-pred-label">{_esc(action_name)}{source_label}</div>'
                        f'<div class="src-pred-value" style="color:{val_color};">{pct}%</div>'
                    )
                    if bar_w > 0:
                        card_html += (
                            f'<div class="src-pred-bar">'
                            f'<div class="src-pred-bar-fill" style="width:{bar_w}%;background:{val_color};"></div>'
                            f'</div>'
                        )
                    card_html += f'<div class="src-pred-explain">{_esc(explain)}</div>'
                    card_html += '</div>'
                    cards.append(card_html)

                if meeting_date:
                    cards.append(
                        f'<div class="src-pred-card" style="opacity:0.7;">'
                        f'<div class="src-pred-label">Next FOMC Meeting</div>'
                        f'<div class="src-pred-value" style="color:#94a3b8;font-size:0.85em;">{_esc(meeting_date)}</div>'
                        f'</div>'
                    )
            else:
                # Old format: single consensus value
                consensus = fed.get("consensus") or fed.get("next_move")
                prob = fed.get("probability")
                if consensus:
                    available_sources.append("Fed rate outlook")
                    prob_pct = ""
                    explain = ""
                    if prob is not None:
                        pval = float(prob) if isinstance(prob, (int, float)) and float(prob) <= 1 else None
                        if pval is not None:
                            prob_pct = f"{int(pval * 100)}%"
                            explain = f"{prob_pct} chance the Fed cuts rates by 25bp at the next meeting"
                        else:
                            prob_pct = str(prob)
                    display_val = prob_pct if prob_pct else _esc(str(consensus))
                    card_html = (
                        f'<div class="src-pred-card">'
                        f'<div class="src-pred-label">Fed Rate</div>'
                        f'<div class="src-pred-value" style="color:#3b82f6;">{display_val}</div>'
                    )
                    if prob_pct and isinstance(prob, (int, float)) and float(prob) <= 1:
                        bar_w = int(float(prob) * 100)
                        card_html += (
                            f'<div class="src-pred-bar">'
                            f'<div class="src-pred-bar-fill" style="width:{bar_w}%;"></div>'
                            f'</div>'
                        )
                    if explain:
                        card_html += f'<div class="src-pred-explain">{_esc(explain)}</div>'
                    elif consensus:
                        card_html += f'<div class="src-pred-explain">{_esc(str(consensus))}</div>'
                    card_html += '</div>'
                    cards.append(card_html)
        elif isinstance(fed, str):
            available_sources.append("Fed rate outlook")
            cards.append(
                f'<div class="src-pred-card">'
                f'<div class="src-pred-label">Fed Rate</div>'
                f'<div class="src-pred-value" style="color:#3b82f6;">{_esc(fed)}</div>'
                f'</div>'
            )

        # Recession probability (handle both old and new format)
        recession = pred.get("recession")
        if isinstance(recession, dict):
            prob = recession.get("probability_2026") or recession.get("probability") or recession.get("consensus")
            rec_source = recession.get("source", "")
            if prob is not None:
                available_sources.append("recession risk")
                if isinstance(prob, (int, float)) and float(prob) <= 1:
                    pct_val = int(float(prob) * 100)
                    prob_display = f"{pct_val}%"
                    bar_w = pct_val
                    # Data-driven explanation
                    if pct_val > 50:
                        explain = f"At {pct_val}%, markets see recession as more likely than not — risk-off positioning may be warranted"
                    elif pct_val > 25:
                        explain = f"At {pct_val}%, recession risk is elevated but not the base case — monitor leading indicators"
                    else:
                        explain = f"At {pct_val}%, markets see low recession probability — supportive of risk assets"
                else:
                    prob_display = str(prob)
                    explain = ""
                    bar_w = 0
                rec_color = "#EF4444" if bar_w > 50 else "#F59E0B" if bar_w > 25 else "#10B981"
                source_label = f" ({_esc(rec_source)})" if rec_source else ""
                card_html = (
                    f'<div class="src-pred-card">'
                    f'<div class="src-pred-label">Recession Risk{source_label}</div>'
                    f'<div class="src-pred-value" style="color:{rec_color};">{_esc(prob_display)}</div>'
                )
                if bar_w > 0:
                    card_html += (
                        f'<div class="src-pred-bar">'
                        f'<div class="src-pred-bar-fill" style="width:{bar_w}%;background:{rec_color};"></div>'
                        f'</div>'
                    )
                if explain:
                    card_html += f'<div class="src-pred-explain">{_esc(explain)}</div>'
                card_html += '</div>'
                cards.append(card_html)

        # Inflation (handle both old and new format)
        inflation = pred.get("inflation")
        if isinstance(inflation, dict):
            cpi_prob = inflation.get("cpi_above_3pct")
            inf_source = inflation.get("source", "")
            expectation = inflation.get("expectation") or inflation.get("consensus")

            if cpi_prob is not None:
                available_sources.append("inflation expectations")
                pct_val = int(float(cpi_prob) * 100)
                inf_color = "#EF4444" if pct_val > 50 else "#F59E0B" if pct_val > 25 else "#10B981"
                if pct_val > 50:
                    explain = f"{pct_val}% probability of CPI above 3% — persistent inflation may delay rate cuts"
                else:
                    explain = f"{pct_val}% probability of CPI above 3% — disinflation trend likely intact"
                source_label = f" ({_esc(inf_source)})" if inf_source else ""
                cards.append(
                    f'<div class="src-pred-card">'
                    f'<div class="src-pred-label">Inflation &gt;3%{source_label}</div>'
                    f'<div class="src-pred-value" style="color:{inf_color};">{pct_val}%</div>'
                    f'<div class="src-pred-bar">'
                    f'<div class="src-pred-bar-fill" style="width:{pct_val}%;background:{inf_color};"></div>'
                    f'</div>'
                    f'<div class="src-pred-explain">{_esc(explain)}</div>'
                    f'</div>'
                )
            elif expectation is not None:
                available_sources.append("inflation expectations")
                exp_str = str(expectation)
                explain = f"Market expects inflation around {exp_str}"
                cards.append(
                    f'<div class="src-pred-card">'
                    f'<div class="src-pred-label">Inflation</div>'
                    f'<div class="src-pred-value" style="color:#F59E0B;">{_esc(exp_str)}</div>'
                    f'<div class="src-pred-explain">{_esc(explain)}</div>'
                    f'</div>'
                )

        # GDP outlook
        gdp = pred.get("gdp")
        if isinstance(gdp, dict):
            q1_prob = gdp.get("q1_positive")
            gdp_source = gdp.get("source", "")
            if q1_prob is not None:
                available_sources.append("GDP outlook")
                pct_val = int(float(q1_prob) * 100)
                gdp_color = "#10B981" if pct_val > 70 else "#F59E0B" if pct_val > 40 else "#EF4444"
                if pct_val > 70:
                    explain = f"{pct_val}% chance of positive Q1 GDP — strong growth expectations support equities"
                elif pct_val > 40:
                    explain = f"{pct_val}% chance of positive Q1 GDP — growth outlook uncertain"
                else:
                    explain = f"Only {pct_val}% chance of positive Q1 GDP — contraction fears elevated"
                source_label = f" ({_esc(gdp_source)})" if gdp_source else ""
                cards.append(
                    f'<div class="src-pred-card">'
                    f'<div class="src-pred-label">Q1 GDP Growth{source_label}</div>'
                    f'<div class="src-pred-value" style="color:{gdp_color};">{pct_val}%</div>'
                    f'<div class="src-pred-bar">'
                    f'<div class="src-pred-bar-fill" style="width:{pct_val}%;background:{gdp_color};"></div>'
                    f'</div>'
                    f'<div class="src-pred-explain">{_esc(explain)}</div>'
                    f'</div>'
                )

        # S&P 500 targets
        sp500 = pred.get("sp500")
        if isinstance(sp500, dict):
            targets = sp500.get("targets", [])
            sp_source = sp500.get("source", "")
            if targets and isinstance(targets, list):
                available_sources.append("S&P 500 targets")
                targets_html = ""
                for t in targets:
                    if isinstance(t, dict):
                        level = t.get("level", 0)
                        t_prob = t.get("probability", 0)
                        targets_html += (
                            f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:3px 10px;'
                            f'border:1px solid rgba(255,255,255,0.1);border-radius:6px;font-size:0.85em;">'
                            f'<strong>{int(level):,}</strong> '
                            f'<span style="opacity:0.7;">({int(float(t_prob)*100)}%)</span>'
                            f'</span>'
                        )
                source_label = f" ({_esc(sp_source)})" if sp_source else ""
                cards.append(
                    f'<div class="src-pred-card">'
                    f'<div class="src-pred-label">S&amp;P 500 Targets{source_label}</div>'
                    f'<div style="margin-top:4px;">{targets_html}</div>'
                    f'</div>'
                )

        if cards:
            grid_html = "".join(cards)
            # Data sparsity note
            all_possible = ["Fed rate probabilities", "recession risk", "inflation expectations", "GDP outlook", "S&P 500 targets"]
            missing = [s for s in all_possible if s not in available_sources]
            sparsity_note = ""
            if missing and len(missing) < len(all_possible):
                sparsity_note = (
                    f'<div class="src-source-label" style="opacity:0.6;font-style:italic;">'
                    f'Limited data — missing: {_esc(", ".join(missing))}'
                    f'</div>'
                )
            sections.append(
                f'<div class="src-section">'
                f'<div class="src-section-title">Prediction Markets</div>'
                f'<div class="src-pred-grid">{grid_html}</div>'
                f'<div class="src-source-label">Kalshi / Polymarket</div>'
                f'{sparsity_note}'
                f'</div>'
            )

    # --- Reddit Sentiment ---
    if sent and isinstance(sent, dict):
        mood_data = sent.get("market_mood") or sent
        overall_mood = (
            mood_data.get("overall_mood")
            or mood_data.get("mood")
            or sent.get("overall_mood")
        )
        per_symbol = sent.get("per_symbol", [])
        trending = sent.get("trending", [])

        # Build data-driven explanation
        mood_explain_parts: list[str] = []

        if overall_mood:
            mood_str = str(overall_mood).lower()
            if "bull" in mood_str or "positive" in mood_str or "optimistic" in mood_str:
                mood_color = "#10B981"
            elif "bear" in mood_str or "negative" in mood_str or "pessimistic" in mood_str:
                mood_color = "#EF4444"
            else:
                mood_color = "#F59E0B"

            # Per-symbol data summary
            if per_symbol and isinstance(per_symbol, list):
                total_posts = sum(int(s.get("post_count", 0)) for s in per_symbol if isinstance(s, dict))
                bullish_syms = [s.get("symbol", "?") for s in per_symbol if isinstance(s, dict) and float(s.get("sentiment_score", 0)) > 0.2]
                bearish_syms = [s.get("symbol", "?") for s in per_symbol if isinstance(s, dict) and float(s.get("sentiment_score", 0)) < -0.2]
                mood_explain_parts.append(f"{total_posts} posts analyzed across {len(per_symbol)} symbols")
                if bullish_syms:
                    mood_explain_parts.append(f"Bullish on: {', '.join(bullish_syms)}")
                if bearish_syms:
                    mood_explain_parts.append(f"Bearish on: {', '.join(bearish_syms)}")
            elif "bull" in mood_str:
                mood_explain_parts.append("Social sentiment skews bullish across monitored subreddits")
            elif "bear" in mood_str:
                mood_explain_parts.append("Social sentiment skews bearish across monitored subreddits")
            else:
                mood_explain_parts.append("Mixed opinions across trading communities — no strong directional bias")

            # Trending summary
            if trending and isinstance(trending, list):
                total_mentions = sum(int(item.get("mentions", 0)) for item in trending if isinstance(item, dict))
                mood_explain_parts.append(f"{total_mentions} total mentions across {len(trending)} trending tickers")

            # Divergence callout: sentiment vs technicals
            if ta and isinstance(ta, dict):
                bd = ta.get("breakdown") or {}
                trend_val = float(bd.get("trend", 0))
                if "bull" in mood_str and trend_val < -0.2:
                    mood_explain_parts.append(
                        "Note: Reddit sentiment is bullish but technical trend is negative "
                        "— retail traders may be lagging a deteriorating setup"
                    )
                elif "bear" in mood_str and trend_val > 0.2:
                    mood_explain_parts.append(
                        "Note: Reddit sentiment is bearish despite positive technical trend "
                        "— contrarian signal worth monitoring"
                    )

            mood_explain = ". ".join(mood_explain_parts) + "." if mood_explain_parts else ""

            sent_html = (
                f'<div class="src-section">'
                f'<div class="src-section-title">Reddit Sentiment</div>'
                f'<div class="src-sent-mood">'
                f'<span class="src-sent-dot" style="background:{mood_color};box-shadow:0 0 6px {mood_color};"></span>'
                f'<span style="color:{mood_color};">{_esc(str(overall_mood).title())}</span>'
                f'</div>'
            )
            if mood_explain:
                sent_html += f'<div class="src-sent-explain">{_esc(mood_explain)}</div>'

            # Mention count for this insight's primary symbol with rank
            symbol = ins.primary_symbol
            if symbol and trending:
                # Sort by mentions to find rank
                sorted_trending = sorted(
                    [item for item in trending if isinstance(item, dict)],
                    key=lambda x: int(x.get("mentions", 0)),
                    reverse=True,
                )
                for rank, item in enumerate(sorted_trending, 1):
                    ticker = item.get("ticker", item.get("symbol", "")).upper()
                    if ticker == symbol.upper():
                        mentions = item.get("mentions") or item.get("count")
                        upvotes = item.get("upvotes")
                        if mentions is not None:
                            rank_text = f", ranked #{rank} trending" if len(sorted_trending) > 1 else ""
                            upvote_text = f", {upvotes} upvotes" if upvotes else ""
                            sent_html += (
                                f'<div class="src-sent-mentions">'
                                f'{_esc(symbol)}: {mentions} mentions{upvote_text}{rank_text}'
                                f'</div>'
                            )
                        break

            # Per-symbol sentiment bars
            if per_symbol and isinstance(per_symbol, list):
                sym_items_html = ""
                for sym_data in per_symbol[:6]:
                    if not isinstance(sym_data, dict):
                        continue
                    sym_name = sym_data.get("symbol", "?")
                    score = float(sym_data.get("sentiment_score", 0))
                    post_count = int(sym_data.get("post_count", 0))
                    bull_count = sym_data.get("bullish_count")
                    bear_count = sym_data.get("bearish_count")
                    bar_pct = min(int(abs(score) * 100), 100)
                    bar_color = "#10B981" if score >= 0.3 else "#EF4444" if score <= -0.3 else "#94a3b8"
                    label = "Bullish" if score >= 0.3 else "Bearish" if score <= -0.3 else "Neutral"

                    detail_text = f"{post_count} posts"
                    if bull_count is not None and bear_count is not None:
                        detail_text += f" ({bull_count} bull / {bear_count} bear)"

                    sym_items_html += (
                        f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;font-size:0.8em;">'
                        f'<span style="font-family:monospace;font-weight:600;width:50px;">{_esc(sym_name)}</span>'
                        f'<div style="flex:1;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;">'
                        f'<div style="height:100%;width:{bar_pct}%;background:{bar_color};border-radius:3px;"></div>'
                        f'</div>'
                        f'<span style="color:{bar_color};font-size:0.9em;width:50px;text-align:right;">{label}</span>'
                        f'<span style="opacity:0.6;font-size:0.85em;">{detail_text}</span>'
                        f'</div>'
                    )
                if sym_items_html:
                    sent_html += (
                        f'<div style="margin-top:8px;">'
                        f'<div style="font-size:0.75em;opacity:0.7;margin-bottom:4px;">Sentiment by Symbol</div>'
                        f'{sym_items_html}'
                        f'</div>'
                    )

            # Trending tickers as chips
            if trending:
                tickers_html = ""
                for item in trending[:8]:
                    if isinstance(item, dict):
                        sym = item.get("ticker", item.get("symbol", ""))
                        mentions = item.get("mentions")
                        if sym:
                            mention_text = f" ({mentions})" if mentions else ""
                            tickers_html += f'<span class="src-sent-ticker">{_esc(sym)}{mention_text}</span>'
                    elif isinstance(item, str):
                        tickers_html += f'<span class="src-sent-ticker">{_esc(item)}</span>'
                if tickers_html:
                    sent_html += f'<div class="src-sent-tickers">{tickers_html}</div>'

            sent_html += (
                '<div class="src-source-label">'
                'r/wallstreetbets, r/stocks, r/investing. '
                'Sentiment can lag institutional positioning by hours to days.'
                '</div>'
            )
            sent_html += '</div>'
            sections.append(sent_html)
        elif not overall_mood and not trending and not per_symbol:
            sections.append(
                '<div class="src-section">'
                '<div class="src-section-title">Reddit Sentiment</div>'
                '<div class="src-sent-explain" style="font-style:italic;opacity:0.7;">'
                'No sentiment data available — social media monitoring did not return data for this analysis period.'
                '</div>'
                '</div>'
            )

    if not sections:
        return ""

    content = "".join(sections)
    return (
        f'<div class="analysis-sources">'
        f'<button class="sources-toggle" onclick="this.parentElement.classList.toggle(\'open\')">'
        f'&#128202; Analysis Sources <span class="toggle-chevron">&#9660;</span>'
        f'</button>'
        f'<div class="sources-content">{content}</div>'
        f'</div>'
    )


def _build_insight_card(ins: DeepInsight, index: int) -> str:
    """Build a single interactive insight card with colored left border."""
    action = ins.action or "WATCH"
    color = _ACTION_COLORS.get(action, "#6366F1")
    bg = _ACTION_BG.get(action, "rgba(99,102,241,0.10)")
    glow = _ACTION_GLOW.get(action, "none")
    label = _ACTION_LABELS.get(action, action)
    border_color = _ACTION_BORDER_COLORS.get(action, "#6366F1")
    confidence = ins.confidence or 0
    confidence_pct = int(confidence * 100)
    conf_color = _confidence_color(confidence)

    # Symbols
    symbols_html = ""
    if ins.primary_symbol:
        symbols_html += (
            f'<span class="symbol-tag primary">{_esc(ins.primary_symbol)}</span>'
        )
    if ins.related_symbols:
        for sym in ins.related_symbols[:5]:
            symbols_html += (
                f'<span class="symbol-tag">{_esc(sym)}</span>'
            )

    # Expandable details
    details_parts: list[str] = []

    # Trading levels (show at top of expanded area)
    if ins.entry_zone or ins.target_price or ins.stop_loss:
        levels_html = '<div class="trading-levels">'
        if ins.entry_zone:
            levels_html += (
                f'<div class="level-box">'
                f'<div class="level-label">Entry Zone</div>'
                f'<div class="level-value">{_esc(ins.entry_zone)}</div>'
                f'</div>'
            )
        if ins.target_price:
            levels_html += (
                f'<div class="level-box">'
                f'<div class="level-label">Target</div>'
                f'<div class="level-value" style="color:#10B981;">{_esc(ins.target_price)}</div>'
                f'</div>'
            )
        if ins.stop_loss:
            levels_html += (
                f'<div class="level-box">'
                f'<div class="level-label">Stop Loss</div>'
                f'<div class="level-value" style="color:#EF4444;">{_esc(ins.stop_loss)}</div>'
                f'</div>'
            )
        levels_html += '</div>'
        details_parts.append(levels_html)

    # Full thesis (rendered with markdown) + layman explanation
    if ins.thesis:
        thesis_layman = generate_layman_explanation("synthesis", ins.thesis)
        layman_div = ""
        if thesis_layman:
            layman_div = (
                f'<div class="layman-explanation">{_esc(thesis_layman)}</div>'
            )
        details_parts.append(
            f'<div class="detail-section">'
            f'<div class="detail-label">Analysis</div>'
            f'<div class="detail-content">{_markdown_to_html(ins.thesis)}</div>'
            f'{layman_div}'
            f'</div>'
        )

    # Dedicated analyst sections from supporting evidence
    if ins.supporting_evidence:
        # Group evidence by analyst type
        analyst_groups: dict[str, list[dict]] = {}
        ungrouped: list[str] = []
        for ev in ins.supporting_evidence[:10]:
            if isinstance(ev, dict):
                analyst = ev.get("analyst", "unknown")
                if analyst not in analyst_groups:
                    analyst_groups[analyst] = []
                analyst_groups[analyst].append(ev)
            elif isinstance(ev, str):
                ungrouped.append(ev)

        # Render each analyst group as a color-coded card
        for analyst_key, findings in analyst_groups.items():
            a_color = _ANALYST_COLORS.get(analyst_key, "#6366F1")
            a_icon = _ANALYST_ICONS.get(analyst_key, "&#9679;")
            a_name = _ANALYST_DISPLAY_NAMES.get(analyst_key, analyst_key.replace("_", " ").title())

            findings_html = ""
            for ev in findings:
                finding_text = ev.get("finding", ev.get("summary", str(ev)))
                conf = ev.get("confidence")
                conf_html = ""
                if conf is not None:
                    conf_pct = int(float(conf) * 100)
                    conf_bar_color = _confidence_color(float(conf))
                    conf_html = (
                        f'<div class="analyst-conf-bar">'
                        f'<div class="analyst-conf-track">'
                        f'<div class="analyst-conf-fill" style="width:{conf_pct}%;background:{conf_bar_color};"></div>'
                        f'</div>'
                        f'<span class="analyst-conf-val" style="color:{conf_bar_color};">{conf_pct}%</span>'
                        f'</div>'
                    )
                # Generate layman explanation for this finding
                finding_layman = generate_layman_explanation(analyst_key, str(finding_text))
                layman_html = ""
                if finding_layman:
                    layman_html = (
                        f'<div class="layman-explanation">{_esc(finding_layman)}</div>'
                    )
                findings_html += (
                    f'<div class="analyst-finding">'
                    f'<div class="analyst-finding-text">{_esc(str(finding_text))}</div>'
                    f'{layman_html}'
                    f'{conf_html}'
                    f'</div>'
                )

            details_parts.append(
                f'<div class="analyst-section" style="border-left:3px solid {a_color};">'
                f'<div class="analyst-section-header">'
                f'<span class="analyst-badge" style="background:{a_color}18;color:{a_color};border:1px solid {a_color}33;">'
                f'{a_icon} {_esc(a_name)}'
                f'</span>'
                f'</div>'
                f'{findings_html}'
                f'</div>'
            )

        # Render any ungrouped string evidence
        if ungrouped:
            ungrouped_items = "".join(
                f'<li>{_esc(ev)}</li>' for ev in ungrouped
            )
            details_parts.append(
                f'<div class="detail-section">'
                f'<div class="detail-label">Additional Factors</div>'
                f'<ul class="detail-list">{ungrouped_items}</ul>'
                f'</div>'
            )

    # Risk factors
    if ins.risk_factors:
        risk_items = "".join(
            f'<li>{_esc(r)}</li>' for r in ins.risk_factors[:6]
        )
        details_parts.append(
            f'<div class="risk-box">'
            f'<div class="detail-label" style="color:#F59E0B;">Risk Factors</div>'
            f'<ul class="detail-list">{risk_items}</ul>'
            f'</div>'
        )

    # Invalidation trigger
    if ins.invalidation_trigger:
        details_parts.append(
            f'<div class="invalidation-box">'
            f'<strong>Invalidation:</strong> {_esc(ins.invalidation_trigger)}'
            f'</div>'
        )

    # Timeframe
    timeframe_html = ""
    horizon = ins.time_horizon or ins.timeframe
    if horizon:
        timeframe_html = (
            f'<span class="timeframe-badge">{_esc(horizon)}</span>'
        )

    details_html = "".join(details_parts)

    # Collapsible analysis sources (TA, predictions, sentiment)
    sources_html = _build_analysis_sources_html(ins)

    return f"""
    <div class="insight-card" data-index="{index}" data-action="{_esc(action)}"
         data-confidence="{confidence}"
         style="border-left:4px solid {border_color};">
      <div class="insight-header" onclick="toggleInsight({index})">
        <div class="insight-top-row">
          <div class="insight-badges">
            <span class="action-badge" style="background:{bg};color:{color};box-shadow:{glow};">
              {_esc(label)}
            </span>
            {symbols_html}
            {timeframe_html}
          </div>
          <div class="confidence-bar-inline">
            <div class="confidence-bar-track">
              <div class="confidence-bar-fill" style="width:{confidence_pct}%;background:{conf_color};"></div>
            </div>
            <span class="confidence-bar-label" style="color:{conf_color};">{confidence_pct}%</span>
          </div>
        </div>
        <h3 class="insight-title">{_esc(ins.title)}</h3>
        <p class="insight-thesis-preview">{_esc((ins.thesis or '')[:180])}{'...' if ins.thesis and len(ins.thesis) > 180 else ''}</p>
        <div class="expand-indicator">
          <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </div>
      </div>
      <div class="insight-details" id="details-{index}">
        {details_html}
        {sources_html}
      </div>
    </div>
"""


def _build_report_html(task: AnalysisTask, insights: list[DeepInsight]) -> str:
    """Build an interactive dashboard HTML report.

    Features: slim header bar, KPI row, executive briefing with markdown,
    two-column sectors/phases grid, insight cards with colored borders,
    filter/sort toolbar, staggered animations, and visual polish.
    """
    # Format dates
    report_date = ""
    report_date_short = ""
    if task.completed_at:
        report_date = task.completed_at.strftime("%B %d, %Y at %H:%M UTC")
        report_date_short = task.completed_at.strftime("%B %d, %Y")
    elif task.started_at:
        report_date = task.started_at.strftime("%B %d, %Y at %H:%M UTC")
        report_date_short = task.started_at.strftime("%B %d, %Y")

    # Market regime
    regime = task.market_regime or "Unknown"
    r_color = _regime_color(regime)

    # --- KPI metrics ---
    num_insights = len(insights)
    duration_str = _format_duration(task.elapsed_seconds)

    # Action breakdown for top action KPI
    action_counts: Counter[str] = Counter()
    for ins in insights:
        act = ins.action or "WATCH"
        action_counts[act] += 1
    top_action = action_counts.most_common(1)[0] if action_counts else ("--", 0)
    top_action_label = _ACTION_LABELS.get(top_action[0], top_action[0])
    top_action_color = _ACTION_COLORS.get(top_action[0], "#6366F1")

    # --- Confidence distribution for chart ---
    conf_high = sum(1 for ins in insights if (ins.confidence or 0) >= 0.8)
    conf_med = sum(1 for ins in insights if 0.6 <= (ins.confidence or 0) < 0.8)
    conf_low = sum(1 for ins in insights if (ins.confidence or 0) < 0.6)
    conf_dist_json = json.dumps([conf_high, conf_med, conf_low])

    # --- Action breakdown for chart ---
    action_chart_labels = []
    action_chart_values = []
    action_chart_colors = []
    for act_key in ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL", "WATCH"]:
        cnt = action_counts.get(act_key, 0)
        if cnt > 0:
            action_chart_labels.append(_ACTION_LABELS.get(act_key, act_key))
            action_chart_values.append(cnt)
            action_chart_colors.append(_ACTION_COLORS.get(act_key, "#6366F1"))
    action_labels_json = json.dumps(action_chart_labels)
    action_values_json = json.dumps(action_chart_values)
    action_colors_json = json.dumps(action_chart_colors)

    # --- Sectors ---
    # Use task.top_sectors if available; otherwise fall back to parsing the
    # executive summary so that historical reports also show sector data.
    effective_sectors = task.top_sectors or []
    if not effective_sectors:
        effective_sectors = _extract_sectors_from_summary(task.discovery_summary)
    sectors_card_html = _build_sector_bars(effective_sectors)

    # --- Phases ---
    phases_html = _build_phase_timeline(
        task.phases_completed or [],
        phase_summaries=task.phase_summaries,
    )

    # --- TL;DR action box ---
    tldr_html = _build_tldr_section(insights, regime, effective_sectors)

    # --- Executive summary (rendered markdown) ---
    summary_html = ""
    briefing_body = _markdown_to_html(task.discovery_summary) if task.discovery_summary else ""
    if tldr_html or briefing_body:
        summary_html = f"""
    <section class="card summary-card">
      <div class="card-label">Executive Briefing</div>
      {tldr_html}
      <div class="summary-text">{briefing_body}</div>
    </section>
"""

    # --- Collect all symbols ---
    all_insight_symbols: set[str] = set()
    for ins in insights:
        if ins.primary_symbol:
            all_insight_symbols.add(ins.primary_symbol)
        if ins.related_symbols:
            for s in ins.related_symbols:
                all_insight_symbols.add(s)

    # --- Insight cards ---
    cards_html = ""
    if insights:
        cards_html = "".join(
            _build_insight_card(ins, i) for i, ins in enumerate(insights)
        )
    else:
        cards_html = (
            '<div class="empty-state">No insights generated for this report.</div>'
        )

    # Insight data JSON for JavaScript
    insight_data_json = _build_insight_data_json(insights)

    # Collect unique actions for filter bar
    unique_actions = sorted(set(ins.action or "WATCH" for ins in insights))
    filter_buttons = '<button class="filter-btn active" data-action="ALL" onclick="filterInsights(\'ALL\')">All</button>'
    for act in unique_actions:
        act_color = _ACTION_COLORS.get(act, "#6366F1")
        act_label = _ACTION_LABELS.get(act, act)
        filter_buttons += (
            f'<button class="filter-btn" data-action="{_esc(act)}" '
            f'onclick="filterInsights(\'{_esc(act)}\')" '
            f'style="--btn-color:{act_color};">{_esc(act_label)}</button>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Teletraan Intelligence &mdash; {_esc(report_date_short)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/apexcharts@3.45.1/dist/apexcharts.min.js"></script>
<style>
/* === RESET & BASE === */
*, *::before, *::after {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 0;
  background: #0B0F19;
  background-image: radial-gradient(ellipse at 50% 0%, rgba(99,102,241,0.08) 0%, transparent 60%);
  color: #CBD5E1;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  line-height: 1.6;
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}}

/* === HEADER BAR (slim, fixed) === */
.header-bar {{
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(11,15,25,0.92);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(255,255,255,0.06);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.header-bar-brand {{
  font-size: 15px;
  font-weight: 800;
  background: linear-gradient(135deg, #6366F1, #8B5CF6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.3px;
}}
.header-bar-right {{
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 13px;
  color: #64748B;
}}
.header-bar-regime {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 12px;
  border-radius: 20px;
  font-weight: 700;
  font-size: 12px;
}}

.container {{
  max-width: 1080px;
  margin: 0 auto;
  padding: 32px 24px 60px;
}}

/* === KPI ROW === */
.kpi-row {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 28px;
}}
.kpi-card {{
  background: rgba(255,255,255,0.03);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 14px;
  padding: 20px;
  text-align: center;
  transition: all 0.25s ease;
}}
.kpi-card:hover {{
  background: rgba(255,255,255,0.05);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.2);
}}
.kpi-label {{
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #64748B;
  margin-bottom: 8px;
}}
.kpi-value {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 28px;
  font-weight: 700;
  color: #F1F5F9;
  line-height: 1.2;
}}
.kpi-sub {{
  font-size: 12px;
  color: #475569;
  margin-top: 4px;
}}

/* === CARDS (glassmorphism) === */
.card {{
  background: rgba(255,255,255,0.03);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 20px;
}}
.card-label {{
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #6366F1;
  margin-bottom: 12px;
}}

/* === SUMMARY / EXECUTIVE BRIEFING === */
.summary-card {{
  margin-bottom: 28px;
}}
.summary-text {{
  font-size: 15px;
  line-height: 1.8;
  color: #CBD5E1;
}}
.summary-text .md-heading {{
  font-size: 16px;
  font-weight: 700;
  color: #E2E8F0;
  margin: 20px 0 8px 0;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}}
.summary-text .md-para {{
  margin: 8px 0;
}}
.summary-text .md-list {{
  margin: 8px 0;
  padding-left: 20px;
  color: #CBD5E1;
  line-height: 1.8;
}}
.summary-text .md-list li {{
  margin-bottom: 4px;
}}
.summary-text .md-kv {{
  margin: 4px 0;
  font-size: 14px;
}}
.summary-text .md-kv-key {{
  font-weight: 700;
  color: #A5B4FC;
}}
.summary-text .md-kv-value {{
  color: #E2E8F0;
}}
.summary-text strong {{ color: #F1F5F9; }}
.summary-text .num-positive {{
  color: #10B981;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}}
.summary-text .num-negative {{
  color: #EF4444;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}}

/* === TL;DR ACTION BOX === */
.tldr-box {{
  margin-bottom: 24px;
  padding: 20px 24px;
  background: rgba(245,158,11,0.05);
  border: 1px solid rgba(245,158,11,0.18);
  border-left: 4px solid #F59E0B;
  border-radius: 12px;
  position: relative;
}}
.tldr-header {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}}
.tldr-icon {{
  font-size: 22px;
  line-height: 1;
}}
.tldr-title {{
  font-size: 17px;
  font-weight: 700;
  color: #F59E0B;
  letter-spacing: -0.2px;
}}
.tldr-list {{
  margin: 0;
  padding-left: 20px;
  list-style: none;
}}
.tldr-list li {{
  position: relative;
  padding-left: 8px;
  margin-bottom: 10px;
  font-size: 15px;
  line-height: 1.7;
  color: #E2E8F0;
}}
.tldr-list li::before {{
  content: "→";
  position: absolute;
  left: -18px;
  color: #F59E0B;
  font-weight: 700;
}}
.tldr-list li strong {{
  color: #FCD34D;
}}
.tldr-list li:last-child {{
  margin-bottom: 0;
}}

/* === TWO-COL GRID === */
.two-col {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 28px;
}}

/* === SECTOR BARS === */
.sector-bars {{
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.sector-bars-subtitle {{
  font-size: 12px;
  color: #8888aa;
  margin-bottom: 4px;
  line-height: 1.4;
}}
.sector-bar-row {{
  display: flex;
  align-items: center;
  gap: 12px;
}}
.sector-bar-name {{
  font-size: 13px;
  font-weight: 600;
  color: #94A3B8;
  min-width: 90px;
  flex-shrink: 0;
}}
.sector-bar-track {{
  flex: 1;
  height: 8px;
  background: rgba(255,255,255,0.06);
  border-radius: 4px;
  position: relative;
}}
.sector-bar-zero {{
  position: absolute;
  left: 50%;
  top: -3px;
  bottom: -3px;
  width: 1px;
  background: rgba(255,255,255,0.25);
  border-left: 1px dashed rgba(255,255,255,0.25);
  z-index: 2;
}}
.sector-bar-fill {{
  position: absolute;
  top: 0;
  height: 100%;
  transition: width 0.6s ease;
}}
.sector-bar-val {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
  min-width: 56px;
  text-align: right;
}}
.sector-bar-axis {{
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 2px;
}}
.sector-bar-axis-track {{
  flex: 1;
  position: relative;
  height: 14px;
}}
.sector-bar-axis-label {{
  position: absolute;
  top: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #64748B;
}}
.num-positive {{ color: #10B981; }}
.num-negative {{ color: #EF4444; }}

/* === PHASE ACCORDION === */
.phase-timeline-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}}
.phase-count-badge {{
  font-size: 12px;
  font-weight: 600;
  color: #10B981;
  background: rgba(16,185,129,0.12);
  padding: 4px 10px;
  border-radius: 20px;
  font-family: 'JetBrains Mono', monospace;
}}
.phase-expand-all-btn {{
  font-size: 12px;
  color: #64748B;
  background: none;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  padding: 4px 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}}
.phase-expand-all-btn:hover {{
  color: #CBD5E1;
  border-color: rgba(255,255,255,0.16);
  background: rgba(255,255,255,0.04);
}}
.phase-accordion-list {{
  display: flex;
  flex-direction: column;
  gap: 6px;
}}
.phase-accordion {{
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.2s ease;
}}
.phase-accordion:hover {{
  border-color: rgba(255,255,255,0.12);
}}
.phase-accordion.open {{
  border-color: rgba(16,185,129,0.25);
}}
.phase-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 12px 14px;
  background: rgba(255,255,255,0.02);
  border: none;
  cursor: pointer;
  transition: background 0.2s ease;
  text-align: left;
  color: inherit;
  font-family: inherit;
}}
.phase-header:hover {{
  background: rgba(255,255,255,0.04);
}}
.phase-header-left {{
  display: flex;
  align-items: center;
  gap: 10px;
}}
.phase-step-num {{
  font-size: 11px;
  font-weight: 700;
  color: #475569;
  background: rgba(255,255,255,0.06);
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'JetBrains Mono', monospace;
  flex-shrink: 0;
}}
.phase-accordion.open .phase-step-num {{
  background: rgba(16,185,129,0.15);
  color: #10B981;
}}
.phase-icon {{
  font-size: 16px;
  line-height: 1;
}}
.phase-name {{
  font-size: 14px;
  font-weight: 600;
  color: #E2E8F0;
}}
.phase-header-right {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.phase-status-badge {{
  font-size: 11px;
  font-weight: 600;
  color: #10B981;
  background: rgba(16,185,129,0.10);
  padding: 2px 8px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}}
.phase-chevron {{
  color: #475569;
  transition: transform 0.25s ease;
  flex-shrink: 0;
}}
.phase-accordion.open .phase-chevron {{
  transform: rotate(180deg);
  color: #10B981;
}}
.phase-content {{
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.3s ease, padding 0.3s ease;
  padding: 0 14px;
}}
.phase-accordion.open .phase-content {{
  max-height: 200px;
  padding: 0 14px 14px;
}}
.phase-desc {{
  font-size: 13px;
  color: #94A3B8;
  line-height: 1.6;
  margin: 0;
  padding-top: 4px;
  border-top: 1px solid rgba(255,255,255,0.04);
}}

/* === DIVIDER === */
.section-divider {{
  height: 1px;
  background: rgba(255,255,255,0.06);
  margin: 8px 0 28px;
}}

/* === FILTER BAR === */
.insights-toolbar {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}}
.filter-bar {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}}
.filter-btn {{
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  color: #94A3B8;
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: inherit;
}}
.filter-btn:hover {{
  background: rgba(255,255,255,0.08);
  color: #E2E8F0;
}}
.filter-btn.active {{
  background: rgba(99,102,241,0.15);
  border-color: rgba(99,102,241,0.3);
  color: #A5B4FC;
}}
.sort-btn {{
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  color: #64748B;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 4px;
}}
.sort-btn:hover {{
  color: #E2E8F0;
  background: rgba(255,255,255,0.08);
}}
.sort-btn.active {{
  color: #A5B4FC;
  border-color: rgba(99,102,241,0.3);
}}

/* === INSIGHT CARDS === */
.insight-card {{
  background: rgba(255,255,255,0.03);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  margin-bottom: 16px;
  overflow: hidden;
  transition: all 0.25s ease;
}}
.insight-card:hover {{
  border-color: rgba(255,255,255,0.10);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}}
.insight-card.expanded {{
  border-color: rgba(99,102,241,0.20);
  background: rgba(255,255,255,0.04);
  transform: none;
  box-shadow: 0 4px 32px rgba(99,102,241,0.08);
}}
.insight-header {{
  padding: 20px 24px 16px;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
}}
.insight-top-row {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}}
.insight-badges {{
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}}
.action-badge {{
  display: inline-block;
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}
.symbol-tag {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  color: #94A3B8;
  background: rgba(255,255,255,0.05);
  padding: 3px 8px;
  border-radius: 6px;
}}
.symbol-tag.primary {{
  color: #E2E8F0;
  background: rgba(255,255,255,0.08);
  font-size: 13px;
}}
.timeframe-badge {{
  font-size: 11px;
  color: #64748B;
  background: rgba(255,255,255,0.04);
  padding: 3px 10px;
  border-radius: 6px;
  font-weight: 500;
}}

/* Confidence progress bar (inline in insight cards) */
.confidence-bar-inline {{
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 100px;
}}
.confidence-bar-track {{
  flex: 1;
  height: 6px;
  background: rgba(255,255,255,0.08);
  border-radius: 3px;
  overflow: hidden;
  min-width: 60px;
}}
.confidence-bar-fill {{
  height: 100%;
  border-radius: 3px;
  transition: width 0.6s ease;
}}
.confidence-bar-label {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 700;
}}

/* Layman explanation text */
.layman-explanation {{
  font-style: italic;
  color: #94A3B8;
  font-size: 13px;
  margin-top: 8px;
  padding-left: 12px;
  border-left: 2px solid rgba(255,255,255,0.1);
  line-height: 1.6;
}}

/* Analyst section cards (per-analyst evidence) */
.analyst-section {{
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 12px;
}}
.analyst-section:last-child {{
  margin-bottom: 0;
}}
.analyst-section-header {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}}
.analyst-badge {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}
.analyst-finding {{
  margin-bottom: 10px;
}}
.analyst-finding:last-child {{
  margin-bottom: 0;
}}
.analyst-finding-text {{
  font-size: 14px;
  line-height: 1.7;
  color: #CBD5E1;
}}
.analyst-conf-bar {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}}
.analyst-conf-track {{
  flex: 1;
  max-width: 120px;
  height: 6px;
  background: rgba(255,255,255,0.08);
  border-radius: 3px;
  overflow: hidden;
}}
.analyst-conf-fill {{
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}}
.analyst-conf-val {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 600;
}}

/* Charts row */
.charts-row {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 28px;
}}
.chart-container {{
  min-height: 220px;
}}

.insight-title {{
  margin: 0 0 6px 0;
  font-size: 17px;
  font-weight: 700;
  color: #F1F5F9;
  line-height: 1.4;
}}
.insight-thesis-preview {{
  margin: 0;
  font-size: 14px;
  color: #94A3B8;
  line-height: 1.6;
}}
.expand-indicator {{
  text-align: center;
  padding-top: 8px;
}}
.chevron {{
  width: 20px;
  height: 20px;
  color: #475569;
  transition: transform 0.3s ease;
}}
.insight-card.expanded .chevron {{
  transform: rotate(180deg);
}}

/* Expanded details */
.insight-details {{
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.4s ease, padding 0.3s ease;
  padding: 0 24px;
}}
.insight-card.expanded .insight-details {{
  max-height: 3000px;
  padding: 0 24px 24px;
}}
.detail-section {{
  margin-bottom: 16px;
}}
.detail-label {{
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: #6366F1;
  margin-bottom: 8px;
}}
.detail-content {{
  font-size: 14px;
  line-height: 1.7;
  color: #CBD5E1;
}}
.detail-content strong {{ color: #F1F5F9; }}
.detail-content .md-heading {{
  font-size: 15px;
  font-weight: 700;
  color: #E2E8F0;
  margin: 16px 0 8px 0;
}}
.detail-content .md-para {{
  margin: 8px 0;
}}
.detail-content .md-list {{
  margin: 8px 0;
  padding-left: 20px;
  line-height: 1.8;
}}
.detail-content .md-list li {{
  margin-bottom: 4px;
}}
.detail-content .md-kv {{
  margin: 4px 0;
}}
.detail-content .md-kv-key {{
  font-weight: 700;
  color: #A5B4FC;
}}
.detail-content .md-kv-value {{
  color: #E2E8F0;
}}
.detail-content .num-positive {{
  color: #10B981;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}}
.detail-content .num-negative {{
  color: #EF4444;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}}
.detail-list {{
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: #94A3B8;
  line-height: 1.8;
}}
.detail-list li {{ margin-bottom: 4px; }}
.detail-list strong {{ color: #CBD5E1; }}

/* Trading levels */
.trading-levels {{
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin: 0 0 16px 0;
}}
.level-box {{
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 10px;
  padding: 10px 16px;
  min-width: 100px;
}}
.level-label {{
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #64748B;
  margin-bottom: 2px;
}}
.level-value {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  font-weight: 600;
  color: #E2E8F0;
}}

/* Risk box */
.risk-box {{
  background: rgba(245,158,11,0.06);
  border: 1px solid rgba(245,158,11,0.12);
  border-radius: 10px;
  padding: 16px;
  margin: 16px 0;
}}
.risk-box .detail-list {{
  color: #FCD34D;
}}

/* Invalidation */
.invalidation-box {{
  background: rgba(239,68,68,0.06);
  border-left: 3px solid #EF4444;
  border-radius: 0 10px 10px 0;
  padding: 12px 16px;
  margin: 16px 0;
  font-size: 13px;
  color: #FCA5A5;
}}
.invalidation-box strong {{ color: #F87171; }}

/* === SECTION TITLE === */
.section-title {{
  font-size: 20px;
  font-weight: 700;
  color: #F1F5F9;
  margin: 0 0 4px 0;
}}
.section-subtitle {{
  font-size: 13px;
  color: #64748B;
  margin: 0 0 20px 0;
}}

/* === EMPTY STATE === */
.empty-state {{
  text-align: center;
  padding: 60px 24px;
  color: #475569;
  font-size: 15px;
}}

/* === FOOTER === */
.report-footer {{
  margin-top: 48px;
  padding-top: 24px;
  border-top: 1px solid rgba(255,255,255,0.06);
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
}}
.report-footer p {{
  margin: 0;
  color: #334155;
  font-size: 13px;
}}
.report-footer strong {{
  color: #475569;
}}
.report-footer a {{
  color: #6366F1;
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
}}
.report-footer a:hover {{
  text-decoration: underline;
}}

/* === RESPONSIVE === */
@media (max-width: 768px) {{
  .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
  .charts-row {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 640px) {{
  .container {{ padding: 20px 16px 40px; }}
  .header-bar {{ padding: 10px 16px; flex-wrap: wrap; gap: 8px; }}
  .kpi-row {{ grid-template-columns: 1fr 1fr; gap: 12px; }}
  .kpi-value {{ font-size: 22px; }}
  .two-col {{ grid-template-columns: 1fr; }}
  .charts-row {{ grid-template-columns: 1fr; }}
  .insight-header {{ padding: 16px; }}
  .insight-details {{ padding: 0 16px; }}
  .insight-card.expanded .insight-details {{ padding: 0 16px 16px; }}
  .insights-toolbar {{ flex-direction: column; align-items: flex-start; }}
  .trading-levels {{ flex-direction: column; }}
  .src-pred-grid {{ grid-template-columns: 1fr; }}
  .src-breakdown-row {{ grid-template-columns: 70px 1fr 44px; gap: 6px; }}
  .src-key-levels {{ flex-direction: column; gap: 8px; }}
}}

/* === ANIMATIONS === */
@keyframes fadeInUp {{
  from {{ opacity: 0; transform: translateY(16px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
.kpi-card {{
  animation: fadeInUp 0.4s ease both;
}}
.kpi-card:nth-child(2) {{ animation-delay: 0.05s; }}
.kpi-card:nth-child(3) {{ animation-delay: 0.1s; }}
.kpi-card:nth-child(4) {{ animation-delay: 0.15s; }}
.insight-card {{
  animation: fadeInUp 0.4s ease both;
}}
.insight-card:nth-child(2) {{ animation-delay: 0.05s; }}
.insight-card:nth-child(3) {{ animation-delay: 0.1s; }}
.insight-card:nth-child(4) {{ animation-delay: 0.15s; }}
.insight-card:nth-child(5) {{ animation-delay: 0.2s; }}
.insight-card:nth-child(6) {{ animation-delay: 0.25s; }}
.insight-card:nth-child(7) {{ animation-delay: 0.3s; }}
.insight-card:nth-child(8) {{ animation-delay: 0.35s; }}

/* === TOOLTIP ON CARD TITLES === */
.card-title-tooltip {{
  position: relative;
  cursor: help;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}}
.card-title-tooltip .tooltip-icon {{
  display: inline-block;
  width: 14px;
  height: 14px;
  line-height: 14px;
  text-align: center;
  font-size: 10px;
  font-weight: 700;
  color: #64748B;
  border: 1px solid #475569;
  border-radius: 50%;
  flex-shrink: 0;
  transition: color 0.2s ease, border-color 0.2s ease;
}}
.card-title-tooltip:hover .tooltip-icon {{
  color: #A5B4FC;
  border-color: #6366F1;
}}
.card-title-tooltip .tooltip-text {{
  visibility: hidden;
  opacity: 0;
  position: absolute;
  left: 50%;
  transform: translateX(-50%) translateY(4px);
  top: 100%;
  z-index: 200;
  width: 280px;
  padding: 10px 14px;
  background: #1a1a2e;
  color: #CBD5E1;
  font-size: 12px;
  font-weight: 400;
  line-height: 1.6;
  letter-spacing: 0;
  text-transform: none;
  border: 1px solid rgba(99,102,241,0.2);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  pointer-events: none;
  transition: opacity 0.25s ease, transform 0.25s ease, visibility 0.25s ease;
}}
.card-title-tooltip:hover .tooltip-text {{
  visibility: visible;
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}}

/* === ANALYSIS SOURCES SECTION === */
.analysis-sources {{
  margin-top: 16px;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  overflow: hidden;
  background: rgba(255,255,255,0.02);
}}
.sources-toggle {{
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 12px 16px;
  background: rgba(255,255,255,0.04);
  border: none;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}}
.sources-toggle:hover {{
  background: rgba(255,255,255,0.08);
}}
.toggle-chevron {{
  margin-left: auto;
  transition: transform 0.3s;
  font-size: 10px;
}}
.analysis-sources.open .toggle-chevron {{
  transform: rotate(180deg);
}}
.sources-content {{
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.4s ease, padding 0.3s;
  padding: 0 16px;
}}
.analysis-sources.open .sources-content {{
  max-height: 800px;
  padding: 16px;
}}
.src-section {{
  padding: 14px;
  margin-bottom: 12px;
  background: rgba(255,255,255,0.03);
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.06);
}}
.src-section:last-child {{
  margin-bottom: 0;
}}
.src-section-title {{
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: #64748b;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}}

/* Technical Analysis */
.src-ta-header {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}}
.src-ta-score {{
  font-size: 22px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}}
.src-ta-rating {{
  font-size: 14px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 6px;
  background: rgba(255,255,255,0.08);
}}
.src-ta-conf {{
  font-size: 12px;
  color: #94a3b8;
}}
.src-ta-explain {{
  font-size: 12px;
  color: #94a3b8;
  font-style: italic;
  margin-bottom: 12px;
  line-height: 1.5;
}}
.src-breakdown {{
  display: grid;
  gap: 8px;
}}
.src-breakdown-row {{
  display: grid;
  grid-template-columns: 90px 1fr 50px;
  align-items: center;
  gap: 10px;
}}
.src-breakdown-label {{
  font-size: 12px;
  color: #94a3b8;
  text-transform: capitalize;
}}
.src-breakdown-track {{
  height: 8px;
  background: rgba(255,255,255,0.06);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}}
.src-breakdown-center {{
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255,255,255,0.15);
}}
.src-breakdown-fill {{
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}}
.src-breakdown-val {{
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  text-align: right;
}}
.src-breakdown-meaning {{
  font-size: 11px;
  color: #64748b;
  grid-column: 1 / -1;
  margin-top: -4px;
}}
.src-key-levels {{
  display: flex;
  gap: 16px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,0.06);
  flex-wrap: wrap;
}}
.src-level {{
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}}
.src-level-label {{
  color: #64748b;
}}
.src-level-val {{
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}}

/* Prediction Markets */
.src-pred-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}}
.src-pred-card {{
  padding: 10px 12px;
  background: rgba(255,255,255,0.03);
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,0.05);
}}
.src-pred-label {{
  font-size: 11px;
  color: #64748b;
  margin-bottom: 4px;
}}
.src-pred-value {{
  font-size: 18px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}}
.src-pred-bar {{
  height: 4px;
  background: rgba(255,255,255,0.06);
  border-radius: 2px;
  margin-top: 6px;
  overflow: hidden;
}}
.src-pred-bar-fill {{
  height: 100%;
  border-radius: 2px;
  background: #3b82f6;
}}
.src-pred-explain {{
  font-size: 11px;
  color: #94a3b8;
  font-style: italic;
  margin-top: 4px;
}}
.src-source-label {{
  font-size: 11px;
  color: #64748b;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid rgba(255,255,255,0.05);
}}

/* Sentiment */
.src-sent-mood {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}}
.src-sent-dot {{
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}}
.src-sent-explain {{
  font-size: 12px;
  color: #94a3b8;
  font-style: italic;
  margin-bottom: 10px;
}}
.src-sent-tickers {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}
.src-sent-ticker {{
  font-size: 11px;
  padding: 3px 8px;
  background: rgba(255,255,255,0.06);
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
}}
.src-sent-mentions {{
  font-size: 12px;
  color: #cbd5e1;
  margin-bottom: 4px;
}}
</style>
</head>
<body>

<!-- HEADER BAR (slim, fixed) -->
<div class="header-bar">
  <div class="header-bar-brand">Teletraan Intelligence</div>
  <div class="header-bar-right">
    <span>{_esc(report_date)}</span>
    <span class="header-bar-regime" style="background:rgba(255,255,255,0.04);color:{r_color};border:1px solid {r_color}33;">
      <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{r_color};box-shadow:0 0 6px {r_color};"></span>
      {_esc(regime)}
    </span>
  </div>
</div>

<div class="container">

  <!-- KPI ROW -->
  <div class="kpi-row">
    <div class="kpi-card">
      <div class="kpi-label">Insights</div>
      <div class="kpi-value">{num_insights}</div>
      <div class="kpi-sub">finding{"s" if num_insights != 1 else ""}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label"><span class="card-title-tooltip">Regime<span class="tooltip-icon">?</span><span class="tooltip-text">Market regime indicates the current overall market behavior pattern (Bullish, Bearish, Transitional, or Volatile). It&#39;s determined by analyzing macro indicators, sector rotation, and price trends across the market.</span></span></div>
      <div class="kpi-value" style="font-size:20px;color:{r_color};">{_esc(regime)}</div>
      <div class="kpi-sub" style="margin-top:6px;">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{r_color};box-shadow:0 0 6px {r_color};vertical-align:middle;"></span>
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Duration</div>
      <div class="kpi-value" style="font-size:22px;">{_esc(duration_str)}</div>
      <div class="kpi-sub">analysis time</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Top Action</div>
      <div class="kpi-value" style="font-size:20px;color:{top_action_color};">{_esc(top_action_label)}</div>
      <div class="kpi-sub" style="font-family:'JetBrains Mono',monospace;">({top_action[1]})</div>
    </div>
  </div>

  <!-- CHARTS ROW -->
  <div class="charts-row">
    <div class="card">
      <div class="card-label"><span class="card-title-tooltip">Confidence Distribution<span class="tooltip-icon">?</span><span class="tooltip-text">Shows how analysis confidence is distributed across insights. Higher confidence (80-100%) means stronger supporting data. The bands are: Low (0-40%), Medium-Low (40-60%), Medium (60-80%), and High (80-100%).</span></span></div>
      <div class="chart-container" id="chart-confidence"></div>
    </div>
    <div class="card">
      <div class="card-label">Action Breakdown</div>
      <div class="chart-container" id="chart-actions"></div>
    </div>
  </div>

  <!-- EXECUTIVE BRIEFING -->
  {summary_html}

  <!-- SECTORS -->
  <div style="margin-bottom:20px;">
    <div class="card">
      <div class="card-label">Sectors</div>
      {sectors_card_html}
    </div>
  </div>

  <!-- ANALYSIS PIPELINE -->
  <div style="margin-bottom:28px;">
    <div class="card">
      <div class="card-label">Analysis Pipeline</div>
      {phases_html}
    </div>
  </div>

  <div class="section-divider"></div>

  <!-- ACTIONABLE INSIGHTS -->
  <div>
    <h2 class="section-title">Actionable Insights</h2>
    <p class="section-subtitle">Click any insight to expand full analysis, risks, and trading levels.</p>

    <div class="insights-toolbar">
      <div class="filter-bar">
        {filter_buttons}
      </div>
      <button class="sort-btn" onclick="toggleSort()" id="sort-btn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <polyline points="19 12 12 19 5 12"></polyline>
        </svg>
        Sort by confidence
      </button>
    </div>

    <div id="insights-container">
      {cards_html}
    </div>
  </div>

  <!-- FOOTER -->
  <footer class="report-footer">
    <p>Generated by <strong>Teletraan Intelligence</strong> &middot; {_esc(report_date)}</p>
    <a href="../index.html">All Reports</a>
  </footer>

</div>

<script>
(function() {{
  // Phase accordion toggle
  window.togglePhase = function(btn) {{
    var accordion = btn.closest('.phase-accordion');
    accordion.classList.toggle('open');
    var isOpen = accordion.classList.contains('open');
    btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  }};

  // Expand / collapse all phases
  window.toggleAllPhases = function() {{
    var accordions = document.querySelectorAll('.phase-accordion');
    var btn = document.querySelector('.phase-expand-all-btn');
    var anyOpen = Array.from(accordions).some(function(a) {{ return a.classList.contains('open'); }});
    accordions.forEach(function(a) {{
      if (anyOpen) {{
        a.classList.remove('open');
        a.querySelector('.phase-header').setAttribute('aria-expanded', 'false');
      }} else {{
        a.classList.add('open');
        a.querySelector('.phase-header').setAttribute('aria-expanded', 'true');
      }}
    }});
    btn.textContent = anyOpen ? 'Expand All' : 'Collapse All';
  }};
}})();
</script>

<script>
(function() {{
  // Insight data for filtering/sorting
  var insightData = {insight_data_json};
  var currentFilter = 'ALL';
  var sortDescending = false;

  // Toggle expand/collapse
  window.toggleInsight = function(index) {{
    var card = document.querySelector('.insight-card[data-index="' + index + '"]');
    if (card) {{
      card.classList.toggle('expanded');
    }}
  }};

  // Filter insights by action
  window.filterInsights = function(action) {{
    currentFilter = action;
    document.querySelectorAll('.filter-btn').forEach(function(btn) {{
      btn.classList.toggle('active', btn.getAttribute('data-action') === action);
    }});
    applyFiltersAndSort();
  }};

  // Toggle sort by confidence
  window.toggleSort = function() {{
    sortDescending = !sortDescending;
    var btn = document.getElementById('sort-btn');
    btn.classList.toggle('active', sortDescending);
    applyFiltersAndSort();
  }};

  function applyFiltersAndSort() {{
    var container = document.getElementById('insights-container');
    var cards = Array.from(container.querySelectorAll('.insight-card'));
    var order = insightData.slice();
    if (currentFilter !== 'ALL') {{
      order = order.filter(function(d) {{ return d.action === currentFilter; }});
    }}
    if (sortDescending) {{
      order.sort(function(a, b) {{ return b.confidence - a.confidence; }});
    }}
    var visibleIndices = new Set(order.map(function(d) {{ return d.index; }}));
    cards.forEach(function(card) {{
      var idx = parseInt(card.getAttribute('data-index'));
      card.style.display = visibleIndices.has(idx) ? '' : 'none';
    }});
    if (sortDescending) {{
      order.forEach(function(d) {{
        var card = container.querySelector('.insight-card[data-index="' + d.index + '"]');
        if (card) container.appendChild(card);
      }});
    }}
  }}

  // === ApexCharts === //
  var darkTheme = {{
    mode: 'dark',
    palette: 'palette1',
    monochrome: {{ enabled: false }}
  }};

  // Confidence Distribution (radialBar)
  var confDist = {conf_dist_json};
  var confTotal = confDist[0] + confDist[1] + confDist[2];
  if (confTotal > 0) {{
    var confPcts = confDist.map(function(v) {{ return Math.round(v / confTotal * 100); }});
    var confHoveredIdx = -1;
    new ApexCharts(document.querySelector('#chart-confidence'), {{
      chart: {{ type: 'radialBar', height: 220, background: 'transparent' }},
      theme: darkTheme,
      plotOptions: {{
        radialBar: {{
          hollow: {{ size: '30%' }},
          track: {{ background: 'rgba(255,255,255,0.06)' }},
          dataLabels: {{
            name: {{ fontSize: '12px', color: '#94A3B8', offsetY: -4,
                     formatter: function(seriesName, opts) {{ confHoveredIdx = opts && opts.seriesIndex != null ? opts.seriesIndex : -1; return seriesName; }} }},
            value: {{ fontSize: '14px', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600,
                      formatter: function(val) {{ var count = confHoveredIdx >= 0 && confHoveredIdx < confDist.length ? confDist[confHoveredIdx] : confTotal; return count + ' insight' + (count !== 1 ? 's' : ''); }} }}
          }}
        }}
      }},
      series: confPcts,
      labels: ['High (>80%)', 'Medium (60-80%)', 'Low (<60%)'],
      colors: ['#10B981', '#F59E0B', '#EF4444'],
      stroke: {{ lineCap: 'round' }}
    }}).render();
  }} else {{
    document.querySelector('#chart-confidence').innerHTML =
      '<div style="color:#475569;text-align:center;padding:40px 0;font-size:14px;">No confidence data</div>';
  }}

  // Action Breakdown (donut)
  var actionLabels = {action_labels_json};
  var actionValues = {action_values_json};
  var actionColors = {action_colors_json};
  if (actionValues.length > 0) {{
    new ApexCharts(document.querySelector('#chart-actions'), {{
      chart: {{ type: 'donut', height: 220, background: 'transparent' }},
      theme: darkTheme,
      series: actionValues,
      labels: actionLabels,
      colors: actionColors,
      plotOptions: {{
        pie: {{
          donut: {{
            size: '60%',
            labels: {{
              show: true,
              total: {{
                show: true,
                label: 'Total',
                fontSize: '13px',
                fontFamily: 'JetBrains Mono, monospace',
                fontWeight: 600,
                color: '#94A3B8',
                formatter: function(w) {{ return w.globals.seriesTotals.reduce(function(a,b){{ return a+b; }}, 0); }}
              }},
              value: {{
                fontSize: '20px',
                fontFamily: 'JetBrains Mono, monospace',
                fontWeight: 700,
                color: '#F1F5F9'
              }}
            }}
          }}
        }}
      }},
      dataLabels: {{ enabled: false }},
      legend: {{
        position: 'bottom',
        fontSize: '12px',
        fontFamily: 'Inter, sans-serif',
        fontWeight: 600,
        labels: {{ colors: '#94A3B8' }},
        markers: {{ radius: 3 }}
      }},
      stroke: {{ width: 2, colors: ['#0B0F19'] }}
    }}).render();
  }} else {{
    document.querySelector('#chart-actions').innerHTML =
      '<div style="color:#475569;text-align:center;padding:40px 0;font-size:14px;">No action data</div>';
  }}

}})();
</script>

</body>
</html>"""
