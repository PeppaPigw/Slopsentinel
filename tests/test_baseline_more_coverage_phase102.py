from __future__ import annotations

import json
from pathlib import Path

import pytest

from slopsentinel.baseline import (
    Baseline,
    BaselineError,
    _fingerprint_violation,
    _read_file_lines_cached,
    filter_violations,
    load_baseline,
)
from slopsentinel.engine.types import Location, Violation


def _v(rule_id: str, *, path: Path | None, line: int | None, message: str = "msg") -> Violation:
    loc = None
    if path is not None and line is not None:
        loc = Location(path=path, start_line=line, start_col=1)
    return Violation(rule_id=rule_id, severity="warn", message=message, dimension="quality", location=loc)


def test_filter_violations_keeps_items_not_in_baseline(tmp_path: Path) -> None:
    project_root = tmp_path
    file_path = tmp_path / "src" / "a.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("x = 1\n", encoding="utf-8")

    baseline = Baseline(file_entries=frozenset(), repo_entries=frozenset())
    violations = [
        _v("A03", path=file_path, line=1, message="polite"),
        _v("A01", path=None, line=None, message="repo-level"),
    ]
    remaining = filter_violations(violations, baseline, project_root=project_root)
    assert remaining == violations


def test_load_baseline_raises_on_missing_file_and_invalid_json(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(BaselineError):
        load_baseline(missing)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(BaselineError):
        load_baseline(invalid)


def test_load_baseline_validates_shape_and_version(tmp_path: Path) -> None:
    not_obj = tmp_path / "not_obj.json"
    not_obj.write_text("[]", encoding="utf-8")
    with pytest.raises(BaselineError):
        load_baseline(not_obj)

    bad_version = tmp_path / "bad_version.json"
    bad_version.write_text(json.dumps({"version": 999, "entries": []}), encoding="utf-8")
    with pytest.raises(BaselineError):
        load_baseline(bad_version)

    bad_entries = tmp_path / "bad_entries.json"
    bad_entries.write_text(json.dumps({"version": 2, "entries": {}}), encoding="utf-8")
    with pytest.raises(BaselineError):
        load_baseline(bad_entries)


def test_load_baseline_ignores_malformed_entries(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "version": 2,
                "entries": [
                    123,
                    {"rule_id": ""},
                    {"rule_id": 1},
                    {"rule_id": "A03", "message": "repo"},
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_baseline(baseline_path)
    assert loaded.repo_entries == frozenset({("A03", "repo")})


def test_fingerprint_violation_returns_none_for_missing_location(tmp_path: Path) -> None:
    cache: dict[Path, tuple[str, ...]] = {}
    assert _fingerprint_violation(_v("A03", path=None, line=None), project_root=tmp_path, line_cache=cache) is None


def test_fingerprint_violation_returns_none_for_missing_file_and_out_of_range_line(tmp_path: Path) -> None:
    cache: dict[Path, tuple[str, ...]] = {}
    missing_file = tmp_path / "src" / "missing.py"
    assert (
        _fingerprint_violation(_v("A03", path=missing_file, line=1), project_root=tmp_path, line_cache=cache) is None
    )

    existing = tmp_path / "src" / "a.py"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("x = 1\n", encoding="utf-8")
    assert _fingerprint_violation(_v("A03", path=existing, line=999), project_root=tmp_path, line_cache=cache) is None


def test_read_file_lines_cached_caches_oserror_result(tmp_path: Path) -> None:
    cache: dict[Path, tuple[str, ...]] = {}
    missing = tmp_path / "missing.py"
    assert _read_file_lines_cached(missing, cache) == ()
    assert cache[missing] == ()

