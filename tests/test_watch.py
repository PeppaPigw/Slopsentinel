from __future__ import annotations

from pathlib import Path

from slopsentinel.scanner import prepare_target
from slopsentinel.watch import DebouncedPathBatcher, should_watch_path


def test_debounced_path_batcher_groups_paths_after_quiet_period(tmp_path: Path) -> None:
    batcher = DebouncedPathBatcher(debounce_seconds=0.5)
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"

    batcher.add(a, now=1.0)
    assert batcher.ready(now=1.4) is False
    batcher.add(b, now=1.4)
    assert batcher.ready(now=1.8) is False
    assert batcher.ready(now=1.9) is True
    drained = batcher.drain()
    assert drained == {a, b}
    assert batcher.ready(now=2.5) is False


def test_should_watch_path_requires_supported_extension_and_scope(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    py = tmp_path / "src" / "a.py"
    py.write_text("x = 1\n", encoding="utf-8")
    txt = tmp_path / "src" / "a.txt"
    txt.write_text("x\n", encoding="utf-8")

    target = prepare_target(tmp_path)
    assert should_watch_path(target, py) is True
    assert should_watch_path(target, txt) is False

    # When scanning a single file, only that file is considered.
    file_target = prepare_target(py)
    assert should_watch_path(file_target, py) is True
    other = tmp_path / "src" / "b.py"
    other.write_text("x = 1\n", encoding="utf-8")
    assert should_watch_path(file_target, other) is False


def test_should_watch_path_respects_ignore_patterns(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.ignore]
paths = ["src/"]
""".lstrip(),
        encoding="utf-8",
    )

    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    py = tmp_path / "src" / "a.py"
    py.write_text("x = 1\n", encoding="utf-8")

    target = prepare_target(tmp_path)
    assert should_watch_path(target, py) is False


def test_should_watch_path_rejects_paths_outside_scan_root(tmp_path: Path) -> None:
    target = prepare_target(tmp_path)
    outside = tmp_path.parent / "outside.py"
    assert should_watch_path(target, outside) is False


def test_should_watch_path_rejects_missing_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    target = prepare_target(tmp_path)
    missing = tmp_path / "src" / "missing.py"
    assert should_watch_path(target, missing) is False


def test_should_watch_path_handles_resolve_errors(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    py = tmp_path / "src" / "a.py"
    py.write_text("x = 1\n", encoding="utf-8")
    target = prepare_target(tmp_path)

    path_cls = type(tmp_path)
    original_resolve = path_cls.resolve

    def path_boom(self: Path, *args, **kwargs):  # noqa: ANN001
        if self == py:
            raise OSError("boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(path_cls, "resolve", path_boom)
    assert should_watch_path(target, py) is False


def test_should_watch_path_handles_scan_root_resolve_errors(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    py = tmp_path / "src" / "a.py"
    py.write_text("x = 1\n", encoding="utf-8")
    target = prepare_target(tmp_path)

    path_cls = type(tmp_path)
    original_resolve = path_cls.resolve
    scan_root = target.scan_path

    def scan_boom(self: Path, *args, **kwargs):  # noqa: ANN001
        if self == scan_root:
            raise OSError("boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(path_cls, "resolve", scan_boom)
    assert should_watch_path(target, py) is False


def test_should_watch_path_rejects_unknown_language_even_with_allowed_extension(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    py = tmp_path / "src" / "a.py"
    py.write_text("x = 1\n", encoding="utf-8")
    target = prepare_target(tmp_path)
    monkeypatch.setattr("slopsentinel.watch.detect_language", lambda _p: None)
    assert should_watch_path(target, py) is False
