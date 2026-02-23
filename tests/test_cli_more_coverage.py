from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

import slopsentinel.cli as cli_mod
from slopsentinel.audit import AuditResult
from slopsentinel.config import CacheConfig, ScoringConfig, SlopSentinelConfig
from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation
from slopsentinel.init import InitResult
from slopsentinel.scanner import ScanTarget


def _dummy_audit_result(project_root: Path, *, score: int = 100, cache_enabled: bool = False) -> AuditResult:
    config = SlopSentinelConfig(
        threshold=60,
        fail_on_slop=False,
        cache=CacheConfig(enabled=cache_enabled),
        scoring=ScoringConfig(profile="default"),
    )
    target = ScanTarget(project_root=project_root, scan_path=project_root, config=config)
    v = Violation(
        rule_id="A03",
        severity="info",
        message="We need to ensure this is tested.",
        dimension="fingerprint",
        location=Location(path=project_root / "src" / "example.py", start_line=1, start_col=1, end_line=1, end_col=10),
    )
    summary = ScanSummary(
        files_scanned=1,
        violations=(v,),
        score=int(score),
        breakdown=DimensionBreakdown(fingerprint=1, quality=0, hallucination=0, maintainability=0, security=0),
        dominant_fingerprints=(),
    )
    return AuditResult(target=target, files=(project_root,), summary=summary)


def test_version_flag_prints_version() -> None:
    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["--version"])
    assert res.exit_code == 0
    assert res.output.strip() == cli_mod.__version__


def test_cli_settings_defaults_without_click_context() -> None:
    settings = cli_mod._cli_settings()
    assert settings == {"verbose": False, "quiet": False, "progress": True}


def test_emit_output_rejects_unknown_format_without_github(tmp_path: Path) -> None:
    summary = _dummy_audit_result(tmp_path).summary
    with pytest.raises(typer.BadParameter):
        cli_mod._emit_output(
            "nope",
            summary=summary,
            project_root=tmp_path,
            console=Console(file=io.StringIO(), force_terminal=False),
            allow_github=False,
        )


@pytest.mark.parametrize("fmt", ["terminal", "html", "sarif", "markdown", "github"])
def test_scan_supports_multiple_output_formats(tmp_path: Path, monkeypatch, fmt: str) -> None:
    runner = CliRunner()
    monkeypatch.setattr("slopsentinel.cli._audit_with_optional_progress", lambda *_a, **_k: _dummy_audit_result(tmp_path))

    res = runner.invoke(cli_mod.app, ["--no-progress", "scan", str(tmp_path), "--format", fmt, "--threshold", "0"])
    assert res.exit_code == 0, res.output


def test_scan_fail_under_forces_fail_on_slop(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("slopsentinel.cli._audit_with_optional_progress", lambda *_a, **_k: _dummy_audit_result(tmp_path, score=0))

    res = runner.invoke(cli_mod.app, ["scan", str(tmp_path), "--format", "json", "--fail-under", "100"])
    assert res.exit_code == 1


def test_scan_rejects_unknown_scoring_profile(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["scan", str(tmp_path), "--format", "json", "--profile", "nope"])
    assert res.exit_code != 0


def test_diff_rejects_unknown_scoring_profile_before_git(tmp_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["diff", str(tmp_path), "--format", "json", "--profile", "nope"])
    assert res.exit_code != 0


def test_diff_reports_git_error_as_exit_code_2(tmp_path: Path, monkeypatch) -> None:
    from slopsentinel.git import GitError

    runner = CliRunner()
    monkeypatch.setattr("slopsentinel.gitdiff.changed_lines_between", lambda *_a, **_k: (_ for _ in ()).throw(GitError("no repo")))

    res = runner.invoke(cli_mod.app, ["diff", str(tmp_path), "--format", "terminal"])
    assert res.exit_code == 2
    assert "git diff failed" in res.output


def test_rules_terminal_output_and_unsupported_format(tmp_path: Path) -> None:
    runner = CliRunner()
    ok = runner.invoke(cli_mod.app, ["rules", str(tmp_path)])
    assert ok.exit_code == 0

    bad = runner.invoke(cli_mod.app, ["rules", str(tmp_path), "--format", "nope"])
    assert bad.exit_code != 0


def test_rules_plugin_load_error_exits_2(tmp_path: Path, monkeypatch) -> None:
    from slopsentinel.rules.plugins import PluginLoadError

    runner = CliRunner()
    monkeypatch.setattr("slopsentinel.rules.plugins.load_plugin_rules", lambda *_a, **_k: (_ for _ in ()).throw(PluginLoadError("boom")))
    res = runner.invoke(cli_mod.app, ["rules", str(tmp_path)])
    assert res.exit_code == 2
    assert "Failed to load plugins" in res.output


def test_explain_terminal_output_and_unsupported_format(tmp_path: Path) -> None:
    runner = CliRunner()
    ok = runner.invoke(cli_mod.app, ["explain", "A03", "--path", str(tmp_path)])
    assert ok.exit_code == 0
    assert "A03" in ok.output

    bad = runner.invoke(cli_mod.app, ["explain", "A03", "--path", str(tmp_path), "--format", "nope"])
    assert bad.exit_code != 0


def test_explain_plugin_load_error_exits_2(tmp_path: Path, monkeypatch) -> None:
    from slopsentinel.rules.plugins import PluginLoadError

    runner = CliRunner()
    monkeypatch.setattr("slopsentinel.rules.plugins.load_plugin_rules", lambda *_a, **_k: (_ for _ in ()).throw(PluginLoadError("boom")))
    res = runner.invoke(cli_mod.app, ["explain", "A03", "--path", str(tmp_path)])
    assert res.exit_code == 2
    assert "Failed to load plugins" in res.output


def test_init_interactive_prompts_are_exercised(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr("slopsentinel.init.detect_project_languages", lambda _p: ("python", "typescript"))

    confirms: list[bool] = [
        False,  # Use detected languages?
        True,  # Generate GitHub Actions workflow?
        True,  # Generate pre-commit?
    ]

    def fake_confirm(_text: str, *, default: bool = True) -> bool:
        return confirms.pop(0)

    prompts: list[str] = [
        "python,typescript",  # Languages prompt
        "strict",  # Scoring profile prompt
    ]

    def fake_prompt(_text: str, *, default: str = "") -> str:
        return prompts.pop(0)

    monkeypatch.setattr("typer.confirm", fake_confirm)
    monkeypatch.setattr("typer.prompt", fake_prompt)

    captured: dict[str, object] = {}

    def fake_init_project(options) -> InitResult:
        captured["options"] = options
        inside = tmp_path / "pyproject.toml"
        outside = tmp_path.parent / "outside.txt"
        return InitResult(
            changed_files=(inside, outside),
            messages=("Initialized.",),
        )

    monkeypatch.setattr("slopsentinel.cli.init_project", fake_init_project)

    res = runner.invoke(cli_mod.app, ["init", str(tmp_path), "--interactive"])
    assert res.exit_code == 0, res.output
    assert "Detected languages" in res.output
    assert "Changed files:" in res.output
    assert "outside.txt" in res.output

    options = captured["options"]
    assert options.project_dir == tmp_path.resolve()
    assert options.ci == "github"
    assert options.pre_commit is True
    assert options.languages == ("python", "typescript")
    assert options.scoring_profile == "strict"


def test_init_rejects_invalid_profile_and_unknown_languages(tmp_path: Path) -> None:
    runner = CliRunner()
    bad_profile = runner.invoke(cli_mod.app, ["init", str(tmp_path), "--scoring-profile", "nope"])
    assert bad_profile.exit_code != 0

    bad_lang = runner.invoke(cli_mod.app, ["init", str(tmp_path), "--languages", "python,wat"])
    assert bad_lang.exit_code != 0


def test_baseline_uses_configured_output_path(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "example.py").write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
baseline = ".slopsentinel/custom-baseline.json"
""".lstrip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["baseline", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert (tmp_path / ".slopsentinel" / "custom-baseline.json").exists()


def test_trend_terminal_html_unsupported_and_empty_history(tmp_path: Path) -> None:
    runner = CliRunner()

    empty = runner.invoke(cli_mod.app, ["trend", str(tmp_path), "--format", "terminal", "--last", "10"])
    assert empty.exit_code == 0
    assert "No history recorded yet" in empty.output

    # Create history and verify HTML branch.
    history_path = tmp_path / ".slopsentinel" / "history.json"
    payload = {
        "version": 1,
        "entries": [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "score": 90,
                "files_scanned": 1,
                "violations": 0,
                "breakdown": {"fingerprint": 35, "quality": 20, "hallucination": 20, "maintainability": 15, "security": 0},
            },
        ],
    }
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(payload), encoding="utf-8")

    html = runner.invoke(cli_mod.app, ["trend", str(tmp_path), "--format", "html", "--last", "1"])
    assert html.exit_code == 0
    assert "<!doctype html>" in html.output.lower()

    bad = runner.invoke(cli_mod.app, ["trend", str(tmp_path), "--format", "nope"])
    assert bad.exit_code != 0


def test_trend_enforces_regression_and_max_drop(tmp_path: Path) -> None:
    history_path = tmp_path / ".slopsentinel" / "history.json"
    payload = {
        "version": 1,
        "entries": [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "score": 90,
                "files_scanned": 1,
                "violations": 0,
                "breakdown": {"fingerprint": 35, "quality": 20, "hallucination": 20, "maintainability": 15, "security": 0},
            },
            {
                "timestamp": "2026-01-02T00:00:00Z",
                "score": 80,
                "files_scanned": 1,
                "violations": 0,
                "breakdown": {"fingerprint": 35, "quality": 20, "hallucination": 20, "maintainability": 15, "security": 0},
            },
        ],
    }
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(payload), encoding="utf-8")

    runner = CliRunner()
    reg = runner.invoke(cli_mod.app, ["trend", str(tmp_path), "--format", "terminal", "--last", "2", "--fail-on-regression"])
    assert reg.exit_code == 1

    drop = runner.invoke(cli_mod.app, ["trend", str(tmp_path), "--format", "terminal", "--last", "2", "--max-drop", "5"])
    assert drop.exit_code == 1


def test_trend_refuses_history_path_outside_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel.history]
enabled = true
path = "../outside.json"
""".lstrip(),
        encoding="utf-8",
    )
    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ["trend", str(tmp_path), "--format", "terminal"])
    assert res.exit_code != 0
    assert "History path must be within the project root" in res.output


def test_lsp_command_delegates_to_stdio_server(monkeypatch) -> None:
    runner = CliRunner()
    called: list[bool] = []

    monkeypatch.setattr("slopsentinel.lsp.run_stdio_server", lambda: called.append(True))
    res = runner.invoke(cli_mod.app, ["lsp"])
    assert res.exit_code == 0
    assert called == [True]


def test_deslop_file_and_directory_no_changes_paths(tmp_path: Path) -> None:
    runner = CliRunner()

    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")

    file_res = runner.invoke(cli_mod.app, ["deslop", str(clean)])
    assert file_res.exit_code == 0
    assert "No changes needed" in file_res.output

    dir_res = runner.invoke(cli_mod.app, ["deslop", str(tmp_path)])
    assert dir_res.exit_code == 0
    assert "No changes needed" in dir_res.output


def test_fix_prints_no_changes_needed_when_clean(tmp_path: Path) -> None:
    runner = CliRunner()
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")
    res = runner.invoke(cli_mod.app, ["fix", str(clean)])
    assert res.exit_code == 0
    assert "No changes needed" in res.output


def test_audit_with_optional_progress_exercises_progress_branch(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    file_a = tmp_path / "src" / "a.py"
    file_b = tmp_path / "src" / "b.py"

    target = _dummy_audit_result(tmp_path, cache_enabled=True).target
    monkeypatch.setattr("slopsentinel.scanner.prepare_target", lambda _p: target)
    monkeypatch.setattr("slopsentinel.scanner.discover_files", lambda _t: [file_a, file_b])

    class FakeProgress:
        def __init__(self, *args, **kwargs) -> None:
            self.advanced: list[tuple[int, int]] = []
            self.updated: list[tuple[int, int | None, int | None]] = []
            self._task = 0

        def add_task(self, _desc: str, *, total: int) -> int:
            self._task += 1
            return self._task

        def advance(self, task_id: int, advance: int) -> None:
            self.advanced.append((task_id, int(advance)))

        def update(self, task_id: int, *, total: int, completed: int) -> None:
            self.updated.append((task_id, int(total), int(completed)))

        def __enter__(self) -> FakeProgress:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr("rich.progress.Progress", FakeProgress)

    def fake_audit_files(target, *, files, changed_lines, apply_baseline, record_history, callbacks=None):
        assert callbacks is not None
        for p in files:
            callbacks.on_context_built(p)
        callbacks.on_file_contexts_ready(len(files))
        for p in files:
            callbacks.on_file_scanned(p)
        return _dummy_audit_result(tmp_path)

    monkeypatch.setattr("slopsentinel.cli.audit_files", fake_audit_files)

    result = cli_mod._audit_with_optional_progress(
        tmp_path,
        changed_lines=None,
        apply_baseline=True,
        record_history=False,
        show_progress=True,
        verbose=True,
        scoring_profile="strict",
        no_cache=True,
    )
    assert isinstance(result, AuditResult)


def test_audit_with_optional_progress_filters_changed_lines_to_discovered(tmp_path: Path, monkeypatch) -> None:
    discovered = tmp_path / "src" / "ok.py"
    extra = tmp_path / "src" / "nope.py"
    discovered.parent.mkdir(parents=True, exist_ok=True)

    target = _dummy_audit_result(tmp_path).target
    monkeypatch.setattr("slopsentinel.scanner.prepare_target", lambda _p: target)
    monkeypatch.setattr("slopsentinel.scanner.discover_files", lambda _t: [discovered])

    captured: dict[str, object] = {}

    def fake_audit_files(target, *, files, **kwargs):
        captured["files"] = tuple(files)
        return _dummy_audit_result(tmp_path)

    monkeypatch.setattr("slopsentinel.cli.audit_files", fake_audit_files)

    _ = cli_mod._audit_with_optional_progress(
        tmp_path,
        changed_lines={discovered: {1}, extra: {1}},
        apply_baseline=True,
        record_history=False,
        show_progress=False,
        verbose=False,
    )
    assert captured["files"] == (discovered,)
