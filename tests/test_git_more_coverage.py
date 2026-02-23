from __future__ import annotations

from pathlib import Path

from slopsentinel.git import git_check_call, git_check_output, git_root


def test_git_helpers_check_call_and_output(tmp_path: Path) -> None:
    git_check_call(["init"], cwd=tmp_path)
    assert (tmp_path / ".git").is_dir()

    inside = git_check_output(["rev-parse", "--is-inside-work-tree"], cwd=tmp_path).strip().lower()
    assert inside == "true"

    root = git_root(cwd=tmp_path)
    assert root is not None
    assert root.resolve() == tmp_path.resolve()

