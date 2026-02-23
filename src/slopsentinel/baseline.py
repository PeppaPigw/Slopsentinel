from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from slopsentinel.engine.types import Violation
from slopsentinel.utils import safe_relpath

BASELINE_VERSION = 2
_SUPPORTED_BASELINE_VERSIONS = {1, 2}


class BaselineError(RuntimeError):
    """Raised when a baseline file is invalid or cannot be processed."""


@dataclass(frozen=True, slots=True)
class Baseline:
    # (rule_id, relative_path, line_no, fingerprint)
    #
    # Fingerprints make baselines resilient to line-number drift; line numbers
    # are retained for readability and as a fallback when fingerprinting is
    # unavailable.
    file_entries: frozenset[tuple[str, str, int, str]]
    repo_entries: frozenset[tuple[str, str]]


def build_baseline(violations: list[Violation], *, project_root: Path) -> Baseline:
    file_entries: set[tuple[str, str, int, str]] = set()
    repo_entries: set[tuple[str, str]] = set()
    line_cache: dict[Path, tuple[str, ...]] = {}

    for v in violations:
        if v.location is not None and v.location.path is not None and v.location.start_line is not None:
            rel = safe_relpath(v.location.path, project_root)
            fingerprint = _fingerprint_violation(v, project_root=project_root, line_cache=line_cache) or ""
            file_entries.add((v.rule_id.strip().upper(), rel, int(v.location.start_line), fingerprint))
        else:
            repo_entries.add((v.rule_id.strip().upper(), v.message))

    return Baseline(file_entries=frozenset(sorted(file_entries)), repo_entries=frozenset(sorted(repo_entries)))


def filter_violations(violations: list[Violation], baseline: Baseline, *, project_root: Path) -> list[Violation]:
    out: list[Violation] = []
    fingerprint_keys = {(rule_id, path, fp) for rule_id, path, _line, fp in baseline.file_entries if fp}
    line_keys = {(rule_id, path, line) for rule_id, path, line, fp in baseline.file_entries if not fp}
    line_cache: dict[Path, tuple[str, ...]] = {}

    for v in violations:
        if v.location is not None and v.location.path is not None and v.location.start_line is not None:
            rel = safe_relpath(v.location.path, project_root)
            rule_id = v.rule_id.strip().upper()
            fingerprint = _fingerprint_violation(v, project_root=project_root, line_cache=line_cache)
            if fingerprint is not None and (rule_id, rel, fingerprint) in fingerprint_keys:
                continue

            key = (rule_id, rel, int(v.location.start_line))
            if key in line_keys:
                continue
            out.append(v)
            continue

        repo_key = (v.rule_id.strip().upper(), v.message)
        if repo_key in baseline.repo_entries:
            continue
        out.append(v)

    return out


def load_baseline(path: Path) -> Baseline:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"Failed to read baseline: {path}") from exc

    if not isinstance(data, dict):
        raise BaselineError("Baseline must be a JSON object.")

    version = data.get("version")
    if version not in _SUPPORTED_BASELINE_VERSIONS:
        raise BaselineError(f"Unsupported baseline version: {version!r}")

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise BaselineError("Baseline `entries` must be a list.")

    file_entries: set[tuple[str, str, int, str]] = set()
    repo_entries: set[tuple[str, str]] = set()

    for item in entries:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            continue
        canonical_rule_id = rule_id.strip().upper()
        raw_path = item.get("path")
        raw_line = item.get("line")
        if isinstance(raw_path, str) and isinstance(raw_line, int):
            fp = item.get("fingerprint")
            fingerprint = fp.strip() if isinstance(fp, str) else ""
            file_entries.add((canonical_rule_id, raw_path, int(raw_line), fingerprint))
            continue
        message = item.get("message")
        if isinstance(message, str):
            repo_entries.add((canonical_rule_id, message))

    return Baseline(file_entries=frozenset(sorted(file_entries)), repo_entries=frozenset(sorted(repo_entries)))


def save_baseline(baseline: Baseline, path: Path) -> None:
    entries: list[dict[str, Any]] = []
    for rule_id, rel, line_no, fingerprint in sorted(baseline.file_entries):
        entry: dict[str, Any] = {"rule_id": rule_id, "path": rel, "line": int(line_no)}
        if fingerprint:
            entry["fingerprint"] = fingerprint
        entries.append(entry)
    for rule_id, message in sorted(baseline.repo_entries):
        entries.append({"rule_id": rule_id, "message": message})

    payload = {
        "version": BASELINE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "entries": entries,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fingerprint_violation(
    v: Violation,
    *,
    project_root: Path,
    line_cache: dict[Path, tuple[str, ...]],
) -> str | None:
    """
    Compute a stable fingerprint for a file-level violation.

    Fingerprints are designed to be resilient to line-number drift across
    commits. To avoid churn across SlopSentinel releases, we intentionally do
    *not* incorporate `message`/`suggestion` into the hash.
    """

    if v.location is None or v.location.path is None or v.location.start_line is None:
        return None

    path = Path(v.location.path)
    lines = _read_file_lines_cached(path, line_cache)
    if not lines:
        return None

    idx = int(v.location.start_line) - 1
    if idx < 0 or idx >= len(lines):
        return None

    start = max(0, idx - 1)
    end = min(len(lines), idx + 2)
    window = [_normalize_line(lines[i]) for i in range(start, end)]
    snippet = "\n".join(window)

    payload = {
        "rule_id": v.rule_id.strip().upper(),
        "path": safe_relpath(path, project_root),
        "snippet": snippet,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return sha256(raw).hexdigest()


def _read_file_lines_cached(path: Path, cache: dict[Path, tuple[str, ...]]) -> tuple[str, ...]:
    cached = cache.get(path)
    if cached is not None:
        return cached

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        cache[path] = ()
        return ()

    lines = tuple(text.splitlines())
    cache[path] = lines
    return lines


def _normalize_line(line: str) -> str:
    # Collapse whitespace to keep fingerprints stable across indentation tweaks.
    return " ".join(line.strip().split())
