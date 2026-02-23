from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from slopsentinel import action as action_mod
from slopsentinel.audit import AuditResult
from slopsentinel.config import CacheConfig, HistoryConfig, RulesConfig, SlopSentinelConfig
from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation
from slopsentinel.git import GitError
from slopsentinel.scanner import ScanTarget


def _summary(*, score: int, violations: tuple[Violation, ...] = ()) -> ScanSummary:
    return ScanSummary(
        files_scanned=1,
        violations=violations,
        score=score,
        breakdown=DimensionBreakdown(
            fingerprint=0,
            quality=0,
            hallucination=0,
            maintainability=0,
            security=0,
        ),
    )


@pytest.mark.parametrize(
    ("rules_spec", "expected_enable"),
    [
        ("all", "all"),
        ("claude,generic", ("claude", "generic")),
    ],
)
def test_override_target_preserves_non_action_config_fields(
    tmp_path: Path,
    rules_spec: str,
    expected_enable: object,
) -> None:
    cfg = SlopSentinelConfig(
        threshold=10,
        fail_on_slop=False,
        rules=RulesConfig(enable=("cursor",)),
        baseline=".slopsentinel-baseline.json",
        cache=CacheConfig(enabled=True, path=".slopsentinel/cache.json"),
        history=HistoryConfig(enabled=True, path=".slopsentinel/history.json", max_entries=50),
        plugins=("my_rules",),
    )
    target = ScanTarget(project_root=tmp_path, scan_path=tmp_path, config=cfg)

    updated = action_mod._override_target(target, threshold=55, fail_on_slop=True, rules_spec=rules_spec)
    assert updated.config.threshold == 55
    assert updated.config.fail_on_slop is True
    assert updated.config.rules.enable == expected_enable

    # Ensure action inputs don't accidentally drop unrelated config blocks.
    assert updated.config.baseline == cfg.baseline
    assert updated.config.cache == cfg.cache
    assert updated.config.history == cfg.history
    assert updated.config.plugins == cfg.plugins


def test_write_outputs_writes_expected_lines(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))

    action_mod._write_outputs(_summary(score=42), sarif_path="report.sarif")
    text = out.read_text(encoding="utf-8")
    assert "score=42" in text
    assert "files_scanned=1" in text
    assert "sarif_path=report.sarif" in text


def test_action_main_non_pr_writes_outputs(tmp_path: Path, monkeypatch, capsys) -> None:
    old_cwd = Path.cwd()
    workspace = tmp_path

    try:
        monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
        monkeypatch.setenv("GITHUB_OUTPUT", str(workspace / "out.txt"))
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(workspace / "summary.md"))
        monkeypatch.setenv("INPUT_THRESHOLD", "60")
        monkeypatch.setenv("INPUT_COMMENT", "false")
        monkeypatch.setenv("INPUT_SARIF", "true")
        monkeypatch.setenv("INPUT_SARIF_PATH", "slopsentinel.sarif")

        target = ScanTarget(project_root=workspace, scan_path=workspace, config=SlopSentinelConfig())
        monkeypatch.setattr(action_mod, "prepare_target", lambda _: target)
        monkeypatch.setattr(action_mod, "discover_files", lambda _: [workspace / "src" / "app.py"])

        v = Violation(rule_id="A01", severity="info", message="repo", dimension="fingerprint", location=None)
        audit = AuditResult(target=target, files=(), summary=_summary(score=100, violations=(v,)))
        monkeypatch.setattr(action_mod, "audit_files", lambda *_args, **_kwargs: audit)
        monkeypatch.setattr(action_mod, "_maybe_write_sarif", lambda **_kwargs: "slopsentinel.sarif")

        action_mod.main()

        out_text = (workspace / "out.txt").read_text(encoding="utf-8")
        assert "score=100" in out_text
        assert "sarif_path=slopsentinel.sarif" in out_text
        assert "SlopSentinel report" in (workspace / "summary.md").read_text(encoding="utf-8")

        stdout = capsys.readouterr().out
        assert "::notice::A01 repo" in stdout
    finally:
        os.chdir(old_cwd)


def test_action_main_pr_posts_comments(tmp_path: Path, monkeypatch) -> None:
    old_cwd = Path.cwd()
    workspace = tmp_path
    (workspace / "src").mkdir(parents=True, exist_ok=True)

    event_path = workspace / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 7,
                    "base": {"sha": "base-sha"},
                    "head": {"sha": "head-sha"},
                }
            }
        ),
        encoding="utf-8",
    )

    posted: dict[str, object] = {}

    try:
        monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("INPUT_COMMENT", "true")
        monkeypatch.setenv("INPUT_GITHUB_TOKEN", "token")
        monkeypatch.setenv("INPUT_SARIF", "false")

        target = ScanTarget(project_root=workspace, scan_path=workspace, config=SlopSentinelConfig())
        monkeypatch.setattr(action_mod, "prepare_target", lambda _: target)
        file_path = workspace / "src" / "app.py"
        monkeypatch.setattr(action_mod, "discover_files", lambda _: [file_path])
        monkeypatch.setattr(action_mod, "_ensure_git_object", lambda _sha: None)
        monkeypatch.setattr(action_mod, "changed_lines_between", lambda *_args, **_kwargs: {file_path: {1}})

        v = Violation(
            rule_id="A03",
            severity="warn",
            message="msg",
            dimension="fingerprint",
            location=Location(path=file_path, start_line=1, start_col=1),
        )
        audit = AuditResult(target=target, files=(), summary=_summary(score=100, violations=(v,)))
        monkeypatch.setattr(action_mod, "audit_files", lambda *_args, **_kwargs: audit)

        def fake_post_pull_request_comments(**kwargs) -> None:
            posted.update(kwargs)

        monkeypatch.setattr(action_mod, "_post_pull_request_comments", fake_post_pull_request_comments)

        action_mod.main()

        assert posted["repository"] == "owner/repo"
        assert posted["pull_number"] == 7
        assert posted["commit_id"] == "head-sha"
        assert isinstance(posted["violations"], list) and posted["violations"]
    finally:
        os.chdir(old_cwd)


def test_action_main_fails_when_below_threshold(tmp_path: Path, monkeypatch) -> None:
    old_cwd = Path.cwd()
    workspace = tmp_path

    try:
        monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
        monkeypatch.setenv("INPUT_THRESHOLD", "60")
        monkeypatch.setenv("INPUT_FAIL_ON_SLOP", "true")
        monkeypatch.setenv("INPUT_COMMENT", "false")
        monkeypatch.setenv("INPUT_SARIF", "false")

        target = ScanTarget(project_root=workspace, scan_path=workspace, config=SlopSentinelConfig())
        monkeypatch.setattr(action_mod, "prepare_target", lambda _: target)
        monkeypatch.setattr(action_mod, "discover_files", lambda _: [])
        audit = AuditResult(target=target, files=(), summary=_summary(score=0))
        monkeypatch.setattr(action_mod, "audit_files", lambda *_args, **_kwargs: audit)

        with pytest.raises(SystemExit) as excinfo:
            action_mod.main()
        assert excinfo.value.code == 1
    finally:
        os.chdir(old_cwd)


def test_git_helpers_cover_common_paths(monkeypatch) -> None:
    monkeypatch.setattr(action_mod, "git_check_output", lambda *_args, **_kwargs: "origin\nupstream\n")
    assert action_mod._git_remote() == "origin"

    def raise_git(*_args, **_kwargs):
        raise GitError("boom")

    monkeypatch.setattr(action_mod, "git_check_call", raise_git)
    assert action_mod._git_has_object("deadbeef") is False
