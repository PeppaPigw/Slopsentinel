from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from slopsentinel.config import path_is_ignored
from slopsentinel.languages.registry import allowed_extensions, detect_language
from slopsentinel.scanner import ScanTarget


@dataclass(slots=True)
class DebouncedPathBatcher:
    """
    Collect file paths and flush them after a quiet period.

    This is intentionally small and dependency-free so it can be unit-tested
    without watchdog or threads.
    """

    debounce_seconds: float
    _pending: set[Path] = field(default_factory=set, init=False)
    _last_event_at: float | None = field(default=None, init=False)

    def add(self, path: Path, *, now: float) -> None:
        self._pending.add(path)
        self._last_event_at = float(now)

    def seconds_until_ready(self, *, now: float) -> float:
        if not self._pending or self._last_event_at is None:
            return float("inf")
        elapsed = float(now) - float(self._last_event_at)
        return max(0.0, float(self.debounce_seconds) - elapsed)

    def ready(self, *, now: float) -> bool:
        return self.seconds_until_ready(now=now) <= 0.0

    def drain(self) -> set[Path]:
        out = set(self._pending)
        self._pending.clear()
        self._last_event_at = None
        return out


def should_watch_path(target: ScanTarget, path: Path) -> bool:
    """
    Return True if `path` is a candidate for watch-triggered re-scan.

    This matches the same core rules as discovery:
    - Must be under the scan path.
    - Must have an enabled language extension.
    - Must not match ignore patterns.
    """

    try:
        resolved = path.resolve()
    except OSError:
        return False

    scan_path = target.scan_path
    try:
        scan_resolved = scan_path.resolve()
    except OSError:
        return False

    # Only consider files within the scan scope.
    if scan_resolved.is_file():
        if resolved != scan_resolved:
            return False
    else:
        try:
            resolved.relative_to(scan_resolved)
        except ValueError:
            return False

    if not resolved.exists() or not resolved.is_file():
        return False

    allowed_exts = allowed_extensions(target.config.languages)
    if resolved.suffix.lower() not in allowed_exts:
        return False

    if detect_language(resolved) is None:
        return False

    if path_is_ignored(resolved, project_root=target.project_root, ignore_patterns=target.config.ignore.paths):
        return False

    return True

