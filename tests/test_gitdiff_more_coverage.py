from __future__ import annotations

from pathlib import Path

import pytest

from slopsentinel.git import GitError
from slopsentinel.gitdiff import changed_lines_between, changed_lines_since, changed_lines_staged


def test_changed_lines_since_delegates_to_changed_lines_between(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    calls: list[tuple[str, str, Path]] = []

    def fake_between(base: str, head: str, *, cwd: Path, scope: Path | None = None) -> dict[Path, set[int]]:
        assert scope is None
        calls.append((base, head, cwd))
        return {repo_root / "a.py": {1}}

    monkeypatch.setattr("slopsentinel.gitdiff.changed_lines_between", fake_between)

    result = changed_lines_since("BASE", cwd=repo_root)
    assert result == {repo_root / "a.py": {1}}
    assert calls == [("BASE", "HEAD", repo_root)]


def test_changed_lines_staged_pathspec_and_devnull_and_zero_count(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    scope = repo_root / "sub"
    repo_root.mkdir()
    scope.mkdir()

    def fake_check_output(cmd: list[str], *, cwd: str, stderr, text: bool) -> str:  # type: ignore[no-untyped-def]
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return str(repo_root)

        if cmd[:2] == ["git", "diff"]:
            assert cmd == ["git", "diff", "--cached", "--unified=0", "--no-color", "--", "sub"]
            assert cwd == str(repo_root)
            return "\n".join(
                [
                    # Deleted file path should be ignored.
                    "diff --git a/deleted.py b/deleted.py",
                    "+++ /dev/null",
                    "@@ -1,1 +0,0 @@",
                    "-gone",
                    "",
                    # Zero-count hunks should be ignored.
                    "diff --git a/sub/foo.py b/sub/foo.py",
                    "+++ b/sub/foo.py",
                    "@@ -1,1 +1,0 @@",
                    "",
                    # Normal hunk should be parsed.
                    "diff --git a/sub/bar.py b/sub/bar.py",
                    "+++ b/sub/bar.py",
                    "@@ -0,0 +3,2 @@",
                    "+line1",
                    "+line2",
                    "",
                ]
            )

        raise AssertionError(f"Unexpected subprocess.check_output call: {cmd!r}")

    monkeypatch.setattr("slopsentinel.git.subprocess.check_output", fake_check_output)

    result = changed_lines_staged(cwd=repo_root, scope=scope)
    assert result == {(repo_root / "sub" / "bar.py").resolve(): {3, 4}}


def test_changed_lines_between_scope_outside_root_does_not_append_pathspec(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()

    def fake_check_output(cmd: list[str], *, cwd: str, stderr, text: bool) -> str:  # type: ignore[no-untyped-def]
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return str(repo_root)

        if cmd[:2] == ["git", "diff"]:
            # Scope is not relative to repo root; pathspec should not be appended.
            assert cmd == ["git", "diff", "--unified=0", "--no-color", "BASE...HEAD", "--"]
            assert cwd == str(repo_root)
            return "\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "+++ b/foo.py",
                    "@@ -0,0 +1,1 @@",
                    "+x",
                    "",
                ]
            )

        raise AssertionError(f"Unexpected subprocess.check_output call: {cmd!r}")

    monkeypatch.setattr("slopsentinel.git.subprocess.check_output", fake_check_output)

    result = changed_lines_between("BASE", "HEAD", cwd=repo_root, scope=outside)
    assert result == {(repo_root / "foo.py").resolve(): {1}}


def test_changed_lines_between_pathspec_and_devnull_and_zero_count(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    scope = repo_root / "src"
    repo_root.mkdir()
    scope.mkdir()

    def fake_check_output(cmd: list[str], *, cwd: str, stderr, text: bool) -> str:  # type: ignore[no-untyped-def]
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return str(repo_root)

        if cmd[:2] == ["git", "diff"]:
            assert cmd == ["git", "diff", "--unified=0", "--no-color", "BASE...HEAD", "--", "src"]
            assert cwd == str(repo_root)
            return "\n".join(
                [
                    "diff --git a/deleted.py b/deleted.py",
                    "+++ /dev/null",
                    "@@ -1,1 +0,0 @@",
                    "-gone",
                    "",
                    "diff --git a/src/foo.py b/src/foo.py",
                    "+++ b/src/foo.py",
                    "@@ -1,1 +1,0 @@",
                    "",
                    "diff --git a/src/bar.py b/src/bar.py",
                    "+++ b/src/bar.py",
                    "@@ -0,0 +10,1 @@",
                    "+x",
                    "",
                ]
            )

        raise AssertionError(f"Unexpected subprocess.check_output call: {cmd!r}")

    monkeypatch.setattr("slopsentinel.git.subprocess.check_output", fake_check_output)

    result = changed_lines_between("BASE", "HEAD", cwd=repo_root, scope=scope)
    assert result == {(repo_root / "src" / "bar.py").resolve(): {10}}


def test_changed_lines_between_propagates_git_error(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_check_output(cmd: list[str], *, cwd: str, stderr, text: bool) -> str:  # type: ignore[no-untyped-def]
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return str(repo_root)
        raise GitError("boom")

    monkeypatch.setattr("slopsentinel.git.subprocess.check_output", fake_check_output)

    with pytest.raises(GitError):
        changed_lines_between("BASE", "HEAD", cwd=repo_root)

