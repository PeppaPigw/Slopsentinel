from __future__ import annotations

from pathlib import Path

from slopsentinel.audit import audit_path
from slopsentinel.autofix import autofix_path


def test_autofix_e11_simplifies_boolean_return(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "def f(x: bool) -> bool:\n"
        "    if x:\n"
        "        return True\n"
        "    else:\n"
        "        return False\n",
        encoding="utf-8",
    )

    audit = audit_path(path)
    assert "E11" in {v.rule_id for v in audit.summary.violations}

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files
    updated = path.read_text(encoding="utf-8")
    assert "return x" in updated
    assert "else:" not in updated


def test_autofix_e11_simplifies_inverted_boolean_return(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "def f(x: bool) -> bool:\n"
        "    if x:\n"
        "        return False\n"
        "    else:\n"
        "        return True\n",
        encoding="utf-8",
    )

    audit = audit_path(path)
    assert "E11" in {v.rule_id for v in audit.summary.violations}

    _ = autofix_path(path, dry_run=False, backup=False)
    updated = path.read_text(encoding="utf-8")
    assert "return not x" in updated
    assert "else:" not in updated

