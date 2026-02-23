from __future__ import annotations

import logging
from pathlib import Path

from slopsentinel.audit import audit_path


def test_rules_severity_overrides_map_changes_violation_severity(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
languages = ["python"]

[tool.slopsentinel.rules]
enable = "claude"
severity_overrides = { "A03" = "error" }
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "example.py").write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    result = audit_path(tmp_path, record_history=False)
    a03 = [v for v in result.summary.violations if v.rule_id == "A03"]
    assert a03
    assert all(v.severity == "error" for v in a03)


def test_rules_severity_overrides_accepts_warning_alias(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
languages = ["python"]

[tool.slopsentinel.rules]
enable = "claude"
severity_overrides = { "A03" = "warning" }
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "example.py").write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    result = audit_path(tmp_path, record_history=False)
    a03 = [v for v in result.summary.violations if v.rule_id == "A03"]
    assert a03
    assert all(v.severity == "warn" for v in a03)


def test_unknown_rule_id_in_severity_overrides_warns_but_does_not_error(tmp_path: Path, caplog) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
languages = ["python"]

[tool.slopsentinel.rules]
enable = "claude"
severity_overrides = { "Z99" = "warn" }
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "example.py").write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    caplog.set_level(logging.WARNING)
    _ = audit_path(tmp_path, record_history=False)
    assert any("unknown rule id" in rec.message for rec in caplog.records)

