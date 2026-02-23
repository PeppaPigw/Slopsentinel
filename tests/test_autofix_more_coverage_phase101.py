from __future__ import annotations

from pathlib import Path

from slopsentinel.audit import audit_path
from slopsentinel.autofix import (
    LineReplacement,
    _fixable_violations,
    _merge_replacements,
    _python_a04_docstring_section_removals,
    _python_bare_except_pass_line,
    _python_boolean_return_extra_removals,
    _python_e09_credential_redaction_replacements,
    _python_plan_boolean_return_simplification,
    _python_token_is_fstring,
    apply_fixes,
    autofix_path,
)
from slopsentinel.engine.types import Location, Violation


def _v(rule_id: str, *, path: Path, start_line: int | None, message: str = "x") -> Violation:
    return Violation(
        rule_id=rule_id,
        severity="warn",
        message=message,
        dimension="quality",
        suggestion=None,
        location=Location(path=path, start_line=start_line, start_col=1, end_line=start_line, end_col=1),
    )


def test_python_token_is_fstring_returns_false_when_no_quotes() -> None:
    assert _python_token_is_fstring("no_quotes_here") is False


def test_autofix_a04_trims_google_style_args_and_returns_sections(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    path.write_text(
        "def trivial(x: int) -> int:\n"
        "    \"\"\"\n"
        "    Return x.\n"
        "\n"
        "    Args:\n"
        "        x: Input.\n"
        "\n"
        "    Returns:\n"
        "        int: Output.\n"
        "\n"
        "    Notes:\n"
        "        Keep this section.\n"
        "    \"\"\"\n"
        "    return x\n",
        encoding="utf-8",
    )

    audit = audit_path(path)
    assert "A04" in {v.rule_id for v in audit.summary.violations}

    result = autofix_path(path, dry_run=False, backup=False)
    assert path.resolve() in result.changed_files

    updated = path.read_text(encoding="utf-8")
    assert "Args:" not in updated
    assert "Returns:" not in updated
    assert "Notes:" in updated


def test_apply_fixes_a04_summary_only_docstring_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    original = (
        "def f() -> int:\n"
        "    \"\"\"Return 1.\"\"\"\n"
        "    return 1\n"
    )
    updated = apply_fixes(path, original, [_v("A04", path=path, start_line=2, message="docstring")])
    assert updated == original


def test_python_a04_docstring_section_removals_returns_empty_on_syntax_error(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    lines = ["def f(:\n"]
    assert _python_a04_docstring_section_removals(lines, [_v("A04", path=path, start_line=1)]) == []


def test_apply_fixes_e09_redacts_function_local_and_inserts_import_after_docstring_future_and_imports(tmp_path: Path) -> None:
    path = tmp_path / "cred.py"
    original = (
        '"""module doc"""\n'
        "from __future__ import annotations\n"
        "import sys\n"
        "\n"
        "def f() -> str:\n"
        '    password = "secret"\n'
        "    return password\n"
    )
    updated = apply_fixes(path, original, [_v("E09", path=path, start_line=6, message="credential")])

    lines = updated.splitlines()
    assert lines[0] == '"""module doc"""'
    assert lines[1].startswith("from __future__")
    assert lines[2] == "import sys"
    assert lines[3] == "import os"
    assert any('password = os.environ.get("PASSWORD", "")' in ln for ln in lines)


def test_apply_fixes_e09_supports_annassign_and_preserves_encoding_comment(tmp_path: Path) -> None:
    path = tmp_path / "cred.py"
    original = (
        "# -*- coding: utf-8 -*-\n"
        'token: str = "secret"\n'
        "x = 1\n"
    )
    updated = apply_fixes(path, original, [_v("E09", path=path, start_line=2, message="credential")])
    out_lines = updated.splitlines()
    assert out_lines[0].startswith("# -*- coding:")
    assert out_lines[1] == "import os"
    assert any('token = os.environ.get("TOKEN", "")' in ln for ln in out_lines)


def test_python_e09_credential_redaction_skips_non_simple_assign(tmp_path: Path) -> None:
    path = tmp_path / "cred.py"
    original = (
        'a, b = ("x", "y")\n'
        'token = "secret"\n'
    )
    lines = original.splitlines(keepends=True)
    reps = _python_e09_credential_redaction_replacements(lines, [_v("E09", path=path, start_line=1, message="credential")])
    # Line 1 isn't a simple `Name = "..."` assignment; this should be ignored.
    assert reps == []


def test_apply_fixes_can_remove_safe_unused_import_even_when_bulk_removal_does_not_match(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    original = "import os\nx = 1\n"
    updated = apply_fixes(path, original, [_v("E03", path=path, start_line=1, message="unused import")])
    assert "import os" not in updated
    assert "x = 1" in updated


def test_python_bare_except_pass_line_returns_none_when_reaches_eof() -> None:
    lines = [
        "try:\n",
        "    1 / 0\n",
        "except:\n",
        "    # comment\n",
    ]
    assert _python_bare_except_pass_line(lines, 3) is None


def test_merge_replacements_merges_insertions_and_orders_imports_before_constants(tmp_path: Path) -> None:
    original = 'token = "secret"\n'
    lines = original.splitlines(keepends=True)

    merged = _merge_replacements(
        lines,
        [
            LineReplacement(rule_ids=("E06",), line=1, content='HELLO = "hello"\n' + lines[0]),
            LineReplacement(rule_ids=("E09",), line=1, content="import os\n" + lines[0]),
            LineReplacement(rule_ids=("E09",), line=1, content='token = os.environ.get("TOKEN", "")\n'),
        ],
    )
    assert len(merged) == 1
    content = merged[0].content
    assert content.startswith("import os\n")
    assert 'HELLO = "hello"\n' in content
    assert 'token = os.environ.get("TOKEN", "")' in content


def test_merge_replacements_keeps_last_for_out_of_range_lines() -> None:
    merged = _merge_replacements(
        ["x = 1\n"],
        [
            LineReplacement(rule_ids=("E09",), line=999, content="import os\n"),
            LineReplacement(rule_ids=("E06",), line=999, content="CONST = 1\n"),
        ],
    )
    assert merged == (LineReplacement(rule_ids=("E06",), line=999, content="CONST = 1\n"),)


def test_python_boolean_return_helpers_cover_syntax_error_and_missing_if_node(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    lines = ["def f(:\n"]
    assert _python_plan_boolean_return_simplification(lines, [_v("E11", path=path, start_line=1)], replaced_lines=set()) == []
    assert _python_boolean_return_extra_removals(lines, [_v("E11", path=path, start_line=1)]) == []

    ok_lines = [
        "def f(x: bool) -> bool:\n",
        "    if x:\n",
        "        return True\n",
        "    else:\n",
        "        return False\n",
    ]
    # Wrong line number => no if node found => no removals.
    assert _python_boolean_return_extra_removals(ok_lines, [_v("E11", path=path, start_line=999)]) == []


def test_fixable_violations_skips_missing_location_and_path(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    v_missing_loc = Violation(
        rule_id="E11",
        severity="warn",
        message="x",
        dimension="quality",
        suggestion=None,
        location=None,
    )
    v_missing_path = Violation(
        rule_id="E11",
        severity="warn",
        message="x",
        dimension="quality",
        suggestion=None,
        location=Location(path=None, start_line=1, start_col=1, end_line=1, end_col=1),
    )
    v_ok = _v("E11", path=path, start_line=1)
    assert _fixable_violations((v_missing_loc, v_missing_path, v_ok)) == [v_ok]


def test_python_plan_boolean_return_simplification_happy_paths(tmp_path: Path) -> None:
    path = tmp_path / "x.py"

    lines = [
        "def f(x: bool) -> bool:\n",
        "    if x:\n",
        "        return True\n",
        "    else:\n",
        "        return False\n",
    ]
    reps = _python_plan_boolean_return_simplification(lines, [_v("E11", path=path, start_line=2)], replaced_lines=set())
    assert reps == [LineReplacement(rule_ids=("E11",), line=2, content="    return x\n")]

    inverted_lines = [
        "def f(x: bool) -> bool:\n",
        "    if x:\n",
        "        return False\n",
        "    else:\n",
        "        return True\n",
    ]
    inv_reps = _python_plan_boolean_return_simplification(
        inverted_lines, [_v("E11", path=path, start_line=2)], replaced_lines=set()
    )
    assert inv_reps == [LineReplacement(rule_ids=("E11",), line=2, content="    return not x\n")]


def test_python_plan_boolean_return_simplification_skips_invalid_patterns(tmp_path: Path) -> None:
    path = tmp_path / "x.py"

    # Wrong line number => no if node match.
    lines = [
        "def f(x: bool) -> bool:\n",
        "    if x:\n",
        "        return True\n",
        "    else:\n",
        "        return False\n",
    ]
    assert _python_plan_boolean_return_simplification(lines, [_v("E11", path=path, start_line=999)], replaced_lines=set()) == []

    # Missing else.
    no_else = [
        "def f(x: bool) -> bool:\n",
        "    if x:\n",
        "        return True\n",
        "    return False\n",
    ]
    assert _python_plan_boolean_return_simplification(no_else, [_v("E11", path=path, start_line=2)], replaced_lines=set()) == []

    # Else branch isn't a return statement.
    else_not_return = [
        "def f(x: bool) -> bool:\n",
        "    if x:\n",
        "        return True\n",
        "    else:\n",
        "        pass\n",
    ]
    assert (
        _python_plan_boolean_return_simplification(else_not_return, [_v("E11", path=path, start_line=2)], replaced_lines=set())
        == []
    )

    # Return values aren't booleans.
    not_bool = [
        "def f(x: bool) -> int:\n",
        "    if x:\n",
        "        return 1\n",
        "    else:\n",
        "        return 0\n",
    ]
    assert _python_plan_boolean_return_simplification(not_bool, [_v("E11", path=path, start_line=2)], replaced_lines=set()) == []

    # Multi-line condition => skipped for safety.
    multiline_cond = [
        "def f(x: bool, y: bool) -> bool:\n",
        "    if x and (\n",
        "        y\n",
        "    ):\n",
        "        return True\n",
        "    else:\n",
        "        return False\n",
    ]
    assert (
        _python_plan_boolean_return_simplification(multiline_cond, [_v("E11", path=path, start_line=2)], replaced_lines=set())
        == []
    )

    # Any already-replaced line in the if/else range => skipped.
    assert (
        _python_plan_boolean_return_simplification(lines, [_v("E11", path=path, start_line=2)], replaced_lines={3})
        == []
    )


def test_python_boolean_return_extra_removals_skips_single_line_if(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    lines = [
        "def f(x: bool) -> bool:\n",
        "    if x: return True\n",
        "    return False\n",
    ]
    # A single-line if has end_lineno == lineno; we should not plan removals.
    assert _python_boolean_return_extra_removals(lines, [_v("E11", path=path, start_line=2)]) == []


def test_merge_replacements_insertion_weight_default_path() -> None:
    lines = ["x = 1\n"]
    merged = _merge_replacements(
        lines,
        [
            LineReplacement(rule_ids=("A04",), line=1, content="# prefix\n" + lines[0]),
            LineReplacement(rule_ids=("E09",), line=1, content="import os\n" + lines[0]),
        ],
    )
    assert merged == (LineReplacement(rule_ids=("A04", "E09"), line=1, content="import os\n# prefix\nx = 1\n"),)
