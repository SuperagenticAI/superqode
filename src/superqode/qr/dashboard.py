"""
QR Web Dashboard - Interactive local viewer for Quality Reports.

Provides a web-based interface for viewing QR findings with:
- Severity filtering
- Interactive findings table
- Verified fixes visualization
- Trend charts from historical QRs
"""

from __future__ import annotations

import http.server
import json
import socketserver
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# HTML template with dark theme matching SuperQode TUI
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SuperQode QR Dashboard</title>
    <style>
        :root {
            --bg-primary: #0a0a0a;
            --bg-secondary: #1a1a1a;
            --bg-tertiary: #2a2a2a;
            --text-primary: #e4e4e7;
            --text-secondary: #a1a1aa;
            --text-muted: #71717a;
            --purple: #a855f7;
            --pink: #ec4899;
            --orange: #f97316;
            --cyan: #06b6d4;
            --green: #22c55e;
            --yellow: #fbbf24;
            --red: #ef4444;
            --blue: #3b82f6;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }

        /* Header */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--bg-tertiary);
        }

        .logo {
            font-size: 1.5rem;
            font-weight: bold;
            background: linear-gradient(90deg, var(--purple), var(--pink), var(--orange));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .meta {
            text-align: right;
            color: var(--text-secondary);
            font-size: 0.875rem;
        }

        /* Verdict Banner */
        .verdict {
            padding: 1.5rem;
            border-radius: 0.5rem;
            margin-bottom: 2rem;
            text-align: center;
        }

        .verdict.pass {
            background: linear-gradient(135deg, rgba(34, 197, 94, 0.2), rgba(34, 197, 94, 0.05));
            border: 1px solid var(--green);
        }

        .verdict.conditional {
            background: linear-gradient(135deg, rgba(251, 191, 36, 0.2), rgba(251, 191, 36, 0.05));
            border: 1px solid var(--yellow);
        }

        .verdict.fail {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(239, 68, 68, 0.05));
            border: 1px solid var(--red);
        }

        .verdict.blocked {
            background: linear-gradient(135deg, rgba(113, 113, 122, 0.2), rgba(113, 113, 122, 0.05));
            border: 1px solid var(--text-muted);
        }

        .verdict h2 {
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
        }

        .verdict p {
            color: var(--text-secondary);
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }

        .stat-card {
            background: var(--bg-secondary);
            padding: 1rem;
            border-radius: 0.5rem;
            text-align: center;
        }

        .stat-card .value {
            font-size: 2rem;
            font-weight: bold;
        }

        .stat-card .label {
            color: var(--text-secondary);
            font-size: 0.75rem;
            text-transform: uppercase;
        }

        .stat-card.critical .value { color: var(--red); }
        .stat-card.high .value { color: var(--orange); }
        .stat-card.medium .value { color: var(--yellow); }
        .stat-card.low .value { color: var(--blue); }
        .stat-card.info .value { color: var(--text-muted); }

        /* Filters */
        .filters {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
        }

        .filter-btn {
            padding: 0.5rem 1rem;
            border: 1px solid var(--bg-tertiary);
            background: var(--bg-secondary);
            color: var(--text-primary);
            border-radius: 0.25rem;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.875rem;
            transition: all 0.2s;
        }

        .filter-btn:hover {
            background: var(--bg-tertiary);
        }

        .filter-btn.active {
            background: var(--purple);
            border-color: var(--purple);
        }

        /* Findings Table */
        .section {
            margin-bottom: 2rem;
        }

        .section h3 {
            font-size: 1.125rem;
            margin-bottom: 1rem;
            color: var(--purple);
        }

        .findings-table {
            width: 100%;
            border-collapse: collapse;
            background: var(--bg-secondary);
            border-radius: 0.5rem;
            overflow: hidden;
        }

        .findings-table th,
        .findings-table td {
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 1px solid var(--bg-tertiary);
        }

        .findings-table th {
            background: var(--bg-tertiary);
            color: var(--text-secondary);
            font-weight: 500;
            font-size: 0.75rem;
            text-transform: uppercase;
        }

        .findings-table tr:last-child td {
            border-bottom: none;
        }

        .findings-table tr:hover {
            background: var(--bg-tertiary);
        }

        .severity-badge {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.75rem;
            font-weight: 500;
            text-transform: uppercase;
        }

        .severity-badge.critical { background: rgba(239, 68, 68, 0.2); color: var(--red); }
        .severity-badge.high { background: rgba(249, 115, 22, 0.2); color: var(--orange); }
        .severity-badge.medium { background: rgba(251, 191, 36, 0.2); color: var(--yellow); }
        .severity-badge.low { background: rgba(59, 130, 246, 0.2); color: var(--blue); }
        .severity-badge.info { background: rgba(113, 113, 122, 0.2); color: var(--text-muted); }

        .priority-badge {
            display: inline-block;
            padding: 0.125rem 0.375rem;
            background: var(--bg-tertiary);
            border-radius: 0.25rem;
            font-size: 0.625rem;
            color: var(--text-secondary);
        }

        .location {
            font-size: 0.875rem;
            color: var(--cyan);
        }

        .confidence {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        /* Finding Details Modal */
        .modal-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }

        .modal-overlay.active {
            display: flex;
        }

        .modal {
            background: var(--bg-secondary);
            border-radius: 0.5rem;
            max-width: 800px;
            max-height: 80vh;
            overflow: auto;
            padding: 1.5rem;
            margin: 1rem;
        }

        .modal h4 {
            margin-bottom: 1rem;
            color: var(--purple);
        }

        .modal-close {
            float: right;
            background: none;
            border: none;
            color: var(--text-secondary);
            cursor: pointer;
            font-size: 1.5rem;
        }

        .modal pre {
            background: var(--bg-primary);
            padding: 1rem;
            border-radius: 0.25rem;
            overflow-x: auto;
            font-size: 0.875rem;
        }

        /* Verified Fixes Section */
        .fix-card {
            background: var(--bg-secondary);
            border-radius: 0.5rem;
            padding: 1rem;
            margin-bottom: 1rem;
        }

        .fix-card.improvement {
            border-left: 3px solid var(--green);
        }

        .fix-card.failed {
            border-left: 3px solid var(--red);
        }

        .fix-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }

        .fix-metrics {
            display: flex;
            gap: 1rem;
            color: var(--text-secondary);
            font-size: 0.875rem;
        }

        .fix-metrics .positive { color: var(--green); }
        .fix-metrics .negative { color: var(--red); }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 3rem;
            color: var(--text-muted);
        }

        .empty-state .icon {
            font-size: 3rem;
            margin-bottom: 1rem;
        }

        /* Footer */
        .footer {
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-size: 0.75rem;
            border-top: 1px solid var(--bg-tertiary);
            margin-top: 2rem;
        }

        .footer a {
            color: var(--purple);
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <div class="logo">SuperQode QR Dashboard</div>
            <div class="meta">
                <div>Session: <code>{session_id}</code></div>
                <div>Date: {date}</div>
                <div>Duration: {duration}s</div>
            </div>
        </header>

        <div class="verdict {verdict_class}">
            <h2>{verdict_icon} {verdict_text}</h2>
            <p>{verdict_explanation}</p>
        </div>

        <div class="stats-grid">
            <div class="stat-card critical">
                <div class="value">{critical_count}</div>
                <div class="label">Critical</div>
            </div>
            <div class="stat-card high">
                <div class="value">{high_count}</div>
                <div class="label">High</div>
            </div>
            <div class="stat-card medium">
                <div class="value">{medium_count}</div>
                <div class="label">Medium</div>
            </div>
            <div class="stat-card low">
                <div class="value">{low_count}</div>
                <div class="label">Low</div>
            </div>
            <div class="stat-card info">
                <div class="value">{info_count}</div>
                <div class="label">Info</div>
            </div>
        </div>

        <div class="section">
            <h3>Findings ({total_findings})</h3>

            <div class="filters">
                <button class="filter-btn active" onclick="filterFindings('all')">All</button>
                <button class="filter-btn" onclick="filterFindings('critical')">Critical</button>
                <button class="filter-btn" onclick="filterFindings('high')">High</button>
                <button class="filter-btn" onclick="filterFindings('medium')">Medium</button>
                <button class="filter-btn" onclick="filterFindings('low')">Low</button>
                <button class="filter-btn" onclick="filterFindings('info')">Info</button>
            </div>

            {findings_table}
        </div>

        {verified_fixes_section}

        <footer class="footer">
            Generated by <a href="https://github.com/superqode/superqode">SuperQode</a> - Agentic Quality Engineering
        </footer>
    </div>

    <div class="modal-overlay" id="modalOverlay" onclick="closeModal(event)">
        <div class="modal" onclick="event.stopPropagation()">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <div id="modalContent"></div>
        </div>
    </div>

    <script>
        const findings = {findings_json};

        function filterFindings(severity) {
            document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');

            document.querySelectorAll('.finding-row').forEach(row => {
                if (severity === 'all' || row.dataset.severity === severity) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        }

        function showFindingDetails(id) {
            const finding = findings.find(f => f.id === id);
            if (!finding) return;

            let html = `
                <h4>${finding.title}</h4>
                <p><span class="severity-badge ${finding.severity}">${finding.severity}</span>
                   <span class="priority-badge">P${finding.priority}</span></p>
                <p style="margin: 1rem 0;">${finding.description}</p>
            `;

            if (finding.location) {
                html += `<p><strong>Location:</strong> <code class="location">${finding.location}</code></p>`;
            }

            if (finding.evidence) {
                html += `<p style="margin-top: 1rem;"><strong>Evidence:</strong></p>
                         <pre>${escapeHtml(finding.evidence)}</pre>`;
            }

            if (finding.suggested_fix) {
                html += `<p style="margin-top: 1rem;"><strong>Suggested Fix:</strong></p>
                         <pre>${escapeHtml(finding.suggested_fix)}</pre>`;
            }

            if (finding.tags && finding.tags.length > 0) {
                html += `<p style="margin-top: 1rem;"><strong>Tags:</strong> ${finding.tags.join(', ')}</p>`;
            }

            document.getElementById('modalContent').innerHTML = html;
            document.getElementById('modalOverlay').classList.add('active');
        }

        function closeModal(event) {
            if (!event || event.target.id === 'modalOverlay') {
                document.getElementById('modalOverlay').classList.remove('active');
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Close modal on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeModal();
        });
    </script>
</body>
</html>
"""


def _render_findings_table(findings: List[Dict[str, Any]]) -> str:
    """Render the findings table HTML."""
    if not findings:
        return """
        <div class="empty-state">
            <div class="icon">✅</div>
            <p>No issues found during this investigation.</p>
        </div>
        """

    rows = []
    for f in findings:
        severity = f.get("severity", "info")
        priority = f.get("priority", 2)
        confidence = f.get("confidence_score", 0.8)
        location = f.get("location", "-")

        rows.append(f"""
        <tr class="finding-row" data-severity="{severity}" onclick="showFindingDetails('{f["id"]}')">
            <td><span class="severity-badge {severity}">{severity}</span></td>
            <td><span class="priority-badge">P{priority}</span></td>
            <td>{f.get("title", "Untitled")}</td>
            <td><span class="location">{location}</span></td>
            <td><span class="confidence">{confidence:.0%}</span></td>
            <td>{f.get("found_by", "-")}</td>
        </tr>
        """)

    return f"""
    <table class="findings-table">
        <thead>
            <tr>
                <th>Severity</th>
                <th>Priority</th>
                <th>Title</th>
                <th>Location</th>
                <th>Confidence</th>
                <th>Found By</th>
            </tr>
        </thead>
        <tbody>
            {"".join(rows)}
        </tbody>
    </table>
    """


def _render_verified_fixes(verified_fixes: Optional[Dict[str, Any]]) -> str:
    """Render the verified fixes section."""
    if not verified_fixes or not verified_fixes.get("fixes"):
        return ""

    fixes = verified_fixes.get("fixes", [])
    total = verified_fixes.get("total", 0)
    verified = verified_fixes.get("verified", 0)
    improvements = verified_fixes.get("improvements", 0)

    cards = []
    for fix in fixes:
        is_improvement = fix.get("is_improvement", False)
        card_class = "improvement" if is_improvement else "failed"
        status = "✅ Verified" if fix.get("fix_verified") else "❌ Failed"

        metrics = fix.get("metrics", {})
        before = metrics.get("before", {})
        after = metrics.get("after", {})

        tests_before = f"{before.get('tests_passed', 0)}/{before.get('tests_total', 0)}"
        tests_after = f"{after.get('tests_passed', 0)}/{after.get('tests_total', 0)}"

        cards.append(f"""
        <div class="fix-card {card_class}">
            <div class="fix-header">
                <strong>{fix.get("finding_title", "Unknown")}</strong>
                <span>{status}</span>
            </div>
            <div class="fix-metrics">
                <span>Tests: {tests_before} → <span class="{"positive" if is_improvement else ""}">{tests_after}</span></span>
                <span>Patch: <code>{fix.get("patch_file", "-")}</code></span>
                <span>Confidence: {fix.get("fix_confidence", 0):.0%}</span>
            </div>
        </div>
        """)

    return f"""
    <div class="section">
        <h3>Verified Fixes ({verified}/{total} verified, {improvements} improvements)</h3>
        {"".join(cards)}
    </div>
    """


def generate_dashboard_html(qir_json: Dict[str, Any]) -> str:
    """Generate HTML dashboard from QIR JSON data."""
    # Extract data
    session_id = qir_json.get("session_id", "unknown")[:12]
    mode = qir_json.get("mode", "unknown")
    duration = qir_json.get("duration_seconds", 0)

    # Parse date
    started_at = qir_json.get("started_at", "")
    try:
        date = datetime.fromisoformat(started_at.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        date = started_at[:16] if started_at else "Unknown"

    # Verdict
    verdict = qir_json.get("verdict", "blocked")
    verdict_map = {
        "pass": ("✅", "PASS", "pass", "No significant issues found"),
        "conditional": ("⚠️", "CONDITIONAL PASS", "conditional", "Issues found, review recommended"),
        "fail": ("❌", "FAIL", "fail", "Critical issues require attention"),
        "blocked": ("⛔", "BLOCKED", "blocked", "Analysis could not complete"),
    }
    verdict_icon, verdict_text, verdict_class, verdict_explanation = verdict_map.get(
        verdict, verdict_map["blocked"]
    )

    # Override explanation if provided
    if qir_json.get("overall_explanation"):
        verdict_explanation = qir_json["overall_explanation"]

    # Summary counts
    summary = qir_json.get("summary", {})
    by_severity = summary.get("by_severity", {})

    critical_count = by_severity.get("critical", 0)
    high_count = by_severity.get("high", 0)
    medium_count = by_severity.get("medium", 0)
    low_count = by_severity.get("low", 0)
    info_count = by_severity.get("info", 0)
    total_findings = summary.get("total_findings", 0)

    # Findings
    findings = qir_json.get("findings", [])
    findings_table = _render_findings_table(findings)
    findings_json = json.dumps(findings)

    # Verified fixes
    verified_fixes = qir_json.get("verified_fixes")
    verified_fixes_section = _render_verified_fixes(verified_fixes)

    # Render template
    return HTML_TEMPLATE.format(
        session_id=session_id,
        date=date,
        duration=f"{duration:.1f}",
        verdict_icon=verdict_icon,
        verdict_text=verdict_text,
        verdict_class=verdict_class,
        verdict_explanation=verdict_explanation,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        info_count=info_count,
        total_findings=total_findings,
        findings_table=findings_table,
        findings_json=findings_json,
        verified_fixes_section=verified_fixes_section,
    )


class QIRDashboardHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler for serving QIR dashboard."""

    html_content: str = ""

    def do_GET(self):
        """Handle GET requests."""
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(self.html_content.encode("utf-8"))

    def log_message(self, format: str, *args):
        """Suppress default logging."""
        pass


def find_latest_qr(project_root: Path) -> Optional[Path]:
    """Find the most recent QR JSON file."""
    qr_dir = project_root / ".superqode" / "qe-artifacts" / "qr"

    if not qr_dir.exists():
        return None

    json_files = list(qr_dir.glob("*.json"))
    if not json_files:
        return None

    return max(json_files, key=lambda f: f.stat().st_mtime)


def start_dashboard(
    qr_path: Optional[Path] = None,
    project_root: Optional[Path] = None,
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """
    Start the QR web dashboard.

    Args:
        qr_path: Path to specific QR JSON file. If None, uses latest.
        project_root: Project root to search for QRs. Defaults to cwd.
        port: Port to serve on (default: 8765)
        open_browser: Whether to open browser automatically
    """
    project_root = project_root or Path.cwd()

    # Find QR file
    if qr_path is None:
        qr_path = find_latest_qr(project_root)
        if qr_path is None:
            raise FileNotFoundError("No QR files found. Run 'superqe run .' first.")

    # Load QR JSON
    qr_json = json.loads(qr_path.read_text())

    # Generate HTML
    html_content = generate_dashboard_html(qir_json)

    # Configure handler
    QIRDashboardHandler.html_content = html_content

    # Start server
    with socketserver.TCPServer(("", port), QIRDashboardHandler) as httpd:
        url = f"http://localhost:{port}"
        print(f"QR Dashboard running at {url}")
        print("Press Ctrl+C to stop")

        if open_browser:
            # Open browser in background thread to not block
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped")


def export_html(
    qr_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    """
    Export QR as standalone HTML file.

    Args:
        qr_path: Path to QR JSON file
        output_path: Output path for HTML. Defaults to same name with .html extension.

    Returns:
        Path to generated HTML file
    """
    qr_json = json.loads(qr_path.read_text())
    html_content = generate_dashboard_html(qir_json)

    if output_path is None:
        output_path = qr_path.with_suffix(".html")

    output_path.write_text(html_content, encoding="utf-8")
    return output_path
