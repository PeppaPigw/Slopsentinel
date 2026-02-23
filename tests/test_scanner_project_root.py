from __future__ import annotations

from pathlib import Path

from slopsentinel.scanner import prepare_target


def test_prepare_target_prefers_nearest_pyproject_in_parents(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "repo"
    nested = project_root / "services" / "api"
    nested.mkdir(parents=True)
    (project_root / "pyproject.toml").write_text("[tool.slopsentinel]\nthreshold = 42\n", encoding="utf-8")

    # Defensive: ensure we don't accidentally try to read real git state.
    monkeypatch.setattr("slopsentinel.scanner.git_root", lambda *_args, **_kwargs: None)

    target = prepare_target(nested)
    assert target.project_root == project_root.resolve()
    assert target.config.threshold == 42


def test_prepare_target_falls_back_to_git_root_when_no_pyproject(tmp_path: Path, monkeypatch) -> None:
    start = tmp_path / "repo" / "src"
    start.mkdir(parents=True)
    repo_root = tmp_path / "repo"

    monkeypatch.setattr("slopsentinel.scanner.git_root", lambda *_args, **_kwargs: repo_root)

    target = prepare_target(start)
    assert target.project_root == repo_root.resolve()


def test_prepare_target_uses_start_dir_when_no_pyproject_or_git(tmp_path: Path, monkeypatch) -> None:
    start = tmp_path / "repo" / "src"
    start.mkdir(parents=True)

    monkeypatch.setattr("slopsentinel.scanner.git_root", lambda *_args, **_kwargs: None)

    target = prepare_target(start)
    assert target.project_root == start.resolve()

