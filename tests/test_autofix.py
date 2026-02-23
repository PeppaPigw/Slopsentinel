from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from slopsentinel.audit import audit_path
from slopsentinel.autofix import autofix_path
from slopsentinel.cli import app


def _sloppy_file_content() -> str:
    return (
        "# We need to ensure this is removed.\n"
        "# ----------\n"
        "# Here's a comprehensive overview of the module.\n"
        "# As of my last update, this was correct.\n"
        "# <thinking>\n"
        "# internal chain of thought that should not be committed\n"
        "# </thinking>\n"
        "x = 1\n"
    )


def test_autofix_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "src" / "example.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    original = _sloppy_file_content()
    path.write_text(original, encoding="utf-8")

    audit = audit_path(path)
    ids = {v.rule_id for v in audit.summary.violations}
    assert {"A03", "A06", "A10", "C09", "D01"} <= ids

    result = autofix_path(path, dry_run=True, backup=False)
    assert path.read_text(encoding="utf-8") == original
    assert path.resolve() in result.changed_files
    assert "-# We need to ensure this is removed." in result.diff


def test_autofix_writes_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "src" / "example.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_sloppy_file_content(), encoding="utf-8")

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.read_text(encoding="utf-8") == "x = 1\n"
    assert path.resolve() in result.changed_files

    second = autofix_path(path, dry_run=False, backup=False)
    assert second.changed_files == ()
    assert second.diff == ""


def test_autofix_backup_creates_backup(tmp_path: Path) -> None:
    path = tmp_path / "src" / "example.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    original = _sloppy_file_content()
    path.write_text(original, encoding="utf-8")

    result = autofix_path(path, dry_run=False, backup=True)
    assert path.resolve() in result.changed_files

    backup_path = path.with_suffix(path.suffix + ".slopsentinel.bak")
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == original

    # Backup should be preserved on repeated runs.
    _ = autofix_path(path, dry_run=False, backup=True)
    assert backup_path.read_text(encoding="utf-8") == original


def test_cli_fix_command_updates_files(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(_sloppy_file_content(), encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["fix", str(tmp_path)])
    assert res.exit_code == 0
    assert path.read_text(encoding="utf-8") == "x = 1\n"


def test_cli_fix_dry_run_leaves_file_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    original = _sloppy_file_content()
    path.write_text(original, encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["fix", str(tmp_path), "--dry-run"])
    assert res.exit_code == 0
    assert path.read_text(encoding="utf-8") == original
    assert "-# We need to ensure this is removed." in res.stdout


def test_autofix_removes_block_comment_interior_line(tmp_path: Path) -> None:
    path = tmp_path / "example.js"
    path.write_text(
        "/*\n"
        " * Here's a comprehensive overview of this file.\n"
        " */\n"
        "const x = 1\n",
        encoding="utf-8",
    )

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files
    updated = path.read_text(encoding="utf-8")
    assert "Here's a comprehensive" not in updated
    assert "/*" in updated
    assert "*/" in updated


def test_autofix_removes_double_slash_comment_line(tmp_path: Path) -> None:
    path = tmp_path / "example.js"
    path.write_text(
        "// Here's a comprehensive overview of this file.\n"
        "const x = 1;\n",
        encoding="utf-8",
    )

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files
    updated = path.read_text(encoding="utf-8")
    assert "Here's a comprehensive" not in updated
    assert "const x" in updated


def test_autofix_can_fix_unused_import_and_except_pass(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "import os\n"
        "\n"
        "def f():\n"
        "    try:\n"
        "        1 / 0\n"
        "    except:\n"
        "        pass\n"
        "    return 1\n",
        encoding="utf-8",
    )

    audit = audit_path(path)
    ids = {v.rule_id for v in audit.summary.violations}
    assert "E03" in ids
    assert "E04" in ids

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files

    updated = path.read_text(encoding="utf-8")
    assert "import os" not in updated
    assert "except:" in updated
    assert "raise" in updated
    assert "\n        pass\n" not in updated


def test_autofix_can_remove_multiline_unused_import(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "from pkg import (\n"
        "    a,\n"
        "    b,\n"
        ")\n"
        "\n"
        "x = 1\n",
        encoding="utf-8",
    )

    audit = audit_path(path)
    ids = {v.rule_id for v in audit.summary.violations}
    assert "E03" in ids

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files
    updated = path.read_text(encoding="utf-8")
    assert "from pkg import" not in updated
    assert "x = 1" in updated


def test_autofix_can_extract_repeated_string_literal_to_constant(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "def f():\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n",
        encoding="utf-8",
    )

    audit = audit_path(path)
    ids = {v.rule_id for v in audit.summary.violations}
    assert "E06" in ids

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files
    updated = path.read_text(encoding="utf-8")
    assert "hello world" in updated
    assert updated.count("hello world") == 1
    assert "HELLO_WORLD" in updated
    assert "print(HELLO_WORLD)" in updated


def test_autofix_e06_inserts_constant_after_import_block(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "import os\n"
        "import sys\n"
        "\n"
        "def f():\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n"
        "    print(os.name)\n"
        "    print(sys.version)\n",
        encoding="utf-8",
    )

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files
    updated = path.read_text(encoding="utf-8")
    assert updated.startswith("import os\nimport sys\nHELLO_WORLD = ")


def test_autofix_e06_does_not_replace_class_attribute_defaults(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "class C:\n"
        "    A = \"hello world\"\n"
        "    B = \"hello world\"\n"
        "    C = \"hello world\"\n"
        "    D = \"hello world\"\n"
        "\n"
        "def f():\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n"
        "    print(\"hello world\")\n",
        encoding="utf-8",
    )

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files
    updated = path.read_text(encoding="utf-8")

    # Class-level defaults remain unchanged.
    assert updated.count("A = \"hello world\"") == 1
    assert updated.count("B = \"hello world\"") == 1

    # Function body uses a constant.
    assert "HELLO_WORLD" in updated
    assert "print(HELLO_WORLD)" in updated
