from __future__ import annotations

from pathlib import Path

from slopsentinel.gitdiff import changed_lines_between, changed_lines_staged


def test_changed_lines_between_uses_base_and_head_and_parses_hunks(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "foo.py").write_text("print('x')\n", encoding="utf-8")

    calls: list[tuple[list[str], str]] = []

    def fake_check_output(cmd: list[str], *, cwd: str, stderr, text: bool) -> str:  # type: ignore[no-untyped-def]
        calls.append((cmd, cwd))

        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return str(repo_root)

        if cmd[:2] == ["git", "diff"]:
            assert cmd == ["git", "diff", "--unified=0", "--no-color", "BASE_SHA...HEAD_SHA", "--"]
            assert cwd == str(repo_root)
            return "\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "index 0000000..1111111 100644",
                    "--- a/foo.py",
                    "+++ b/foo.py",
                    "@@ -0,0 +1,2 @@",
                    "+line1",
                    "+line2",
                    "",
                ]
            )

        raise AssertionError(f"Unexpected subprocess.check_output call: {cmd!r}")

    monkeypatch.setattr("slopsentinel.git.subprocess.check_output", fake_check_output)

    result = changed_lines_between("BASE_SHA", "HEAD_SHA", cwd=repo_root)
    assert result == {(repo_root / "foo.py").resolve(): {1, 2}}

    assert calls[0][0] == ["git", "rev-parse", "--show-toplevel"]
    assert calls[1][0] == ["git", "diff", "--unified=0", "--no-color", "BASE_SHA...HEAD_SHA", "--"]


def test_changed_lines_staged_parses_cached_diff(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "foo.py").write_text("print('x')\n", encoding="utf-8")

    calls: list[tuple[list[str], str]] = []

    def fake_check_output(cmd: list[str], *, cwd: str, stderr, text: bool) -> str:  # type: ignore[no-untyped-def]
        calls.append((cmd, cwd))

        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return str(repo_root)

        if cmd[:2] == ["git", "diff"]:
            assert cmd == ["git", "diff", "--cached", "--unified=0", "--no-color", "--"]
            assert cwd == str(repo_root)
            return "\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "index 0000000..1111111 100644",
                    "--- a/foo.py",
                    "+++ b/foo.py",
                    "@@ -0,0 +1,2 @@",
                    "+line1",
                    "+line2",
                    "",
                ]
            )

        raise AssertionError(f"Unexpected subprocess.check_output call: {cmd!r}")

    monkeypatch.setattr("slopsentinel.git.subprocess.check_output", fake_check_output)

    result = changed_lines_staged(cwd=repo_root)
    assert result == {(repo_root / "foo.py").resolve(): {1, 2}}

    assert calls[0][0] == ["git", "rev-parse", "--show-toplevel"]
    assert calls[1][0] == ["git", "diff", "--cached", "--unified=0", "--no-color", "--"]
