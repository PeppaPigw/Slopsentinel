from __future__ import annotations

import html
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from slopsentinel import __version__
from slopsentinel.engine.scoring import DIMENSION_LABELS, DIMENSION_MAX, DIMENSION_ORDER
from slopsentinel.engine.types import ScanSummary, Violation
from slopsentinel.rules.base import RuleMeta
from slopsentinel.rules.registry import rule_meta_by_id
from slopsentinel.utils import safe_relpath

_SEVERITY_LABEL = {"error": "Error", "warn": "Warning", "info": "Info"}
_SEVERITY_CLASS = {"error": "sev-error", "warn": "sev-warn", "info": "sev-info"}


def render_html(summary: ScanSummary, *, project_root: Path) -> str:
    """
    Render an HTML report.

    This reporter is dependency-free (stdlib only) and focuses on deterministic,
    copy/paste-friendly output (suitable for artifacts).
    """

    meta = rule_meta_by_id()

    by_file: dict[str, list[Violation]] = defaultdict(list)
    repo_level: list[Violation] = []

    for v in summary.violations:
        if v.location is None or v.location.path is None:
            repo_level.append(v)
            continue
        by_file[safe_relpath(v.location.path, project_root)].append(v)

    file_lines: dict[str, list[str]] = {path: _read_lines_safe(project_root, path) for path in by_file}

    out: list[str] = []
    out.append("<!doctype html>")
    out.append('<html lang="en">')
    out.append("<head>")
    out.append('  <meta charset="utf-8">')
    out.append("  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    out.append("  <title>SlopSentinel report</title>")
    out.append("  <style>")
    out.append(_CSS)
    out.append("  </style>")
    out.append("</head>")
    out.append("<body>")

    out.append('  <a class="skip" href="#main">Skip to content</a>')
    out.append("  <header>")
    out.append("    <h1>SlopSentinel report</h1>")
    out.append(f"    <div class=\"meta\">Version {html.escape(__version__)}</div>")
    out.append("  </header>")

    out.append('  <main id="main">')

    out.append("  <section class=\"summary\">")
    out.append("    <h2>Summary</h2>")
    out.append("    <ul>")
    out.append(f"      <li><strong>Score</strong>: {int(summary.score)}/100</li>")
    out.append(f"      <li><strong>Files scanned</strong>: {int(summary.files_scanned)}</li>")
    out.append(f"      <li><strong>Violations</strong>: {len(summary.violations)}</li>")
    if summary.dominant_fingerprints:
        dom = ", ".join(html.escape(x) for x in summary.dominant_fingerprints)
        out.append(f"      <li><strong>Dominant fingerprints</strong>: {dom}</li>")
    out.append("    </ul>")
    out.append("  </section>")

    out.append("  <section class=\"controls\" aria-label=\"Filters\">")
    out.append("    <h2>Filters</h2>")
    out.append("    <form id=\"filters\">")
    out.append("      <fieldset>")
    out.append("        <legend>Severity</legend>")
    out.append("        <label><input type=\"checkbox\" name=\"severity\" value=\"error\" checked> Error</label>")
    out.append("        <label><input type=\"checkbox\" name=\"severity\" value=\"warn\" checked> Warning</label>")
    out.append("        <label><input type=\"checkbox\" name=\"severity\" value=\"info\" checked> Info</label>")
    out.append("      </fieldset>")
    out.append("      <fieldset>")
    out.append("        <legend>Dimension</legend>")
    for dim in DIMENSION_ORDER:
        label = DIMENSION_LABELS.get(dim, dim.title())
        out.append(
            f"        <label><input type=\"checkbox\" name=\"dimension\" value=\"{html.escape(dim)}\" checked> {html.escape(label)}</label>"
        )
    out.append("      </fieldset>")
    out.append(
        "      <label class=\"search\">Search <input id=\"filter-search\" type=\"search\" placeholder=\"rule id, message, file\" autocomplete=\"off\"></label>"
    )
    out.append(
        "      <div class=\"filter-meta\" aria-live=\"polite\">Showing <span id=\"visible-count\">0</span> of <span id=\"total-count\">0</span> violations</div>"
    )
    out.append("    </form>")
    out.append("    <noscript><div class=\"meta\">Enable JavaScript to use interactive filters.</div></noscript>")
    out.append("  </section>")

    out.append("  <section class=\"breakdown\">")
    out.append("    <h2>Breakdown</h2>")
    out.append("    <table>")
    out.append("      <thead><tr><th>Dimension</th><th>Points</th></tr></thead>")
    out.append("      <tbody>")
    for dim in DIMENSION_ORDER:
        label = DIMENSION_LABELS.get(dim, dim.title())
        value = getattr(summary.breakdown, dim)
        out.append(f"        <tr><td>{html.escape(label)}</td><td>{int(value)}/{int(DIMENSION_MAX[dim])}</td></tr>")
    out.append("      </tbody>")
    out.append("    </table>")
    out.append(_render_breakdown_svg(summary))
    out.append("  </section>")

    if repo_level:
        out.append("  <section class=\"repo\">")
        out.append("    <h2>Repository signals</h2>")
        out.append("    <ul class=\"violations\">")
        for v in sorted(repo_level, key=_sort_key):
            out.append(_render_violation(v, file_lines=None, rel_file=None, meta=meta))
        out.append("    </ul>")
        out.append("  </section>")

    if by_file:
        out.append("  <section class=\"files\">")
        out.append("    <h2>Files</h2>")
        out.append("    <nav aria-label=\"Files\">")
        out.append("    <ul>")
        for file_path in sorted(by_file):
            anchor = _anchor_for_file(file_path)
            out.append(f"      <li><a href=\"#{anchor}\">{html.escape(file_path)}</a></li>")
        out.append("    </ul>")
        out.append("    </nav>")
        out.append("  </section>")

    for file_path in sorted(by_file):
        anchor = _anchor_for_file(file_path)
        out.append(f"  <section class=\"file\" id=\"{anchor}\" data-file=\"{html.escape(file_path)}\">")
        out.append(f"    <h2>{html.escape(file_path)}</h2>")
        out.append("    <ul class=\"violations\">")
        for v in sorted(by_file[file_path], key=_sort_key):
            out.append(_render_violation(v, file_lines=file_lines.get(file_path), rel_file=file_path, meta=meta))
        out.append("    </ul>")
        out.append("  </section>")

    out.append("  </main>")

    out.append("  <script>")
    out.append(_JS)
    out.append("  </script>")

    out.append("</body>")
    out.append("</html>")
    out.append("")
    return "\n".join(out)


def _render_violation(
    v: Violation,
    *,
    file_lines: list[str] | None,
    rel_file: str | None,
    meta: Mapping[str, RuleMeta],
) -> str:
    sev = v.severity
    sev_label = _SEVERITY_LABEL.get(sev, sev.title())
    sev_class = _SEVERITY_CLASS.get(sev, "sev-unknown")
    rule_meta = meta.get(v.rule_id)
    model = rule_meta.fingerprint_model if rule_meta is not None else None

    loc = ""
    snippet = ""
    if v.location is not None and v.location.start_line is not None:
        loc = f"{int(v.location.start_line)}"
        if v.location.start_col is not None:
            loc += f":{int(v.location.start_col)}"

        if file_lines is not None:
            idx = int(v.location.start_line) - 1
            if 0 <= idx < len(file_lines):
                snippet_text = file_lines[idx].rstrip("\n")
                snippet = f"<pre><code>{html.escape(snippet_text)}</code></pre>"

    suggestion = ""
    if v.suggestion:
        suggestion = f"<div class=\"suggestion\">{html.escape(v.suggestion)}</div>"

    message = html.escape(v.message)
    rule_id = html.escape(v.rule_id)
    loc_html = f"<span class=\"loc\">({html.escape(loc)})</span>" if loc else ""
    file_attr = html.escape(rel_file or "")
    model_attr = html.escape(model or "")
    dimension_attr = html.escape(v.dimension)

    return (
        "<li class=\"violation\" "
        f"data-severity=\"{html.escape(sev)}\" "
        f"data-dimension=\"{dimension_attr}\" "
        f"data-rule-id=\"{rule_id}\" "
        f"data-file=\"{file_attr}\" "
        f"data-model=\"{model_attr}\">"
        f"<span class=\"badge {sev_class}\">{html.escape(sev_label)}</span> "
        f"<span class=\"rule\">{rule_id}</span> "
        f"{loc_html} "
        f"<span class=\"message\">{message}</span>"
        f"{suggestion}"
        f"{snippet}"
        "</li>"
    )


def _sort_key(v: Violation) -> tuple[int, int, str]:
    severity_rank = {"error": 0, "warn": 1, "info": 2}.get(v.severity, 3)
    line = v.location.start_line if v.location and v.location.start_line else 10**9
    return severity_rank, int(line), v.rule_id


def _anchor_for_file(path: str) -> str:
    # Keep IDs predictable and valid.
    safe = []
    for ch in path:
        if ch.isalnum():
            safe.append(ch)
        else:
            safe.append("-")
    return "file-" + "".join(safe).strip("-")


def _read_lines_safe(project_root: Path, rel_path: str) -> list[str]:
    """
    Read file lines for rendering snippets, refusing to escape the project root.
    """

    candidate = project_root / Path(rel_path)
    try:
        resolved_root = project_root.resolve()
        resolved = candidate.resolve()
        resolved.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        return []

    try:
        return resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _render_breakdown_svg(summary: ScanSummary) -> str:
    width = 520
    height = 24 * len(DIMENSION_ORDER) + 16
    left = 140
    bar_width = width - left - 20

    parts: list[str] = []
    parts.append(
        f'    <svg class="breakdown-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Score breakdown chart">'
    )

    y = 16
    for dim in DIMENSION_ORDER:
        label = DIMENSION_LABELS.get(dim, dim.title())
        value = int(getattr(summary.breakdown, dim))
        max_value = int(DIMENSION_MAX[dim])
        ratio = (value / max(max_value, 1)) if max_value else 0.0
        w = int(bar_width * ratio)

        parts.append(f'      <text x="0" y="{y + 12}" class="svg-label">{html.escape(label)}</text>')
        parts.append(f'      <rect x="{left}" y="{y}" width="{bar_width}" height="14" class="svg-bg" />')
        parts.append(f'      <rect x="{left}" y="{y}" width="{w}" height="14" class="svg-bar" />')
        parts.append(f'      <text x="{left + bar_width + 6}" y="{y + 12}" class="svg-value">{value}/{max_value}</text>')
        y += 24

    parts.append("    </svg>")
    return "\n".join(parts)


_CSS = """
body {
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  margin: 2rem;
  color: #111827;
  background: #ffffff;
}

header {
  margin-bottom: 1.5rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #e5e7eb;
}

h1, h2 {
  margin: 0 0 0.75rem 0;
}

.meta {
  color: #6b7280;
  font-size: 0.9rem;
}

section {
  margin: 1.5rem 0;
}

table {
  border-collapse: collapse;
  width: 100%;
  max-width: 42rem;
}

th, td {
  border: 1px solid #e5e7eb;
  padding: 0.5rem 0.75rem;
  text-align: left;
}

th {
  background: #f9fafb;
}

ul.violations {
  list-style: none;
  padding: 0;
  margin: 0;
}

li.violation {
  padding: 0.75rem 0;
  border-bottom: 1px solid #e5e7eb;
}

.badge {
  display: inline-block;
  font-size: 0.8rem;
  padding: 0.12rem 0.5rem;
  border-radius: 0.5rem;
  border: 1px solid #e5e7eb;
  margin-right: 0.25rem;
}

.sev-error { background: #fee2e2; border-color: #fecaca; }
.sev-warn { background: #fef9c3; border-color: #fde68a; }
.sev-info { background: #e0f2fe; border-color: #bae6fd; }

.rule {
  font-weight: 700;
}

.loc {
  color: #6b7280;
  margin-right: 0.25rem;
}

.suggestion {
  margin-top: 0.25rem;
  color: #374151;
  font-style: italic;
}

pre {
  margin: 0.5rem 0 0 0;
  padding: 0.75rem;
  background: #111827;
  color: #f9fafb;
  border-radius: 0.5rem;
  overflow-x: auto;
}

code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.9rem;
}

[hidden] {
  display: none !important;
}

.skip {
  position: absolute;
  left: -9999px;
  top: auto;
  width: 1px;
  height: 1px;
  overflow: hidden;
}

.skip:focus {
  position: static;
  width: auto;
  height: auto;
  padding: 0.5rem 0.75rem;
  background: #111827;
  color: #ffffff;
  border-radius: 0.5rem;
  display: inline-block;
  margin-bottom: 1rem;
}

.controls form {
  display: grid;
  gap: 0.75rem;
  max-width: 54rem;
}

fieldset {
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
  padding: 0.75rem;
}

legend {
  padding: 0 0.25rem;
  font-weight: 600;
}

label {
  margin-right: 0.75rem;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

.search {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

input[type="search"] {
  padding: 0.35rem 0.5rem;
  border: 1px solid #d1d5db;
  border-radius: 0.375rem;
  min-width: 18rem;
}

.filter-meta {
  color: #6b7280;
  font-size: 0.9rem;
}

.breakdown-svg {
  margin-top: 0.75rem;
  max-width: 42rem;
  width: 100%;
}

.svg-label, .svg-value {
  font: 12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  fill: #111827;
}

.svg-bg {
  fill: #f3f4f6;
  stroke: #e5e7eb;
}

.svg-bar {
  fill: #2563eb;
}
"""


_JS = r"""
(function () {
  const violations = Array.from(document.querySelectorAll("li.violation"));
  const fileSections = Array.from(document.querySelectorAll("section.file"));

  const totalCount = document.getElementById("total-count");
  const visibleCount = document.getElementById("visible-count");
  const search = document.getElementById("filter-search");
  const filterForm = document.getElementById("filters");

  function selectedValues(name) {
    return new Set(
      Array.from(filterForm.querySelectorAll(`input[name="${name}"]:checked`)).map((el) => el.value)
    );
  }

  function normalize(s) {
    return (s || "").toLowerCase();
  }

  function matchesSearch(el, query) {
    if (!query) return true;
    const text = [
      el.getAttribute("data-rule-id") || "",
      el.getAttribute("data-file") || "",
      el.getAttribute("data-model") || "",
      el.textContent || "",
    ].join(" ");
    return normalize(text).includes(query);
  }

  function applyFilters() {
    const severities = selectedValues("severity");
    const dimensions = selectedValues("dimension");
    const query = normalize(search.value.trim());

    let visible = 0;
    for (const el of violations) {
      const sev = el.getAttribute("data-severity");
      const dim = el.getAttribute("data-dimension");
      const ok =
        severities.has(sev) &&
        dimensions.has(dim) &&
        matchesSearch(el, query);
      el.hidden = !ok;
      if (ok) visible += 1;
    }

    for (const section of fileSections) {
      const anyVisible = section.querySelector("li.violation:not([hidden])") !== null;
      section.hidden = !anyVisible;
    }

    totalCount.textContent = String(violations.length);
    visibleCount.textContent = String(visible);
  }

  filterForm.addEventListener("change", applyFilters);
  search.addEventListener("input", applyFilters);
  applyFilters();
})();
"""
