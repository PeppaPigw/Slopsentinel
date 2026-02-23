from __future__ import annotations

from pathlib import Path

import pytest

from slopsentinel.audit import audit_path
from slopsentinel.autofix import apply_fixes, autofix_path, supported_rule_ids
from slopsentinel.engine.types import Location, Violation


def _v(rule_id: str, *, path: Path, start_line: int, message: str = "x") -> Violation:
    return Violation(
        rule_id=rule_id,
        severity="warn",
        message=message,
        dimension="security" if rule_id.startswith("E") else "fingerprint",
        suggestion=None,
        location=Location(path=path, start_line=start_line, start_col=1, end_line=start_line, end_col=1),
    )


def test_supported_rule_ids_includes_a04_and_e09() -> None:
    ids = supported_rule_ids()
    assert "A04" in ids
    assert "E09" in ids


def test_autofix_a04_trims_parameters_returns_and_raises_but_preserves_notes_warning_examples(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "def trivial(x: int) -> int:\n"
        "    \"\"\"\n"
        "    Return x.\n"
        "\n"
        "    Parameters\n"
        "    ----------\n"
        "    x : int\n"
        "        Input.\n"
        "\n"
        "    Returns\n"
        "    -------\n"
        "    int\n"
        "        Output.\n"
        "\n"
        "    Raises\n"
        "    ------\n"
        "    ValueError\n"
        "        Never actually raised.\n"
        "\n"
        "    Notes\n"
        "    -----\n"
        "    Keep this section.\n"
        "\n"
        "    Warning\n"
        "    -------\n"
        "    Also keep this section.\n"
        "\n"
        "    Examples\n"
        "    --------\n"
        "    >>> trivial(1)\n"
        "    1\n"
        "    \"\"\"\n"
        "    return x\n",
        encoding="utf-8",
    )

    audit = audit_path(path)
    ids = {v.rule_id for v in audit.summary.violations}
    assert "A04" in ids

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files

    updated = path.read_text(encoding="utf-8")
    assert "Return x." in updated

    # Removed boilerplate sections.
    assert "Parameters" not in updated
    assert "Returns" not in updated
    assert "Raises" not in updated

    # Preserved potentially useful sections.
    assert "Notes" in updated
    assert "Warning" in updated
    assert "Examples" in updated
    assert "Keep this section." in updated
    assert "Also keep this section." in updated
    assert ">>> trivial(1)" in updated

    # Updated file remains syntactically valid.
    import ast

    ast.parse(updated)

    # Second run is a no-op (idempotent edits).
    second = autofix_path(path, dry_run=False, backup=False)
    assert second.changed_files == ()
    assert second.diff == ""


def test_apply_fixes_e09_inserts_import_and_redacts_module_level_literal(tmp_path: Path) -> None:
    path = tmp_path / "cred.py"
    original = (
        'api_key = "supersecret"\n'
        "\n"
        "def f() -> str:\n"
        "    return api_key\n"
    )
    updated = apply_fixes(path, original, [_v("E09", path=path, start_line=1, message="credential")])

    assert updated.startswith("import os\n")
    assert 'api_key = os.environ.get("API_KEY", "")' in updated
    assert "supersecret" not in updated

    import ast

    ast.parse(updated)


def test_apply_fixes_e09_does_not_duplicate_import_when_already_present(tmp_path: Path) -> None:
    path = tmp_path / "cred.py"
    original = (
        "import os\n"
        "\n"
        'token = "secret"\n'
        "x = 1\n"
    )
    updated = apply_fixes(path, original, [_v("E09", path=path, start_line=3, message="credential")])
    assert updated.count("import os\n") == 1
    assert 'token = os.environ.get("TOKEN", "")' in updated
    assert "secret" not in updated


@pytest.mark.parametrize(
    "source",
    [
        'CONFIG = {"API_KEY": "secret"}\n',
        "class C:\n    API_KEY = \"secret\"\n",
    ],
)
def test_apply_fixes_e09_skips_dict_and_class_attributes(tmp_path: Path, source: str) -> None:
    path = tmp_path / "cred.py"
    # Both examples place the string literal on line 1 or 2, but E09 should be a no-op.
    violation_line = 1 if source.startswith("CONFIG") else 2
    updated = apply_fixes(path, source, [_v("E09", path=path, start_line=violation_line, message="credential")])
    assert updated == source


def test_apply_fixes_e09_preserves_shebang_and_inserts_import_after_it(tmp_path: Path) -> None:
    path = tmp_path / "cred.py"
    original = (
        "#!/usr/bin/env python3\n"
        'token = "secret"\n'
        "print(token)\n"
    )
    updated = apply_fixes(path, original, [_v("E09", path=path, start_line=2, message="credential")])

    assert updated.splitlines()[0] == "#!/usr/bin/env python3"
    assert updated.splitlines()[1] == "import os"
    assert 'token = os.environ.get("TOKEN", "")' in updated

