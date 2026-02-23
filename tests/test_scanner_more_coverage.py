from __future__ import annotations

from pathlib import Path

from slopsentinel.config import IgnoreConfig, SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.scanner import (
    ScanTarget,
    build_file_context,
    build_file_context_from_text,
    build_file_contexts,
    build_project_context,
    discover_files,
    resolve_worker_count,
)


def test_resolve_worker_count_more_branches() -> None:
    assert resolve_worker_count("auto", default=3, max_workers=10) == 3
    assert resolve_worker_count("", default=3, max_workers=10) == 3
    assert resolve_worker_count("not-an-int", default=3, max_workers=10) == 3
    assert resolve_worker_count("0", default=3, max_workers=10) == 3


def test_discover_files_file_paths_skip_and_ignore(tmp_path: Path) -> None:
    txt = tmp_path / "note.txt"
    txt.write_text("hello\n", encoding="utf-8")

    ignored = tmp_path / "ignored.py"
    ignored.write_text("x = 1\n", encoding="utf-8")

    cfg = SlopSentinelConfig(languages=("python",), ignore=IgnoreConfig(paths=("ignored.py",)))
    target_txt = ScanTarget(project_root=tmp_path, scan_path=txt, config=cfg)
    assert discover_files(target_txt) == []

    target_ignored = ScanTarget(project_root=tmp_path, scan_path=ignored, config=cfg)
    assert discover_files(target_ignored) == []


def test_discover_files_directory_branches(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "skip.py").write_text("x = 2\n", encoding="utf-8")

    cfg = SlopSentinelConfig(languages=("python",), ignore=IgnoreConfig(paths=("skip.py",)))
    target = ScanTarget(project_root=root, scan_path=root, config=cfg)

    # Force `detect_language()` to return None for one file to cover the `lang is None` branch.
    def fake_detect_language(path: Path) -> str | None:
        if path.name == "a.py":
            return None
        return "python"

    monkeypatch.setattr("slopsentinel.scanner.detect_language", fake_detect_language)

    files = discover_files(target)
    assert files == []


def test_build_file_context_handles_oserror(tmp_path: Path, monkeypatch) -> None:
    cfg = SlopSentinelConfig(languages=("python",))
    target = ScanTarget(project_root=tmp_path, scan_path=tmp_path, config=cfg)
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")

    project = build_project_context(target, [path])

    def raise_oserror(self: Path, *args, **kwargs) -> str:  # type: ignore[no-untyped-def]
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", raise_oserror)
    assert build_file_context(project, path) is None


def test_build_file_context_from_text_python_syntax_error(tmp_path: Path) -> None:
    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(), config=SlopSentinelConfig())
    path = tmp_path / "bad.py"
    ctx = build_file_context_from_text(project, path, "def f(:\n")
    assert ctx is not None
    assert ctx.python_ast is None


def test_build_file_contexts_calls_callback_serial_and_parallel(tmp_path: Path) -> None:
    cfg = SlopSentinelConfig(languages=("python",))
    target = ScanTarget(project_root=tmp_path, scan_path=tmp_path, config=cfg)

    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("x = 1\n", encoding="utf-8")
    b.write_text("y = 2\n", encoding="utf-8")

    paths = [a, b]
    project = build_project_context(target, paths)

    seen: list[Path] = []

    def on_done(p: Path) -> None:
        seen.append(p)

    serial = build_file_contexts(project, paths, workers=1, on_path_done=on_done)
    assert [ctx.relative_path for ctx in serial] == ["a.py", "b.py"]
    assert seen == paths

    seen.clear()
    parallel = build_file_contexts(project, paths, workers=2, on_path_done=on_done)
    assert [ctx.relative_path for ctx in parallel] == ["a.py", "b.py"]
    assert seen == paths

