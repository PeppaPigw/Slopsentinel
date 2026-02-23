from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from slopsentinel import __version__
from slopsentinel.engine.types import Location, Violation
from slopsentinel.utils import safe_relpath

CACHE_VERSION = 1


class CacheError(RuntimeError):
    """Raised when the cache cannot be read or written safely."""


def file_content_hash(text: str) -> str:
    # Stable across platforms because we hash the decoded text produced by the
    # scanner (which reads with errors="replace").
    return sha256(text.encode("utf-8", errors="replace")).hexdigest()


def config_fingerprint(*, enabled_rule_ids: set[str], overrides: dict[str, str], plugins: tuple[str, ...]) -> str:
    """
    Compute a stable fingerprint for results that depend on config/rules.

    This deliberately does not include paths/ignore/threshold; only the rule
    set and severity overrides influence per-file detections.
    """

    payload = {
        "tool_version": __version__,
        "enabled_rule_ids": sorted(enabled_rule_ids),
        "overrides": {k: overrides[k] for k in sorted(overrides)},
        "plugins": list(plugins),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return sha256(raw).hexdigest()


@dataclass
class _CacheFileEntry:
    content_hash: str
    raw_violations: list[dict[str, Any]]
    parsed_violations: list[Violation] | None = None


class FileViolationCache:
    def __init__(self, path: Path, *, fingerprint: str, project_root: Path) -> None:
        self._path = path
        self._fingerprint = fingerprint
        self._project_root = project_root
        self._lock = threading.Lock()
        self._dirty = False
        self._files: dict[str, _CacheFileEntry] = {}
        self._hits = 0
        self._misses = 0

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def load(cls, path: Path, *, fingerprint: str, project_root: Path) -> FileViolationCache:
        cache = cls(path, fingerprint=fingerprint, project_root=project_root)
        if not path.exists():
            return cache

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Corrupt cache should not break scans; start fresh.
            return cache

        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
            return cache
        if data.get("fingerprint") != fingerprint:
            return cache

        files = data.get("files")
        if not isinstance(files, dict):
            return cache

        for relpath, entry in files.items():
            if not isinstance(relpath, str) or not isinstance(entry, dict):
                continue
            content_hash = entry.get("hash")
            raw_violations = entry.get("violations", [])
            if not isinstance(content_hash, str) or not isinstance(raw_violations, list):
                continue
            raw_dicts = [item for item in raw_violations if isinstance(item, dict)]
            cache._files[relpath] = _CacheFileEntry(
                content_hash=content_hash,
                raw_violations=cast(list[dict[str, Any]], raw_dicts),
            )

        return cache

    def get(self, *, relative_path: str, content_hash: str) -> list[Violation] | None:
        with self._lock:
            entry = self._files.get(relative_path)
            if entry is None or entry.content_hash != content_hash:
                self._misses += 1
                return None
            self._hits += 1
            if entry.parsed_violations is None:
                entry.parsed_violations = [_deserialize_violation(v, project_root=self._project_root) for v in entry.raw_violations]
            return list(entry.parsed_violations)

    def put(self, *, relative_path: str, content_hash: str, violations: list[Violation]) -> None:
        raw = [_serialize_violation(v, project_root=self._project_root) for v in violations]
        with self._lock:
            self._files[relative_path] = _CacheFileEntry(
                content_hash=content_hash,
                raw_violations=raw,
                parsed_violations=list(violations),
            )
            self._dirty = True

    def stats(self) -> tuple[int, int]:
        """
        Return (hits, misses) observed during this process run.

        Intended for verbose logging / benchmark instrumentation.
        """

        with self._lock:
            return int(self._hits), int(self._misses)

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return

            payload = {
                "version": CACHE_VERSION,
                "fingerprint": self._fingerprint,
                "files": {
                    rel: {"hash": entry.content_hash, "violations": entry.raw_violations} for rel, entry in sorted(self._files.items())
                },
            }

            # Atomic write: write next to the target then replace.
            #
            # Keep the lock held for the full write/replace operation to avoid
            # races where concurrent `put()` calls flip `_dirty` during a save
            # and then get lost when `_dirty` is reset.
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(self._path)

            self._dirty = False


def _serialize_violation(v: Violation, *, project_root: Path) -> dict[str, Any]:
    loc = v.location
    out: dict[str, Any] = {
        "rule_id": v.rule_id,
        "severity": v.severity,
        "message": v.message,
        "dimension": v.dimension,
        "suggestion": v.suggestion,
        "location": None,
    }
    if loc is None or loc.path is None or loc.start_line is None:
        return out

    rel = safe_relpath(loc.path, project_root)
    out["location"] = {
        "path": rel,
        "start_line": int(loc.start_line),
        "start_col": int(loc.start_col or 1),
        "end_line": int(loc.end_line) if loc.end_line is not None else None,
        "end_col": int(loc.end_col) if loc.end_col is not None else None,
    }
    return out


def _deserialize_violation(data: dict[str, Any], *, project_root: Path) -> Violation:
    rule_id = str(data.get("rule_id", "")).strip().upper()
    raw_severity = str(data.get("severity", "info")).strip().lower()
    if raw_severity not in {"info", "warn", "error"}:
        raw_severity = "info"
    severity = cast(Any, raw_severity)

    message = str(data.get("message", ""))

    raw_dimension = str(data.get("dimension", "quality")).strip().lower()
    if raw_dimension not in {"fingerprint", "quality", "hallucination", "maintainability", "security"}:
        raw_dimension = "quality"
    dimension = cast(Any, raw_dimension)
    suggestion = data.get("suggestion")
    if not isinstance(suggestion, str):
        suggestion = None

    loc = None
    raw_loc = data.get("location")
    if isinstance(raw_loc, dict):
        raw_path = raw_loc.get("path")
        raw_start_line = raw_loc.get("start_line")
        raw_start_col = raw_loc.get("start_col")
        if isinstance(raw_path, str) and isinstance(raw_start_line, int) and raw_start_line > 0:
            start_col = int(raw_start_col) if isinstance(raw_start_col, int) and raw_start_col > 0 else 1

            candidate_path = Path(raw_path)
            if not candidate_path.is_absolute():
                resolved_root = project_root.resolve()
                resolved_path: Path | None
                try:
                    resolved_path = (project_root / candidate_path).resolve()
                    resolved_path.relative_to(resolved_root)
                except (OSError, RuntimeError, ValueError):
                    resolved_path = None

                if resolved_path is not None:
                    loc = Location(
                        path=resolved_path,
                        start_line=int(raw_start_line),
                        start_col=start_col,
                        end_line=int(raw_loc["end_line"]) if isinstance(raw_loc.get("end_line"), int) else None,
                        end_col=int(raw_loc["end_col"]) if isinstance(raw_loc.get("end_col"), int) else None,
                    )

    return Violation(
        rule_id=rule_id,
        severity=severity,
        message=message,
        dimension=dimension,
        suggestion=suggestion,
        location=loc,
    )
