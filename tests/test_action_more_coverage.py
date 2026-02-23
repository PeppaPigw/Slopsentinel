from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path

from slopsentinel import action as action_mod
from slopsentinel.config import RulesConfig, SlopSentinelConfig
from slopsentinel.git import GitError
from slopsentinel.scanner import ScanTarget


def test_override_target_empty_rules_spec_falls_back_to_all(tmp_path: Path) -> None:
    cfg = SlopSentinelConfig(rules=RulesConfig(enable=("cursor",)))
    target = ScanTarget(project_root=tmp_path, scan_path=tmp_path, config=cfg)
    updated = action_mod._override_target(target, threshold=60, fail_on_slop=False, rules_spec=" , ; ")
    assert updated.config.rules.enable == "all"


def test_action_main_pr_comment_missing_env_prints_warning(tmp_path: Path, monkeypatch, capsys) -> None:
    old_cwd = Path.cwd()
    workspace = tmp_path
    (workspace / "src").mkdir(parents=True, exist_ok=True)
    event_path = workspace / "event.json"
    event_path.write_text(
        json.dumps({"pull_request": {"number": 1, "base": {"sha": "base"}, "head": {"sha": "head"}}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("INPUT_COMMENT", "true")
    monkeypatch.setenv("INPUT_SARIF", "false")

    # Make the run deterministic and fast.
    target = ScanTarget(project_root=workspace, scan_path=workspace, config=SlopSentinelConfig())
    monkeypatch.setattr(action_mod, "prepare_target", lambda _: target)
    file_path = workspace / "src" / "app.py"
    file_path.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(action_mod, "discover_files", lambda *_args, **_kwargs: [file_path])
    monkeypatch.setattr(action_mod, "_ensure_git_object", lambda _sha: None)
    monkeypatch.setattr(action_mod, "changed_lines_between", lambda *_args, **_kwargs: {file_path: {1}})

    from slopsentinel.audit import AuditResult
    from slopsentinel.engine.types import DimensionBreakdown, ScanSummary

    summary = ScanSummary(
        files_scanned=1,
        violations=(),
        score=100,
        breakdown=DimensionBreakdown(fingerprint=0, quality=0, hallucination=0, maintainability=0, security=0),
    )
    monkeypatch.setattr(action_mod, "audit_files", lambda *_args, **_kwargs: AuditResult(target=target, files=(), summary=summary))

    try:
        action_mod.main()
    finally:
        os.chdir(old_cwd)

    stderr = capsys.readouterr().err
    assert "PR commenting requested" in stderr


def test_ensure_git_object_fetch_paths(monkeypatch) -> None:
    # Missing object + no remote: should no-op.
    monkeypatch.setattr(action_mod, "_git_has_object", lambda _sha: False)
    monkeypatch.setattr(action_mod, "_git_remote", lambda: None)

    called: list[list[str]] = []

    def fake_call(args: list[str], *, cwd: Path) -> None:
        called.append(args)

    monkeypatch.setattr(action_mod, "git_check_call", fake_call)
    action_mod._ensure_git_object("deadbeef")
    assert called == []

    # Missing object + remote present + fetch succeeds.
    monkeypatch.setattr(action_mod, "_git_remote", lambda: "origin")
    action_mod._ensure_git_object("deadbeef")
    assert called[-1] == ["fetch", "--no-tags", "--depth=1", "origin", "deadbeef"]

    # Missing object + remote present + fetch fails: should swallow.
    def raise_git(*_args, **_kwargs):
        raise GitError("boom")

    monkeypatch.setattr(action_mod, "git_check_call", raise_git)
    action_mod._ensure_git_object("deadbeef")


def test_git_helpers_more_branches(monkeypatch, tmp_path: Path) -> None:
    # _git_has_object True path.
    monkeypatch.setattr(action_mod, "git_check_call", lambda *_args, **_kwargs: None)
    assert action_mod._git_has_object("deadbeef") is True

    # _git_remote error and non-origin fallback.
    def raise_git(*_args, **_kwargs):
        raise GitError("boom")

    monkeypatch.setattr(action_mod, "git_check_output", raise_git)
    assert action_mod._git_remote() is None

    monkeypatch.setattr(action_mod, "git_check_output", lambda *_args, **_kwargs: "upstream\n")
    assert action_mod._git_remote() == "upstream"

    # _load_event JSON decode + non-dict paths.
    invalid = tmp_path / "event.json"
    invalid.write_text("{not-json", encoding="utf-8")
    assert action_mod._load_event(invalid) is None

    not_dict = tmp_path / "event2.json"
    not_dict.write_text("[]", encoding="utf-8")
    assert action_mod._load_event(not_dict) is None


def test_action_module_main_guard_runs(tmp_path: Path, monkeypatch) -> None:
    # Execute `slopsentinel.action` as a script to cover the __main__ guard.
    (tmp_path / "pyproject.toml").write_text("[tool.slopsentinel]\n", encoding="utf-8")

    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("INPUT_THRESHOLD", "0")
    monkeypatch.setenv("INPUT_FAIL_ON_SLOP", "false")
    monkeypatch.setenv("INPUT_COMMENT", "false")
    monkeypatch.setenv("INPUT_SARIF", "false")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    old_cwd = Path.cwd()
    try:
        # Avoid runpy's "already in sys.modules" warning by forcing a clean run.
        sys.modules.pop("slopsentinel.action", None)

        # No exception == success.
        runpy.run_module("slopsentinel.action", run_name="__main__")
    finally:
        os.chdir(old_cwd)
