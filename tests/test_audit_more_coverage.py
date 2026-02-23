from __future__ import annotations

import logging
from pathlib import Path

import pytest

from slopsentinel.audit import AuditCallbacks, audit_changed_files, audit_path


def test_audit_changed_files_filters_to_discovered_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("hello\n", encoding="utf-8")

    changed_lines = {
        (tmp_path / "a.py").resolve(): {1},
        (tmp_path / "b.txt").resolve(): {1},
    }

    ready_counts: list[int] = []
    callbacks = AuditCallbacks(on_file_contexts_ready=ready_counts.append)

    result = audit_changed_files(
        tmp_path,
        changed_lines,
        apply_baseline=False,
        record_history=False,
        callbacks=callbacks,
    )
    assert result.files == ((tmp_path / "a.py").resolve(),)
    assert ready_counts and ready_counts[0] == 1


def test_audit_path_raises_clean_error_on_plugin_load_failure(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
plugins = ["definitely_not_a_real_plugin_module_12345"]
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Failed to load SlopSentinel plugins"):
        audit_path(tmp_path, apply_baseline=False, record_history=False)


def test_audit_path_warns_on_outside_paths_and_unknown_rule_ids(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
baseline = "../baseline.json"

[tool.slopsentinel.rules]
enable = "all"
severity_overrides = { "Z99" = "warn" }

[tool.slopsentinel.cache]
enabled = true
path = "../cache.json"

[tool.slopsentinel.history]
enabled = true
path = "../history.json"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")

    caplog.set_level(logging.WARNING)
    audit_path(tmp_path)

    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "unknown rule id in rules overrides: Z99" in messages
    assert "refusing cache path outside project root" in messages
    assert "refusing baseline path outside project root" in messages
    assert "refusing history path outside project root" in messages


def test_audit_path_builds_cache_fingerprint_with_directory_overrides(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.rules]
enable = "claude"
severity_overrides = { "A03" = "info" }

[tool.slopsentinel.rules.A04]
severity = "error"

[tool.slopsentinel.rules.A05]

[tool.slopsentinel.overrides."tests/"]
rules.enable = ["claude"]
rules.disable = ["A03"]
rules.severity_overrides = { "A04" = "warn" }

[tool.slopsentinel.cache]
enabled = true
path = ".slopsentinel/cache.json"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "a.py").write_text("# TODO\nx = 1\n", encoding="utf-8")

    result = audit_path(tmp_path, apply_baseline=False, record_history=False)
    assert result.target.config.cache.enabled is True
    assert (tmp_path / ".slopsentinel" / "cache.json").exists()

