from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import click
import typer
from rich.console import Console

from slopsentinel import __version__
from slopsentinel.audit import (
    AuditCallbacks,
    AuditResult,
    audit_files,
    audit_path,
)
from slopsentinel.autofix import autofix_path
from slopsentinel.baseline import build_baseline, save_baseline
from slopsentinel.deslop import deslop_file
from slopsentinel.engine.types import ScanSummary, Violation
from slopsentinel.init import InitOptions, init_project
from slopsentinel.logging_utils import configure_logging
from slopsentinel.reporters.github import render_github_annotations
from slopsentinel.reporters.html_reporter import render_html
from slopsentinel.reporters.json_reporter import parse_json_report, render_json
from slopsentinel.reporters.markdown import render_markdown
from slopsentinel.reporters.sarif import render_sarif
from slopsentinel.reporters.terminal import render_terminal

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="SlopSentinel — local-first AI slop code auditor.",
)
console = Console()
err_console = Console(stderr=True)
logger = logging.getLogger(__name__)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose logs (printed to stderr)."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Reduce non-essential output."),
    ] = False,
    progress: Annotated[
        bool,
        typer.Option("--progress/--no-progress", help="Show a progress bar for long scans.", show_default=True),
    ] = True,
) -> None:
    """SlopSentinel CLI."""

    if verbose and quiet:
        raise typer.BadParameter("Choose at most one: --verbose or --quiet.")
    configure_logging(verbose=verbose, quiet=quiet)
    ctx.obj = {"verbose": verbose, "quiet": quiet, "progress": progress}


def _cli_settings() -> dict[str, bool]:
    ctx = click.get_current_context(silent=True)
    if ctx is None or not isinstance(ctx.obj, dict):
        return {"verbose": False, "quiet": False, "progress": True}
    verbose = bool(ctx.obj.get("verbose", False))
    quiet = bool(ctx.obj.get("quiet", False))
    progress = bool(ctx.obj.get("progress", True))
    return {"verbose": verbose, "quiet": quiet, "progress": progress}


def _emit_output(
    fmt: str,
    *,
    summary: ScanSummary,
    project_root: Path,
    console: Console,
    allow_github: bool,
    show_details: bool = True,
) -> None:
    normalized = fmt.strip().lower()
    if normalized == "terminal":
        render_terminal(summary, project_root=project_root, console=console, show_details=show_details)
        return
    if normalized == "json":
        typer.echo(render_json(summary, project_root=project_root))
        return
    if normalized == "sarif":
        typer.echo(render_sarif(list(summary.violations), project_root=project_root))
        return
    if normalized == "html":
        typer.echo(render_html(summary, project_root=project_root))
        return
    if normalized == "markdown":
        typer.echo(render_markdown(summary, project_root=project_root))
        return
    if normalized == "github" and allow_github:
        typer.echo(render_github_annotations(list(summary.violations), project_root=project_root))
        return

    if allow_github:
        raise typer.BadParameter("Unsupported format. Use: terminal, json, sarif, html, markdown, github.")
    raise typer.BadParameter("Unsupported format. Use: terminal, json, sarif, html, markdown.")


def _audit_with_optional_progress(
    path: Path,
    *,
    changed_lines: dict[Path, set[int]] | None = None,
    apply_baseline: bool = True,
    record_history: bool = True,
    show_progress: bool,
    verbose: bool,
    scoring_profile: str | None = None,
    no_cache: bool = False,
) -> AuditResult:
    from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn

    from slopsentinel.scanner import discover_files, prepare_target

    target = prepare_target(path)
    if scoring_profile is not None:
        target = replace(target, config=replace(target.config, scoring=replace(target.config.scoring, profile=scoring_profile)))
    if no_cache and target.config.cache.enabled:
        target = replace(target, config=replace(target.config, cache=replace(target.config.cache, enabled=False)))

    if changed_lines is None:
        files = discover_files(target)
    else:
        files = sorted(changed_lines.keys())
        # Keep only files that are under scan_path and supported by language/ignore rules.
        discovered = set(discover_files(target))
        files = [p for p in files if p in discovered]

    if verbose:
        logger.debug("discovered %d candidate file(s)", len(files))

    if not show_progress:
        return audit_files(
            target,
            files=files,
            changed_lines=changed_lines,
            apply_baseline=apply_baseline,
            record_history=record_history,
        )

    progress_console = Console(stderr=True)
    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=progress_console,
        transient=True,
    )

    ctx_task = progress.add_task("Contexts", total=len(files))
    scan_task = progress.add_task("Scan", total=1)

    def _on_context_built(_path: Path) -> None:
        progress.advance(ctx_task, 1)

    def _on_ready(total: int) -> None:
        progress.update(scan_task, total=total, completed=0)

    def _on_scanned(_path: Path) -> None:
        progress.advance(scan_task, 1)

    callbacks = AuditCallbacks(
        on_context_built=_on_context_built,
        on_file_contexts_ready=_on_ready,
        on_file_scanned=_on_scanned,
    )

    with progress:
        return audit_files(
            target,
            files=files,
            changed_lines=changed_lines,
            apply_baseline=apply_baseline,
            record_history=record_history,
            callbacks=callbacks,
        )


@app.command()
def rules(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Project directory (default: current directory).",
        ),
    ] = Path("."),
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: terminal, json.", show_default=True),
    ] = "terminal",
    enabled_only: Annotated[
        bool,
        typer.Option("--enabled-only", help="Only show rules enabled by the current config."),
    ] = False,
) -> None:
    """
    List all available rules (built-in + plugin rules) and their metadata.
    """

    import json

    from rich.table import Table

    from slopsentinel.config import compute_enabled_rule_ids
    from slopsentinel.rules.plugins import PluginLoadError, load_plugin_rules
    from slopsentinel.rules.registry import all_rules, set_extra_rules
    from slopsentinel.scanner import prepare_target

    target = prepare_target(path)
    try:
        plugin_rules = load_plugin_rules(target.config.plugins)
    except PluginLoadError as exc:
        console.print(f"Failed to load plugins: {exc}")
        raise typer.Exit(code=2) from exc
    set_extra_rules(plugin_rules)

    available_rules = list(all_rules())
    available_ids = {r.meta.rule_id for r in available_rules}
    enabled_ids = compute_enabled_rule_ids(target.config, available_rule_ids=available_ids)

    rows = []
    for rule in sorted(available_rules, key=lambda r: r.meta.rule_id):
        meta = rule.meta
        enabled = meta.rule_id in enabled_ids
        if enabled_only and not enabled:
            continue
        rows.append(
            {
                "rule_id": meta.rule_id,
                "enabled": enabled,
                "title": meta.title,
                "description": meta.description,
                "dimension": meta.score_dimension,
                "default_severity": meta.default_severity,
                "fingerprint_model": meta.fingerprint_model,
            }
        )

    normalized = output_format.strip().lower()
    if normalized == "json":
        typer.echo(json.dumps(rows, indent=2, sort_keys=True))
        return
    if normalized != "terminal":
        raise typer.BadParameter("Unsupported format. Use: terminal, json.")

    table = Table(title="SlopSentinel Rules")
    table.add_column("ID", style="bold")
    table.add_column("Enabled", justify="center")
    table.add_column("Severity")
    table.add_column("Dimension")
    table.add_column("Model")
    table.add_column("Title")
    for row in rows:
        table.add_row(
            str(row["rule_id"]),
            "yes" if row["enabled"] else "no",
            str(row["default_severity"]),
            str(row["dimension"]),
            str(row["fingerprint_model"] or "-"),
            str(row["title"]),
        )
    console.print(table)


@app.command()
def explain(
    rule_id: Annotated[
        str,
        typer.Argument(help="Rule id to explain (e.g. A03, E01, G02)."),
    ],
    path: Annotated[
        Path,
        typer.Option(
            "--path",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Project directory used to load config + plugin rules (default: current directory).",
        ),
    ] = Path("."),
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: terminal, json.", show_default=True),
    ] = "terminal",
) -> None:
    """
    Explain a single rule (metadata + suppression/config hints).
    """

    import json

    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.text import Text

    from slopsentinel.rules.examples import EXAMPLES
    from slopsentinel.rules.plugins import PluginLoadError, load_plugin_rules
    from slopsentinel.rules.registry import rule_by_id, set_extra_rules
    from slopsentinel.scanner import prepare_target

    target = prepare_target(path)
    try:
        plugin_rules = load_plugin_rules(target.config.plugins)
    except PluginLoadError as exc:
        err_console.print(f"Failed to load plugins: {exc}")
        raise typer.Exit(code=2) from exc
    set_extra_rules(plugin_rules)

    canonical = rule_id.strip().upper()
    rule = rule_by_id(canonical)
    if rule is None:
        raise typer.BadParameter(f"Unknown rule id: {rule_id!r}. Use `slopsentinel rules` to list available rules.")

    meta = rule.meta
    example = EXAMPLES.get(meta.rule_id)

    normalized = output_format.strip().lower()
    if normalized == "json":
        payload = {
            "rule_id": meta.rule_id,
            "title": meta.title,
            "description": meta.description,
            "default_severity": meta.default_severity,
            "dimension": meta.score_dimension,
            "fingerprint_model": meta.fingerprint_model,
            "example": (
                {
                    "language": example.language,
                    "bad": example.bad,
                    "good": example.good,
                    "notes": example.notes,
                }
                if example is not None
                else None
            ),
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if normalized != "terminal":
        raise typer.BadParameter("Unsupported format. Use: terminal, json.")

    header = Text()
    header.append(meta.rule_id, style="bold")
    header.append(" — ", style="dim")
    header.append(meta.title)

    details = "\n".join(
        [
            meta.description,
            "",
            f"Default severity: {meta.default_severity}",
            f"Dimension: {meta.score_dimension}",
            f"Fingerprint model: {meta.fingerprint_model or '-'}",
        ]
    )
    console.print(Panel(details, title=header, border_style="cyan"))

    console.print(Text("Config override (pyproject.toml):", style="bold"))
    console.print(
        Syntax(
            f"[tool.slopsentinel.rules.{meta.rule_id}]\nseverity = \"info\"  # or warn/error\n",
            "toml",
            word_wrap=True,
        )
    )
    console.print(Text("Suppressions (in-file):", style="bold"))
    console.print(
        Syntax(
            "\n".join(
                [
                    f"# slop: disable-file={meta.rule_id}",
                    f"value = 1  # slop: disable={meta.rule_id}",
                    f"# slop: disable-next-line={meta.rule_id}",
                    "value = 2",
                    "",
                ]
            ),
            "python",
            word_wrap=True,
        )
    )

    if example is not None:
        console.print(Text("Example:", style="bold"))
        if example.notes:
            console.print(Text(example.notes, style="dim"))
        console.print(Text("Bad:", style="bold"))
        console.print(Syntax(example.bad, example.language, word_wrap=True))
        if example.good is not None:
            console.print(Text("Good:", style="bold"))
            console.print(Syntax(example.good, example.language, word_wrap=True))


@app.command()
def init(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Target project directory (default: current directory).",
        ),
    ] = Path("."),
    ci: Annotated[
        str | None,
        typer.Option(
            "--ci",
            help="Generate CI workflow (supported: github).",
            show_default=False,
        ),
    ] = None,
    pre_commit: Annotated[
        bool,
        typer.Option("--pre-commit", help="Generate/patch .pre-commit-config.yaml."),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", help="Ask questions and generate a tailored config."),
    ] = False,
    scoring_profile: Annotated[
        str,
        typer.Option("--scoring-profile", help="Scoring profile: default, strict, lenient.", show_default=True),
    ] = "default",
    languages: Annotated[
        str | None,
        typer.Option(
            "--languages",
            help="Comma-separated languages to set in generated config (default: auto-detect).",
            show_default=False,
        ),
    ] = None,
) -> None:
    """
    Initialize SlopSentinel configuration for a repository.

    This command is intentionally conservative:
    - It won't overwrite existing files.
    - It won't rewrite existing pyproject/workflow/pre-commit files if it can avoid it.
    - Running it multiple times is idempotent.
    """

    from slopsentinel.init import detect_project_languages
    from slopsentinel.languages.registry import LANGUAGES

    resolved_languages: tuple[str, ...] | None = None
    resolved_profile = scoring_profile.strip().lower() or "default"
    allowed_profiles = {"default", "strict", "lenient"}
    allowed_languages = {spec.name for spec in LANGUAGES}

    if interactive:
        detected = detect_project_languages(path)
        console.print(f"Detected languages: {', '.join(detected)}")
        if typer.confirm("Use detected languages for config?", default=True):
            resolved_languages = detected
        else:
            raw = typer.prompt("Languages (comma-separated)", default=",".join(detected))
            tokens = [t.strip().lower() for t in raw.replace(";", ",").split(",") if t.strip()]
            resolved_languages = tuple(tokens) if tokens else detected

        if not ci:
            ci = "github" if typer.confirm("Generate a GitHub Actions workflow?", default=True) else None
        if not pre_commit:
            pre_commit = typer.confirm("Generate/patch .pre-commit-config.yaml?", default=False)

        resolved_profile = typer.prompt("Scoring profile", default=resolved_profile).strip().lower() or "default"

    if languages is not None and not interactive:
        tokens = [t.strip().lower() for t in languages.replace(";", ",").split(",") if t.strip()]
        resolved_languages = tuple(tokens) if tokens else None

    if resolved_profile not in allowed_profiles:
        raise typer.BadParameter(f"Unsupported scoring profile: {resolved_profile!r}. Use: default, strict, lenient.")

    if resolved_languages is not None:
        unknown = sorted({lang for lang in resolved_languages if lang not in allowed_languages})
        if unknown:
            raise typer.BadParameter(f"Unknown language(s): {', '.join(unknown)}. Use `slopsentinel rules` to inspect config defaults.")

    options = InitOptions(project_dir=path, ci=ci, pre_commit=pre_commit, languages=resolved_languages, scoring_profile=resolved_profile)
    result = init_project(options)

    for message in result.messages:
        console.print(message)

    if result.changed_files:
        console.print("\nChanged files:")
        for file_path in result.changed_files:
            try:
                display_path = file_path.relative_to(path)
            except ValueError:
                display_path = file_path
            console.print(f"- {display_path}")


@app.command()
def scan(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            help="File or directory to scan (default: current directory).",
        ),
    ] = Path("."),
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: terminal, json, sarif, html, markdown, github.", show_default=True),
    ] = "terminal",
    threshold: Annotated[
        int | None,
        typer.Option("--threshold", min=0, max=100, help="Mark as slop if score is below this threshold (0-100)."),
    ] = None,
    fail_under: Annotated[
        int | None,
        typer.Option("--fail-under", min=0, max=100, help="Shortcut for --threshold N --fail-on-slop (CI-friendly)."),
    ] = None,
    fail_on_slop: Annotated[
        bool | None,
        typer.Option(
            "--fail-on-slop/--no-fail-on-slop",
            help="Exit non-zero when score is below threshold (default: use config).",
            show_default=False,
        ),
    ] = None,
    scoring_profile: Annotated[
        str | None,
        typer.Option("--profile", "--scoring-profile", help="Override scoring profile for this run: default, strict, lenient."),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Disable cache usage for this run (even if enabled in config)."),
    ] = False,
) -> None:
    settings = _cli_settings()
    normalized_profile = scoring_profile.strip().lower() if isinstance(scoring_profile, str) and scoring_profile else None
    if normalized_profile is not None and normalized_profile not in {"default", "strict", "lenient"}:
        raise typer.BadParameter("Unsupported scoring profile. Use: default, strict, lenient.")
    result = _audit_with_optional_progress(
        path,
        changed_lines=None,
        apply_baseline=True,
        record_history=True,
        show_progress=settings["progress"] and not settings["quiet"] and output_format.strip().lower() == "terminal",
        verbose=settings["verbose"],
        scoring_profile=normalized_profile,
        no_cache=no_cache,
    )
    effective_threshold = (
        fail_under
        if fail_under is not None
        else (threshold if threshold is not None else result.target.config.threshold)
    )
    effective_fail_on_slop = (
        True
        if fail_under is not None
        else (fail_on_slop if fail_on_slop is not None else result.target.config.fail_on_slop)
    )

    _emit_output(
        output_format,
        summary=result.summary,
        project_root=result.target.project_root,
        console=console,
        allow_github=True,
        show_details=not settings["quiet"],
    )

    if result.summary.score < effective_threshold and effective_fail_on_slop:
        raise typer.Exit(code=1)


@app.command()
def report(
    input_json: Annotated[
        str,
        typer.Argument(help="Input JSON report path, or '-' to read from stdin."),
    ],
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: terminal, html, sarif, markdown, github.", show_default=True),
    ] = "terminal",
    project_root: Annotated[
        Path,
        typer.Option(
            "--project-root",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Project root used to resolve relative paths in the JSON report (default: current directory).",
        ),
    ] = Path("."),
) -> None:
    """
    Render a previously saved JSON scan report in another format.
    """

    try:
        if input_json.strip() == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(input_json).read_text(encoding="utf-8", errors="replace")
        summary = parse_json_report(raw, project_root=project_root)
    except Exception as exc:
        err_console.print(f"Invalid JSON report: {exc}")
        raise typer.Exit(code=2) from exc

    settings = _cli_settings()
    _emit_output(
        output_format,
        summary=summary,
        project_root=project_root,
        console=console,
        allow_github=True,
        show_details=not settings["quiet"],
    )


def _violation_fingerprint(v: Violation, *, project_root: Path) -> str:
    from slopsentinel.utils import safe_relpath

    loc = v.location
    rel_path = safe_relpath(loc.path, project_root) if loc is not None and loc.path is not None else ""
    line_no = int(loc.start_line) if loc is not None and loc.start_line is not None else 0
    payload = {"rule_id": v.rule_id, "path": rel_path, "line": line_no, "message": v.message}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return sha256(raw).hexdigest()


def _violation_to_dict(v: Violation, *, project_root: Path) -> dict[str, object]:
    from slopsentinel.utils import safe_relpath

    loc = v.location
    loc_payload: dict[str, object] | None = None
    if loc is not None and loc.path is not None:
        loc_payload = {
            "path": safe_relpath(loc.path, project_root),
            "start_line": loc.start_line,
            "start_col": loc.start_col,
            "end_line": loc.end_line,
            "end_col": loc.end_col,
        }
    return {
        "rule_id": v.rule_id,
        "severity": v.severity,
        "dimension": v.dimension,
        "message": v.message,
        "suggestion": v.suggestion,
        "location": loc_payload,
    }


@app.command()
def compare(
    before_json: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, resolve_path=True, help="JSON report from a previous scan."),
    ],
    after_json: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, resolve_path=True, help="JSON report from a later scan."),
    ],
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: terminal, json.", show_default=True),
    ] = "terminal",
    project_root: Annotated[
        Path,
        typer.Option(
            "--project-root",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Project root used to resolve relative paths in the JSON reports (default: current directory).",
        ),
    ] = Path("."),
) -> None:
    """
    Compare two JSON scan reports and show added/removed violations.
    """

    try:
        before = parse_json_report(before_json.read_text(encoding="utf-8", errors="replace"), project_root=project_root)
        after = parse_json_report(after_json.read_text(encoding="utf-8", errors="replace"), project_root=project_root)
    except Exception as exc:
        err_console.print(f"Invalid JSON report(s): {exc}")
        raise typer.Exit(code=2) from exc

    before_by_fp = {_violation_fingerprint(v, project_root=project_root): v for v in before.violations}
    after_by_fp = {_violation_fingerprint(v, project_root=project_root): v for v in after.violations}

    added_fps = sorted(set(after_by_fp).difference(before_by_fp))
    removed_fps = sorted(set(before_by_fp).difference(after_by_fp))
    added = [after_by_fp[fp] for fp in added_fps]
    removed = [before_by_fp[fp] for fp in removed_fps]

    score_delta = int(after.score) - int(before.score)

    normalized = output_format.strip().lower()
    if normalized == "json":
        payload = {
            "score_delta": score_delta,
            "added": [_violation_to_dict(v, project_root=project_root) for v in added],
            "removed": [_violation_to_dict(v, project_root=project_root) for v in removed],
        }
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    if normalized != "terminal":
        raise typer.BadParameter("Unsupported format. Use: terminal, json.")

    console.print(f"Score: {before.score} -> {after.score}  (Δ{score_delta:+d})")
    if not added and not removed:
        console.print("No changes in violations.")
        return

    from slopsentinel.utils import safe_relpath

    if added:
        console.print(f"\nAdded ({len(added)}):", style="bold red")
        for v in added[:50]:
            loc = v.location
            where = "-"
            if loc is not None and loc.path is not None and loc.start_line is not None:
                where = f"{safe_relpath(loc.path, project_root)}:{int(loc.start_line)}"
            console.print(f"+ {where} {v.rule_id} {v.severity} {v.message}")

    if removed:
        console.print(f"\nRemoved ({len(removed)}):", style="bold green")
        for v in removed[:50]:
            loc = v.location
            where = "-"
            if loc is not None and loc.path is not None and loc.start_line is not None:
                where = f"{safe_relpath(loc.path, project_root)}:{int(loc.start_line)}"
            console.print(f"- {where} {v.rule_id} {v.severity} {v.message}")


@app.command()
def ci(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            help="File or directory to scan (default: current directory).",
        ),
    ] = Path("."),
    fail_under: Annotated[
        int,
        typer.Option("--fail-under", min=0, max=100, help="Fail CI if score is below this threshold (0-100)."),
    ] = 75,
    output_format: Annotated[
        str | None,
        typer.Option("--format", help="Output format: terminal, sarif, github (default: auto).", show_default=False),
    ] = None,
    update_baseline: Annotated[
        bool,
        typer.Option("--update-baseline", help="Update baseline file after scanning (intended for main branch automation)."),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Disable cache usage for this run (even if enabled in config)."),
    ] = False,
) -> None:
    """
    CI-friendly scan wrapper: baseline-aware, format-aware, and stable exit codes.

    Exit codes:
    - 0: pass
    - 1: score below --fail-under
    - 2: configuration/runtime error
    """

    from slopsentinel.audit import audit_files
    from slopsentinel.scanner import discover_files, prepare_target

    settings = _cli_settings()
    fmt = (output_format or "").strip().lower() or None
    if fmt is None:
        fmt = "github" if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI") else "terminal"
    if fmt not in {"terminal", "sarif", "github"}:
        raise typer.BadParameter("Unsupported format. Use: terminal, sarif, github.")

    try:
        target = prepare_target(path)
        if no_cache and target.config.cache.enabled:
            target = replace(target, config=replace(target.config, cache=replace(target.config.cache, enabled=False)))

        # Auto-detect baseline when the config doesn't specify one but the default
        # file exists (common CI setup).
        if target.config.baseline is None:
            default_baseline = Path(".slopsentinel-baseline.json")
            if (target.project_root / default_baseline).exists():
                target = replace(target, config=replace(target.config, baseline=str(default_baseline)))

        files = discover_files(target)
        result = audit_files(target, files=files, changed_lines=None, apply_baseline=True, record_history=False)
    except Exception as exc:
        err_console.print(f"CI scan failed: {exc}")
        raise typer.Exit(code=2) from exc

    _emit_output(
        fmt,
        summary=result.summary,
        project_root=result.target.project_root,
        console=console,
        allow_github=True,
        show_details=not settings["quiet"],
    )

    if update_baseline:
        # Re-scan without applying baseline to capture the current full state.
        raw = audit_files(result.target, files=list(result.files), changed_lines=None, apply_baseline=False, record_history=False)
        baseline = build_baseline(list(raw.summary.violations), project_root=result.target.project_root)

        spec = Path(result.target.config.baseline) if result.target.config.baseline else Path(".slopsentinel-baseline.json")
        baseline_path = _resolve_under_root(result.target.project_root, spec)
        if baseline_path is None:
            err_console.print("Baseline output must be within the project root.")
            raise typer.Exit(code=2)
        save_baseline(baseline, baseline_path)
        return

    if result.summary.score < int(fail_under):
        raise typer.Exit(code=1)


@app.command()
def watch(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            help="File or directory to watch for changes (default: current directory).",
        ),
    ] = Path("."),
    debounce: Annotated[
        float,
        typer.Option("--debounce", min=0.0, help="Debounce window in seconds before re-scanning.", show_default=True),
    ] = 0.5,
    scoring_profile: Annotated[
        str | None,
        typer.Option("--profile", "--scoring-profile", help="Override scoring profile for this run: default, strict, lenient."),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Disable cache usage for this run (even if enabled in config)."),
    ] = False,
) -> None:
    """
    Watch for file changes and re-scan incrementally.

    Requires `watchdog` (install via `pip install "slopsentinel[watch]"`).
    """

    import queue
    import time
    from collections import defaultdict
    from typing import Any, Protocol, cast

    settings = _cli_settings()
    normalized_profile = scoring_profile.strip().lower() if isinstance(scoring_profile, str) and scoring_profile else None
    if normalized_profile is not None and normalized_profile not in {"default", "strict", "lenient"}:
        raise typer.BadParameter("Unsupported scoring profile. Use: default, strict, lenient.")

    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError as exc:  # pragma: no cover (depends on optional extra)
        err_console.print("watch requires watchdog. Install via: pip install \"slopsentinel[watch]\"")
        raise typer.Exit(code=2) from exc

    from rich.console import Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    from slopsentinel.audit import audit_files
    from slopsentinel.scanner import prepare_target
    from slopsentinel.utils import safe_relpath
    from slopsentinel.watch import DebouncedPathBatcher, should_watch_path

    target = prepare_target(path)
    if normalized_profile is not None:
        target = replace(target, config=replace(target.config, scoring=replace(target.config.scoring, profile=normalized_profile)))
    if no_cache and target.config.cache.enabled:
        target = replace(target, config=replace(target.config, cache=replace(target.config.cache, enabled=False)))

    watch_root = target.scan_path if target.scan_path.is_dir() else target.scan_path.parent

    q: queue.Queue[Path] = queue.Queue()

    class _Handler(FileSystemEventHandler):
        def _emit(self, raw_path: str) -> None:
            p = Path(raw_path)
            if should_watch_path(target, p):
                q.put(p)

        def on_created(self, event: Any) -> None:
            if getattr(event, "is_directory", False):
                return
            self._emit(str(getattr(event, "src_path", "")))

        def on_modified(self, event: Any) -> None:
            if getattr(event, "is_directory", False):
                return
            self._emit(str(getattr(event, "src_path", "")))

        def on_moved(self, event: Any) -> None:
            if getattr(event, "is_directory", False):
                return
            dest = getattr(event, "dest_path", None)
            if isinstance(dest, str) and dest:
                self._emit(dest)

    class _ObserverProto(Protocol):
        def schedule(self, event_handler: Any, path: str, *, recursive: bool) -> object: ...

        def start(self) -> None: ...

        def stop(self) -> None: ...

        def join(self) -> None: ...

    observer = cast(_ObserverProto, Observer())
    observer.schedule(_Handler(), str(watch_root), recursive=True)

    last_summary: ScanSummary | None = None

    def _render(summary: ScanSummary, *, changed_files: tuple[Path, ...]) -> Panel:
        header = Text()
        header.append("SlopSentinel watch", style="bold")
        header.append(" — ", style="dim")
        header.append(str(safe_relpath(watch_root, target.project_root)), style="dim")

        meta = Text()
        meta.append(f"Changed: {len(changed_files)} file(s)  ", style="dim")
        meta.append(f"Scanned: {summary.files_scanned}  ", style="dim")
        meta.append(f"Score: {summary.score}/100", style="bold")

        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("File", overflow="fold")
        table.add_column("Line", justify="right", style="dim")
        table.add_column("Rule", style="bold")
        table.add_column("Severity")
        table.add_column("Message", overflow="fold")

        by_file: dict[str, list[tuple[int, str, str, str]]] = defaultdict(list)
        repo_level: list[tuple[str, str, str]] = []
        for v in summary.violations:
            if v.location is None or v.location.path is None or v.location.start_line is None:
                repo_level.append((v.rule_id, v.severity, v.message))
                continue
            by_file[safe_relpath(v.location.path, target.project_root)].append(
                (int(v.location.start_line), v.rule_id, v.severity, v.message)
            )

        for rule_id, sev, msg in repo_level:
            table.add_row("-", "-", rule_id, sev, msg)

        # Keep this bounded so `watch` stays responsive in noisy repos.
        rows = 0
        for file_path in sorted(by_file):
            for line, rule_id, sev, msg in sorted(by_file[file_path]):
                table.add_row(file_path, str(line), rule_id, sev, msg)
                rows += 1
                if rows >= 50:
                    break
            if rows >= 50:
                break

        details = Group(header, meta, table if not settings["quiet"] else Text(""))
        return Panel(details, border_style="cyan")

    try:
        observer.start()
        batcher = DebouncedPathBatcher(debounce_seconds=float(debounce))

        with Live(
            Panel(Text(f"Watching {safe_relpath(watch_root, target.project_root)}…", style="dim"), border_style="cyan"),
            console=console,
            refresh_per_second=4,
        ) as live:
            while True:
                # Wait for the first event in a batch.
                p = q.get()
                batcher.add(p, now=time.monotonic())

                while True:
                    timeout = batcher.seconds_until_ready(now=time.monotonic())
                    if timeout <= 0.0:
                        break
                    try:
                        p2 = q.get(timeout=timeout)
                    except queue.Empty:
                        break
                    batcher.add(p2, now=time.monotonic())

                changed = tuple(sorted({p.resolve() for p in batcher.drain() if p.exists()}))
                if not changed:
                    continue

                if settings["verbose"]:
                    logger.debug("watch batch: %d file(s)", len(changed))

                result = audit_files(
                    target,
                    files=list(changed),
                    changed_lines=None,
                    apply_baseline=True,
                    record_history=False,
                )
                last_summary = result.summary
                live.update(_render(result.summary, changed_files=changed))

    except KeyboardInterrupt:
        pass
    finally:
        try:
            observer.stop()
        except Exception:
            pass
        try:
            observer.join()
        except Exception:
            pass

    if last_summary is not None and not settings["quiet"]:
        console.print(_render(last_summary, changed_files=()))


@app.command()
def diff(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Project directory (default: current directory).",
        ),
    ] = Path("."),
    base: Annotated[
        str,
        typer.Option("--base", help="Git base ref/sha to diff against (default: main)."),
    ] = "main",
    head: Annotated[
        str,
        typer.Option("--head", help="Git head ref/sha to diff against (default: HEAD)."),
    ] = "HEAD",
    staged: Annotated[
        bool,
        typer.Option("--staged", help="Diff against staged changes (index) instead of refs."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: terminal, json, sarif, html, markdown, github.", show_default=True),
    ] = "terminal",
    threshold: Annotated[
        int | None,
        typer.Option("--threshold", min=0, max=100, help="Mark as slop if score is below this threshold (0-100)."),
    ] = None,
    fail_under: Annotated[
        int | None,
        typer.Option("--fail-under", min=0, max=100, help="Shortcut for --threshold N --fail-on-slop (CI-friendly)."),
    ] = None,
    fail_on_slop: Annotated[
        bool | None,
        typer.Option(
            "--fail-on-slop/--no-fail-on-slop",
            help="Exit non-zero when score is below threshold (default: use config).",
            show_default=False,
        ),
    ] = None,
    scoring_profile: Annotated[
        str | None,
        typer.Option("--profile", "--scoring-profile", help="Override scoring profile for this run: default, strict, lenient."),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Disable cache usage for this run (even if enabled in config)."),
    ] = False,
) -> None:
    from slopsentinel.git import GitError
    from slopsentinel.gitdiff import changed_lines_between, changed_lines_staged

    settings = _cli_settings()
    normalized_profile = scoring_profile.strip().lower() if isinstance(scoring_profile, str) and scoring_profile else None
    if normalized_profile is not None and normalized_profile not in {"default", "strict", "lenient"}:
        raise typer.BadParameter("Unsupported scoring profile. Use: default, strict, lenient.")
    try:
        if staged:
            changed = changed_lines_staged(cwd=path, scope=path)
        else:
            changed = changed_lines_between(base, head, cwd=path, scope=path)
    except GitError as exc:
        console.print(f"git diff failed: {exc}")
        raise typer.Exit(code=2) from exc

    result = _audit_with_optional_progress(
        path,
        changed_lines=changed,
        apply_baseline=True,
        record_history=True,
        show_progress=settings["progress"] and not settings["quiet"] and output_format.strip().lower() == "terminal",
        verbose=settings["verbose"],
        scoring_profile=normalized_profile,
        no_cache=no_cache,
    )
    effective_threshold = (
        fail_under
        if fail_under is not None
        else (threshold if threshold is not None else result.target.config.threshold)
    )
    effective_fail_on_slop = (
        True
        if fail_under is not None
        else (fail_on_slop if fail_on_slop is not None else result.target.config.fail_on_slop)
    )

    _emit_output(
        output_format,
        summary=result.summary,
        project_root=result.target.project_root,
        console=console,
        allow_github=True,
        show_details=not settings["quiet"],
    )

    if result.summary.score < effective_threshold and effective_fail_on_slop:
        raise typer.Exit(code=1)


@app.command()
def deslop(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            help="File or directory to clean up (mechanical, safe transformations only).",
        ),
    ],
    backup: Annotated[
        bool,
        typer.Option("--backup", help="Create a .slopsentinel.bak backup before writing."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Don't write changes; only print a unified diff."),
    ] = False,
    check: Annotated[
        bool,
        typer.Option("--check", help="Exit non-zero if any files would be modified."),
    ] = False,
) -> None:
    settings = _cli_settings()
    effective_dry_run = dry_run or check

    if path.is_file():
        result = deslop_file(path, backup=backup, dry_run=effective_dry_run)
        if not result.changed:
            if not settings["quiet"]:
                console.print("No changes needed.")
            return
        if result.diff and dry_run:
            typer.echo(result.diff)
        if check:
            raise typer.Exit(code=1)
        if result.diff and not dry_run:
            typer.echo(result.diff)
        return

    from slopsentinel.scanner import discover_files, prepare_target
    from slopsentinel.utils import safe_relpath

    target = prepare_target(path)
    files = discover_files(target)
    changed_files: list[Path] = []
    diffs: list[str] = []
    for file_path in files:
        res = deslop_file(file_path, backup=backup, dry_run=effective_dry_run)
        if not res.changed:
            continue
        changed_files.append(res.path)
        if dry_run and res.diff:
            diffs.append(res.diff)

    if diffs:
        typer.echo("\n".join(diffs))

    if changed_files and not settings["quiet"]:
        console.print(f"Changed {len(changed_files)} file(s):")
        for file_path in changed_files:
            console.print(f"- {safe_relpath(file_path, target.project_root)}")
    elif not changed_files and not settings["quiet"]:
        console.print("No changes needed.")

    if check and changed_files:
        raise typer.Exit(code=1)


@app.command()
def fix(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            help="File or directory to scan + auto-fix (default: current directory).",
        ),
    ] = Path("."),
    backup: Annotated[
        bool,
        typer.Option("--backup", help="Create a .slopsentinel.bak backup before writing."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Don't write changes; only print a unified diff."),
    ] = False,
) -> None:
    """
    Apply conservative, rule-level auto-fixes.

    Currently limited to mechanical comment-only fixes (e.g. A03/A06/A10/D01/C09).
    """

    result = autofix_path(path, backup=backup, dry_run=dry_run)
    if not result.changed_files:
        console.print("No changes needed.")
        return

    diff = result.diff
    if diff:
        typer.echo(diff)


@app.command()
def baseline(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            help="File or directory to scan when generating a baseline (default: current directory).",
        ),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Baseline output path (default: config baseline or .slopsentinel-baseline.json)."),
    ] = None,
) -> None:
    """
    Generate a baseline file to suppress existing findings in full-repo scans.

    The baseline is only applied for `scan` (full scan). `diff` scans already
    focus on changed lines and ignore baseline by default.
    """

    result = audit_path(path, apply_baseline=False, record_history=False)
    baseline = build_baseline(list(result.summary.violations), project_root=result.target.project_root)

    if output is not None:
        spec = output
    elif result.target.config.baseline:
        spec = Path(result.target.config.baseline)
    else:
        spec = Path(".slopsentinel-baseline.json")

    baseline_path = _resolve_under_root(result.target.project_root, spec)
    if baseline_path is None:
        raise typer.BadParameter("Baseline output must be within the project root.")

    save_baseline(baseline, baseline_path)
    console.print(f"Wrote baseline with {len(baseline.file_entries) + len(baseline.repo_entries)} entries: {baseline_path}")


@app.command()
def trend(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Project directory (default: current directory).",
        ),
    ] = Path("."),
    last: Annotated[
        int,
        typer.Option("--last", min=1, max=200, help="Number of recent runs to show."),
    ] = 10,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: terminal, json, html.", show_default=True),
    ] = "terminal",
    min_score: Annotated[
        int | None,
        typer.Option("--min-score", min=0, max=100, help="Exit non-zero if the latest score is below this value."),
    ] = None,
    fail_on_regression: Annotated[
        bool,
        typer.Option("--fail-on-regression", help="Exit non-zero if the latest score regresses vs the previous run."),
    ] = False,
    max_drop: Annotated[
        int | None,
        typer.Option("--max-drop", min=0, max=100, help="Exit non-zero if the latest score drops by more than this amount."),
    ] = None,
) -> None:
    """
    Show score history and trend for a project.

    History recording is opt-in via `[tool.slopsentinel.history] enabled = true`.
    """

    from slopsentinel.history import (
        load_history,
        render_trend_html,
        render_trend_json,
        render_trend_terminal,
    )
    from slopsentinel.scanner import prepare_target

    target = prepare_target(path)
    spec = Path(target.config.history.path)
    history_path = _resolve_under_root(target.project_root, spec)
    if history_path is None:
        raise typer.BadParameter("History path must be within the project root.")

    entries = load_history(history_path)
    normalized = output_format.strip().lower()
    if normalized == "terminal":
        console.print(render_trend_terminal(entries, last=last))
    elif normalized == "json":
        typer.echo(render_trend_json(entries, last=last))
    elif normalized == "html":
        typer.echo(render_trend_html(entries, last=last))
    else:
        raise typer.BadParameter("Unsupported format. Use: terminal, json, html.")

    recent = entries[-last:]
    if not recent:
        return

    latest = recent[-1].score
    if min_score is not None and latest < min_score:
        raise typer.Exit(code=1)
    if fail_on_regression and len(recent) >= 2:
        if latest < recent[-2].score:
            raise typer.Exit(code=1)
    if max_drop is not None and len(recent) >= 2:
        drop = recent[-2].score - latest
        if drop > max_drop:
            raise typer.Exit(code=1)


@app.command()
def lsp() -> None:
    """
    Run a minimal Language Server Protocol (LSP) server over stdio.

    This is intended for IDE integrations that want real-time SlopSentinel diagnostics.
    """

    from slopsentinel.lsp import run_stdio_server

    run_stdio_server()


def _resolve_under_root(root: Path, spec: Path) -> Path | None:
    candidate = spec if spec.is_absolute() else (root / spec)
    try:
        candidate_resolved = candidate.resolve()
        root_resolved = root.resolve()
        candidate_resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate_resolved
