"""Reports API routes — read-only views over AnalysisTask + DeepInsight data."""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

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

    Format: ``{date}-{regime}.html``  (e.g. ``2026-02-10-transitional.html``)
    """
    if task.created_at:
        date_str = task.created_at.strftime("%Y-%m-%d")
    elif task.started_at:
        date_str = task.started_at.strftime("%Y-%m-%d")
    else:
        date_str = "undated"

    regime = _sanitize_regime(task.market_regime)
    return f"{date_str}-{regime}.html"


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
    """Generate a beautiful dark-themed index page with report cards.

    Parses filenames in ``{date}-{regime}.html`` format to extract metadata
    and renders a responsive card grid.
    """
    cards = ""
    for fname in report_files:
        stem = fname.replace(".html", "")
        # Try to parse date-regime format
        parts = stem.split("-", 3)
        if len(parts) >= 4:
            # date is first 3 parts (YYYY-MM-DD), regime is the rest
            date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
            regime_raw = parts[3]
        elif len(parts) == 3:
            # Could be just a date or old UUID style
            date_str = stem
            regime_raw = ""
        else:
            date_str = stem
            regime_raw = ""

        # Format date nicely
        display_date = date_str
        try:
            from datetime import datetime
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            display_date = dt.strftime("%B %d, %Y")
        except (ValueError, ImportError):
            pass

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

        cards += f"""
        <a href="reports/{fname}" class="report-card">
          <div class="card-date">{_esc(display_date)}</div>
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
    color: #E2E8F0;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.6;
    min-height: 100vh;
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
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 20px;
  }}
  .report-card {{
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 24px;
    background: rgba(255,255,255,0.03);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 16px;
    text-decoration: none;
    color: inherit;
    transition: all 0.25s ease;
  }}
  .report-card:hover {{
    background: rgba(255,255,255,0.06);
    border-color: rgba(99,102,241,0.3);
    transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(99,102,241,0.1);
  }}
  .card-date {{
    font-size: 20px;
    font-weight: 700;
    color: #F1F5F9;
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
  @media (max-width: 640px) {{
    .container {{ padding: 24px 16px; }}
    .header h1 {{ font-size: 28px; }}
    .card-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Teletraan Intelligence</h1>
    <p>Published market analysis reports</p>
  </div>

  <div class="card-grid">
    {cards if cards else '<div class="empty-state">No reports published yet.</div>'}
  </div>

  <div class="footer">
    <p>Generated by <strong>Teletraan</strong></p>
  </div>
</div>
</body>
</html>"""


def _do_publish(task: AnalysisTask, html_content: str, repo_dir: str) -> str:
    """Synchronous helper that publishes an HTML report to the gh-pages branch.

    Uses human-readable filename ``{date}-{regime}.html`` derived from the
    AnalysisTask metadata.  Runs inside ``run_in_executor`` so it does not
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
    ``gh-pages`` branch under ``reports/{date}-{regime}.html``.  An index
    page listing all published reports is maintained automatically.

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
# HTML report builder — Obsidian Intelligence theme
# ---------------------------------------------------------------------------

_ACTION_COLORS = {
    "STRONG_BUY": "#22c55e",
    "BUY": "#10B981",
    "HOLD": "#F59E0B",
    "SELL": "#EF4444",
    "STRONG_SELL": "#DC2626",
    "WATCH": "#6366F1",
}

_ACTION_BG = {
    "STRONG_BUY": "rgba(34,197,94,0.12)",
    "BUY": "rgba(16,185,129,0.10)",
    "HOLD": "rgba(245,158,11,0.10)",
    "SELL": "rgba(239,68,68,0.10)",
    "STRONG_SELL": "rgba(220,38,38,0.12)",
    "WATCH": "rgba(99,102,241,0.10)",
}

_ACTION_GLOW = {
    "STRONG_BUY": "0 0 12px rgba(34,197,94,0.4)",
    "STRONG_SELL": "0 0 12px rgba(220,38,38,0.4)",
}

_ACTION_LABELS = {
    "STRONG_BUY": "Strong Buy",
    "BUY": "Buy",
    "HOLD": "Hold",
    "SELL": "Sell",
    "STRONG_SELL": "Strong Sell",
    "WATCH": "Watch",
}


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


def _format_text_with_markup(text: str) -> str:
    """Minimal markdown-like formatting for analysis text.

    Handles **bold**, bullet lists (lines starting with - or *), and paragraphs.
    """
    if not text:
        return ""
    # Escape HTML first
    escaped = _esc(text)
    # Bold
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    # Process lines
    lines = escaped.split("\n")
    result_parts: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                result_parts.append('<ul style="margin:8px 0;padding-left:20px;color:#CBD5E1;">')
                in_list = True
            result_parts.append(f"<li>{stripped[2:]}</li>")
        else:
            if in_list:
                result_parts.append("</ul>")
                in_list = False
            if stripped:
                result_parts.append(f"<p style='margin:8px 0;'>{stripped}</p>")
    if in_list:
        result_parts.append("</ul>")
    return "".join(result_parts)


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


def _build_insight_card(ins: DeepInsight, index: int) -> str:
    """Build a single interactive insight card with collapsible details."""
    action = ins.action or "WATCH"
    color = _ACTION_COLORS.get(action, "#6366F1")
    bg = _ACTION_BG.get(action, "rgba(99,102,241,0.10)")
    glow = _ACTION_GLOW.get(action, "none")
    label = _ACTION_LABELS.get(action, action)
    confidence = ins.confidence or 0
    confidence_pct = int(confidence * 100)
    conf_color = _confidence_color(confidence)

    # Symbols
    symbols_html = ""
    all_symbols: list[str] = []
    if ins.primary_symbol:
        all_symbols.append(ins.primary_symbol)
        symbols_html += (
            f'<span class="symbol-tag primary">{_esc(ins.primary_symbol)}</span>'
        )
    if ins.related_symbols:
        for sym in ins.related_symbols[:5]:
            all_symbols.append(sym)
            symbols_html += (
                f'<span class="symbol-tag">{_esc(sym)}</span>'
            )

    # Expandable details
    details_parts: list[str] = []

    # Full thesis
    if ins.thesis:
        details_parts.append(
            f'<div class="detail-section">'
            f'<div class="detail-label">Analysis</div>'
            f'<div class="detail-content">{_format_text_with_markup(ins.thesis)}</div>'
            f'</div>'
        )

    # Key factors from supporting evidence
    if ins.supporting_evidence:
        evidence_items = ""
        for ev in ins.supporting_evidence[:6]:
            if isinstance(ev, dict):
                analyst = ev.get("analyst", "")
                finding = ev.get("finding", ev.get("summary", str(ev)))
                evidence_items += (
                    f'<li><strong style="color:#A5B4FC;">{_esc(str(analyst))}</strong>: '
                    f'{_esc(str(finding))}</li>'
                )
            elif isinstance(ev, str):
                evidence_items += f"<li>{_esc(ev)}</li>"
        if evidence_items:
            details_parts.append(
                f'<div class="detail-section">'
                f'<div class="detail-label">Key Factors</div>'
                f'<ul class="detail-list">{evidence_items}</ul>'
                f'</div>'
            )

    # Trading levels
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

    return f"""
    <div class="insight-card" data-index="{index}" data-action="{_esc(action)}"
         data-confidence="{confidence}">
      <div class="insight-header" onclick="toggleInsight({index})">
        <div class="insight-top-row">
          <div class="insight-badges">
            <span class="action-badge" style="background:{bg};color:{color};box-shadow:{glow};">
              {_esc(label)}
            </span>
            {symbols_html}
            {timeframe_html}
          </div>
          <div class="confidence-gauge">
            <div class="gauge-bar">
              <div class="gauge-fill" style="width:{confidence_pct}%;background:{conf_color};"></div>
            </div>
            <span class="gauge-label" style="color:{conf_color};">{confidence_pct}%</span>
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
      </div>
    </div>
"""


def _build_phase_timeline(phases: list[str]) -> str:
    """Build an animated phase timeline / stepper."""
    if not phases:
        return '<div style="color:#475569;font-size:14px;">No phase data available.</div>'

    items = ""
    for i, phase in enumerate(phases):
        is_last = i == len(phases) - 1
        connector = "" if is_last else '<div class="timeline-connector"></div>'
        items += f"""
        <div class="timeline-item">
          <div class="timeline-dot"></div>
          {connector}
          <div class="timeline-label">{_esc(phase)}</div>
        </div>
"""
    return f'<div class="timeline">{items}</div>'


def _build_report_html(task: AnalysisTask, insights: list[DeepInsight]) -> str:
    """Build a stunning interactive dashboard HTML report.

    Obsidian Intelligence theme with collapsible insight cards,
    action filters, confidence sort, and phase timeline.
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
    regime_lower = regime.lower()
    if "bull" in regime_lower or "expansion" in regime_lower or "risk-on" in regime_lower:
        regime_color = "#10B981"
    elif "bear" in regime_lower or "contraction" in regime_lower or "risk-off" in regime_lower:
        regime_color = "#EF4444"
    elif "neutral" in regime_lower or "mixed" in regime_lower or "transitional" in regime_lower:
        regime_color = "#F59E0B"
    else:
        regime_color = "#6366F1"

    # Sectors
    sectors_html = ""
    if task.top_sectors:
        sector_badges = "".join(
            f'<span class="sector-badge">{_esc(s)}</span>'
            for s in task.top_sectors
        )
        sectors_html = f'<div class="sector-row">{sector_badges}</div>'

    # Executive summary
    summary_html = ""
    if task.discovery_summary:
        summary_html = f"""
    <section class="card summary-card">
      <div class="card-label">Executive Summary</div>
      <div class="summary-text">{_format_text_with_markup(task.discovery_summary)}</div>
    </section>
"""

    # Regime card + Phases card
    phases_html = _build_phase_timeline(task.phases_completed or [])

    # Portfolio impact — collect all symbols from insights
    all_insight_symbols: set[str] = set()
    for ins in insights:
        if ins.primary_symbol:
            all_insight_symbols.add(ins.primary_symbol)
        if ins.related_symbols:
            for s in ins.related_symbols:
                all_insight_symbols.add(s)

    # Insight cards
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

    num_insights = len(insights)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Teletraan Intelligence &mdash; {_esc(report_date_short)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
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

.container {{
  max-width: 960px;
  margin: 0 auto;
  padding: 40px 24px 60px;
}}

/* === HEADER === */
.report-header {{
  text-align: center;
  padding-bottom: 32px;
  margin-bottom: 32px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}}
.brand {{
  margin: 0 0 4px 0;
  font-size: 14px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 3px;
  color: #6366F1;
}}
.report-header h1 {{
  margin: 0 0 16px 0;
  font-size: 32px;
  font-weight: 800;
  color: #F1F5F9;
  letter-spacing: -0.5px;
}}
.header-meta {{
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 12px;
}}
.header-date {{
  color: #64748B;
  font-size: 14px;
}}
.regime-badge-lg {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 16px;
  border-radius: 24px;
  font-size: 14px;
  font-weight: 700;
}}
.meta-stat {{
  color: #475569;
  font-size: 13px;
  font-family: 'JetBrains Mono', monospace;
}}
.sector-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 16px;
}}
.sector-badge {{
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  padding: 4px 14px;
  border-radius: 20px;
  font-size: 13px;
  color: #94A3B8;
  font-weight: 500;
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

/* === SUMMARY === */
.summary-card {{
  margin-bottom: 24px;
}}
.summary-text {{
  font-size: 15px;
  line-height: 1.8;
  color: #CBD5E1;
}}
.summary-text p {{ margin: 8px 0; }}
.summary-text strong {{ color: #F1F5F9; }}

/* === TWO-COL GRID === */
.two-col {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}}
@media (max-width: 640px) {{
  .two-col {{ grid-template-columns: 1fr; }}
}}

/* === REGIME CARD === */
.regime-display {{
  text-align: center;
  padding: 16px 0;
}}
.regime-big {{
  font-size: 28px;
  font-weight: 800;
  margin-bottom: 4px;
}}

/* === PHASE TIMELINE === */
.timeline {{
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 4px 0;
}}
.timeline-item {{
  display: flex;
  align-items: flex-start;
  gap: 12px;
  position: relative;
  padding-bottom: 12px;
}}
.timeline-dot {{
  width: 10px;
  height: 10px;
  min-width: 10px;
  border-radius: 50%;
  background: #10B981;
  margin-top: 5px;
  box-shadow: 0 0 8px rgba(16,185,129,0.4);
  position: relative;
  z-index: 1;
}}
.timeline-connector {{
  position: absolute;
  left: 4px;
  top: 15px;
  bottom: 0;
  width: 2px;
  background: linear-gradient(to bottom, rgba(16,185,129,0.4), rgba(16,185,129,0.1));
}}
.timeline-label {{
  font-size: 13px;
  color: #94A3B8;
  font-weight: 500;
  line-height: 1.5;
}}

/* === PORTFOLIO IMPACT === */
.portfolio-card {{
  margin-bottom: 24px;
}}
.portfolio-symbols {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}}
.portfolio-symbol {{
  background: rgba(99,102,241,0.10);
  color: #A5B4FC;
  border: 1px solid rgba(99,102,241,0.20);
  padding: 4px 12px;
  border-radius: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
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
}}
.insight-card.expanded {{
  border-color: rgba(99,102,241,0.20);
  background: rgba(255,255,255,0.04);
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

/* Confidence gauge */
.confidence-gauge {{
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 120px;
}}
.gauge-bar {{
  flex: 1;
  height: 6px;
  background: rgba(255,255,255,0.06);
  border-radius: 3px;
  overflow: hidden;
  min-width: 60px;
}}
.gauge-fill {{
  height: 100%;
  border-radius: 3px;
  transition: width 0.6s ease;
}}
.gauge-label {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  font-weight: 600;
  min-width: 36px;
  text-align: right;
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
  max-height: 2000px;
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
  margin: 16px 0;
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
}}
.report-footer p {{
  margin: 0;
  color: #334155;
  font-size: 13px;
}}
.report-footer strong {{
  color: #475569;
}}

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

/* === RESPONSIVE === */
@media (max-width: 640px) {{
  .container {{ padding: 24px 16px 40px; }}
  .report-header h1 {{ font-size: 24px; }}
  .header-meta {{ gap: 8px; }}
  .insight-header {{ padding: 16px; }}
  .insight-details {{ padding: 0 16px; }}
  .insight-card.expanded .insight-details {{ padding: 0 16px 16px; }}
  .insights-toolbar {{ flex-direction: column; align-items: flex-start; }}
  .confidence-gauge {{ min-width: 100px; }}
  .trading-levels {{ flex-direction: column; }}
}}

/* === ANIMATIONS === */
@keyframes fadeInUp {{
  from {{ opacity: 0; transform: translateY(16px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
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
</style>
</head>
<body>

<div class="container">

  <!-- HEADER -->
  <header class="report-header">
    <div class="brand">Teletraan Intelligence</div>
    <h1>Market Analysis Report</h1>
    <div class="header-meta">
      <span class="header-date">{_esc(report_date)}</span>
      <span class="regime-badge-lg" style="background:rgba(255,255,255,0.04);color:{regime_color};border:1px solid {regime_color}33;">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{regime_color};box-shadow:0 0 6px {regime_color};"></span>
        {_esc(regime)}
      </span>
      <span class="meta-stat">{num_insights} insight{"s" if num_insights != 1 else ""}</span>
      <span class="meta-stat">{_format_duration(task.elapsed_seconds)}</span>
    </div>
    {sectors_html}
  </header>

  <!-- EXECUTIVE SUMMARY -->
  {summary_html}

  <!-- REGIME + PHASES -->
  <div class="two-col">
    <div class="card">
      <div class="card-label">Market Regime</div>
      <div class="regime-display">
        <div class="regime-big" style="color:{regime_color};">{_esc(regime)}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-label">Phases Completed</div>
      {phases_html}
    </div>
  </div>

  <!-- PORTFOLIO IMPACT (all mentioned symbols) -->
  {"" if not all_insight_symbols else f'''
  <div class="card portfolio-card">
    <div class="card-label">Symbols Covered</div>
    <div class="portfolio-symbols">
      {"".join(f'<span class="portfolio-symbol">{_esc(s)}</span>' for s in sorted(all_insight_symbols))}
    </div>
  </div>
  '''}

  <!-- INSIGHTS -->
  <div>
    <h2 class="section-title">Insights</h2>
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
  </footer>

</div>

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
    // Update active button
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

    // Build order array
    var order = insightData.slice();

    // Filter
    if (currentFilter !== 'ALL') {{
      order = order.filter(function(d) {{ return d.action === currentFilter; }});
    }}

    // Sort
    if (sortDescending) {{
      order.sort(function(a, b) {{ return b.confidence - a.confidence; }});
    }}

    var visibleIndices = new Set(order.map(function(d) {{ return d.index; }}));

    // Reorder DOM and show/hide
    // First hide all
    cards.forEach(function(card) {{
      var idx = parseInt(card.getAttribute('data-index'));
      if (visibleIndices.has(idx)) {{
        card.style.display = '';
      }} else {{
        card.style.display = 'none';
      }}
    }});

    // Reorder visible cards
    if (sortDescending) {{
      order.forEach(function(d) {{
        var card = container.querySelector('.insight-card[data-index="' + d.index + '"]');
        if (card) container.appendChild(card);
      }});
    }}
  }}
}})();
</script>

</body>
</html>"""
