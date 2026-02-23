from __future__ import annotations

from pathlib import Path

from slopsentinel.audit import audit_path


def _rel(root: Path, p: Path) -> str:
    return p.resolve().relative_to(root.resolve()).as_posix()


def test_directory_overrides_enable_different_rule_groups_per_path(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
languages = ["python"]

[tool.slopsentinel.rules]
enable = "claude"

[tool.slopsentinel.overrides."tests/"]
rules.enable = "generic"

[tool.slopsentinel.overrides."tests/unit/"]
rules.enable = "copilot"
""".lstrip(),
        encoding="utf-8",
    )

    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "unit").mkdir(parents=True, exist_ok=True)

    (tmp_path / "src" / "app.py").write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "tests" / "unit" / "test_unit.py").write_text(
        "# As of my last update, this works.\n" 'password = "hunter2"\n',
        encoding="utf-8",
    )

    result = audit_path(tmp_path, record_history=False)

    by_file: dict[str, set[str]] = {}
    for v in result.summary.violations:
        if v.location is None or v.location.path is None:
            continue
        rel = _rel(tmp_path, v.location.path)
        by_file.setdefault(rel, set()).add(v.rule_id)

    assert "A03" in by_file.get("src/app.py", set())
    assert "E03" in by_file.get("tests/test_app.py", set())

    # Longest-prefix match: `tests/unit/` override wins over `tests/`, so the
    # generic rule (E03) should not run here.
    assert "C09" in by_file.get("tests/unit/test_unit.py", set())
    assert "E03" not in by_file.get("tests/unit/test_unit.py", set())
