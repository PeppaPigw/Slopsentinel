from __future__ import annotations

import queue
import sys
import types
from pathlib import Path

from typer.testing import CliRunner

import slopsentinel.cli as cli_mod
from slopsentinel.audit import AuditResult
from slopsentinel.engine.types import DimensionBreakdown, Location, ScanSummary, Violation
from slopsentinel.scanner import ScanTarget


def test_watch_command_runs_single_batch_and_exits(tmp_path: Path, monkeypatch) -> None:
    # Enable cache in config so --no-cache exercises the disable path.
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
threshold = 60

[tool.slopsentinel.cache]
enabled = true
""".lstrip(),
        encoding="utf-8",
    )

    changed = tmp_path / "src" / "example.py"
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    # Provide a minimal watchdog shim so `slopsentinel watch` can run without the extra installed.
    class DummyObserver:
        def __init__(self) -> None:
            self._handler = None
            self._root = None

        def schedule(self, event_handler, path: str, *, recursive: bool) -> object:  # noqa: ANN001
            self._handler = event_handler
            self._root = Path(path)
            return object()

        def start(self) -> None:
            assert self._handler is not None
            assert self._root is not None
            event = types.SimpleNamespace(
                is_directory=False,
                src_path=str(changed),
                dest_path=str(changed),
            )
            # Exercise created/modified/moved handlers.
            self._handler.on_created(event)
            self._handler.on_modified(event)
            self._handler.on_moved(event)

        def stop(self) -> None:
            # Exercise the defensive stop/join exception handling in the CLI.
            raise RuntimeError("boom")

        def join(self) -> None:
            raise RuntimeError("boom")

    watchdog_events = types.ModuleType("watchdog.events")
    watchdog_events.FileSystemEventHandler = object
    watchdog_observers = types.ModuleType("watchdog.observers")
    watchdog_observers.Observer = DummyObserver
    watchdog_root = types.ModuleType("watchdog")
    monkeypatch.setitem(sys.modules, "watchdog", watchdog_root)
    monkeypatch.setitem(sys.modules, "watchdog.events", watchdog_events)
    monkeypatch.setitem(sys.modules, "watchdog.observers", watchdog_observers)

    # Avoid Rich Live rendering side-effects in tests.
    class DummyLive:
        def __init__(self, *_a, **_k) -> None:
            self.updated: list[object] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
            return False

        def update(self, renderable) -> None:  # noqa: ANN001
            self.updated.append(renderable)

    monkeypatch.setattr("rich.live.Live", DummyLive)

    # Make `seconds_until_ready()` positive (so the inner timeout get() path runs),
    # and ensure we never block on the queue in tests.
    monkeypatch.setattr("time.monotonic", lambda: 0.0)

    original_get = queue.Queue.get

    def patched_get(self, block: bool = True, timeout: float | None = None):  # noqa: ANN001
        try:
            return original_get(self, block=False)
        except queue.Empty:
            if timeout is not None:
                raise
            raise KeyboardInterrupt() from None

    monkeypatch.setattr(queue.Queue, "get", patched_get)

    captured: dict[str, object] = {}

    def fake_audit_files(target: ScanTarget, *, files, changed_lines=None, apply_baseline=True, record_history=False, callbacks=None):  # noqa: ANN001
        captured["target"] = target
        captured["files"] = tuple(files)
        assert apply_baseline is True
        assert record_history is False

        v = Violation(
            rule_id="A03",
            severity="info",
            message="We need to ensure this is tested.",
            dimension="fingerprint",
            location=Location(path=changed, start_line=1, start_col=1, end_line=1, end_col=5),
        )
        v_repo = Violation(
            rule_id="X01",
            severity="info",
            message="Cross-file duplication detected.",
            dimension="maintainability",
            location=None,
        )
        summary = ScanSummary(
            files_scanned=len(files),
            violations=(v, v_repo),
            score=90,
            breakdown=DimensionBreakdown(fingerprint=1, quality=0, hallucination=0, maintainability=1, security=0),
            dominant_fingerprints=(),
        )
        return AuditResult(target=target, files=tuple(files), summary=summary)

    monkeypatch.setattr("slopsentinel.audit.audit_files", fake_audit_files)

    runner = CliRunner()
    res = runner.invoke(
        cli_mod.app,
        ["--verbose", "watch", str(tmp_path), "--debounce", "0.5", "--profile", "strict", "--no-cache"],
    )
    assert res.exit_code == 0, res.output

    target = captured["target"]
    assert isinstance(target, ScanTarget)
    assert target.config.scoring.profile == "strict"
    assert target.config.cache.enabled is False
    assert captured["files"] == (changed.resolve(),)
