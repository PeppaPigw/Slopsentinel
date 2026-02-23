from __future__ import annotations

from pathlib import Path

import pytest

from slopsentinel.autofix import (
    LineRemoval,
    _CommentMask,
    _is_safe_any_comment_deletion,
    _is_safe_simple_python_import_removal,
    _line_matches_rule,
    _merge_removals,
    _plan_removals,
    _plan_replacements,
    _python_bare_except_pass_line,
    _python_comment_lines,
    _python_constant_name,
    _python_plan_constant_extraction,
    _python_token_is_fstring,
    _python_unused_import_statement_removals,
    _range_is_safe,
    _should_remove_line,
    _thinking_blocks,
    _unified_diff,
)
from slopsentinel.engine.types import Location, Violation


def _v(
    rule_id: str,
    *,
    path: Path,
    start_line: int | None,
    message: str,
) -> Violation:
    return Violation(
        rule_id=rule_id,
        severity="info",
        message=message,
        dimension="quality",
        suggestion=None,
        location=Location(path=path, start_line=start_line, start_col=1, end_line=start_line, end_col=1),
    )


def test_python_comment_lines_returns_empty_on_tokenize_error() -> None:
    # Unclosed triple-quoted string triggers tokenize.TokenError.
    source = "def f():\n    '''\n"
    assert _python_comment_lines(source) == set()


def test_python_unused_import_statement_removals_handles_common_skip_cases(tmp_path: Path) -> None:
    path = tmp_path / "x.py"

    # Message mismatch -> no removals.
    lines = ["import os\n"]
    assert _python_unused_import_statement_removals(lines, [_v("E03", path=path, start_line=1, message="nope")]) == []

    # SyntaxError -> no removals.
    bad_lines = ["import \n"]
    assert (
        _python_unused_import_statement_removals(bad_lines, [_v("E03", path=path, start_line=1, message="Imported name `x` is never used.")])
        == []
    )

    # Indented import is skipped (too risky).
    indented = ["def f():\n", "    import os\n"]
    assert (
        _python_unused_import_statement_removals(indented, [_v("E03", path=path, start_line=2, message="Imported name `os` is never used.")])
        == []
    )

    # Semicolon lines are skipped.
    semi = ["import os; import sys\n"]
    assert (
        _python_unused_import_statement_removals(semi, [_v("E03", path=path, start_line=1, message="Imported name `os` is never used.")])
        == []
    )

    # __future__ imports are skipped.
    future = ["from __future__ import annotations\n"]
    assert (
        _python_unused_import_statement_removals(future, [_v("E03", path=path, start_line=1, message="Imported name `annotations` is never used.")])
        == []
    )

    # Star imports are skipped.
    star = ["from x import *\n"]
    assert (
        _python_unused_import_statement_removals(star, [_v("E03", path=path, start_line=1, message="Imported name `x` is never used.")])
        == []
    )

    # slop: directives block editing.
    slop = ["import os  # slop: disable=E03\n"]
    assert (
        _python_unused_import_statement_removals(slop, [_v("E03", path=path, start_line=1, message="Imported name `os` is never used.")])
        == []
    )


def test_python_unused_import_statement_removals_success_and_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "x.py"

    ok_lines = ["import os\n", "\n", "x = 1\n"]
    removals = _python_unused_import_statement_removals(ok_lines, [_v("E03", path=path, start_line=1, message="Imported name `os` is never used.")])
    assert removals == [LineRemoval(rule_ids=("E03",), start_line=1, end_line=1)]

    mismatch_lines = ["import os, sys\n", "x = 1\n"]
    mismatch = _python_unused_import_statement_removals(
        mismatch_lines,
        [_v("E03", path=path, start_line=1, message="Imported name `os` is never used.")],
    )
    assert mismatch == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("import os\n", True),
        ("from x import y\n", True),
        ("from x import *\n", False),
        ("from __future__ import annotations\n", False),
        ("import os.path\n", False),
        ("import os, sys\n", False),
        ("import os  # slop: disable=E03\n", False),
        ("# import os\n", False),
        ("\n", False),
    ],
)
def test_is_safe_simple_python_import_removal(line: str, expected: bool) -> None:
    assert _is_safe_simple_python_import_removal(line) is expected


def test_python_bare_except_pass_line_finds_pass_and_handles_non_pass_cases() -> None:
    lines = [
        "def f():\n",
        "    try:\n",
        "        1 / 0\n",
        "    except:\n",
        "\n",
        "        # comment\n",
        "        pass\n",
        "    return 1\n",
    ]
    assert _python_bare_except_pass_line(lines, 4) == 7

    # If a non-empty non-comment statement appears in the except block, we stop.
    lines2 = [
        "try:\n",
        "    1 / 0\n",
        "except:\n",
        "    x = 1\n",
    ]
    assert _python_bare_except_pass_line(lines2, 3) is None

    # If indentation ends before we see `pass`, we stop.
    lines3 = [
        "try:\n",
        "    1 / 0\n",
        "except:\n",
        "    # comment\n",
        "x = 1\n",
    ]
    assert _python_bare_except_pass_line(lines3, 3) is None


def test_plan_replacements_handles_e04_edge_cases(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    lines = [
        "def f():\n",
        "    try:\n",
        "        1 / 0\n",
        "    except:\n",
        "        pass  # slop: disable=E04\n",
    ]
    mask = _CommentMask(is_comment=(False,) * (len(lines) + 1), in_block_comment=(False,) * (len(lines) + 1))
    reps = _plan_replacements(lines, mask, [_v("E04", path=path, start_line=4, message="except: pass")], language="python")
    assert reps == ()

    # Out-of-range except line is ignored.
    reps2 = _plan_replacements(lines, mask, [_v("E04", path=path, start_line=999, message="except: pass")], language="python")
    assert reps2 == ()

    # If we cannot locate a pass line, we don't replace anything.
    no_pass = ["try:\n", "    1/0\n", "except:\n", "    x = 1\n"]
    mask2 = _CommentMask(is_comment=(False,) * (len(no_pass) + 1), in_block_comment=(False,) * (len(no_pass) + 1))
    reps3 = _plan_replacements(no_pass, mask2, [_v("E04", path=path, start_line=3, message="except: pass")], language="python")
    assert reps3 == ()


def test_plan_removals_skips_out_of_range_violation(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    lines = ["# Here's a comprehensive header\n"]
    mask = _CommentMask(is_comment=(False,) * (len(lines) + 1), in_block_comment=(False,) * (len(lines) + 1))
    removals = _plan_removals(lines, mask, [_v("D01", path=path, start_line=999, message="x")], language="python")
    assert removals == ()


def test_should_remove_line_respects_block_comment_boundaries() -> None:
    lines = [
        "/* Here's a comprehensive overview. */\n",
        "/* Here's a comprehensive overview.\n",
        " * Here's a comprehensive overview.\n",
        " */\n",
    ]
    # Make a mask that simulates "comment line but not in block interior" for the first line,
    # so we exercise the final fall-through path.
    mask_fallthrough = _CommentMask(
        is_comment=(False, True, False, False, False),
        in_block_comment=(False, False, False, False, False),
    )
    assert _should_remove_line("D01", 1, lines[0], mask_fallthrough, allow_block_interior=True) is False

    mask = _CommentMask(
        is_comment=(False, True, True, True, True),
        in_block_comment=(False, True, True, True, True),
    )
    # Block interior can be disabled.
    assert _should_remove_line("D01", 3, lines[2], mask, allow_block_interior=False) is False

    # Single-line /* ... */ can be removed if it matches.
    assert _should_remove_line("D01", 1, lines[0], mask, allow_block_interior=True) is True

    # Boundary lines that aren't single-line /* ... */ are not removed.
    assert _should_remove_line("D01", 2, lines[1], mask, allow_block_interior=True) is False
    assert _should_remove_line("D01", 4, lines[3], mask, allow_block_interior=True) is False


def test_line_matches_rule_default_is_false() -> None:
    assert _line_matches_rule("ZZ", "anything") is False


def test_thinking_blocks_handles_single_line_and_stray_close() -> None:
    lines = [
        "# <thinking> secret </thinking>\n",
        "# </thinking>\n",
    ]
    mask = _CommentMask(
        is_comment=(False, True, True),
        in_block_comment=(False, False, False),
    )
    blocks = _thinking_blocks(lines, mask)
    assert blocks == [(1, 1), (2, 2)]


def test_range_is_safe_rejects_out_of_bounds_and_unsafe_lines() -> None:
    lines = ["# ok\n"]
    mask = _CommentMask(is_comment=(False, True), in_block_comment=(False, False))
    assert _range_is_safe(lines, mask, start=1, end=2) is False

    mask2 = _CommentMask(is_comment=(False, False), in_block_comment=(False, False))
    assert _range_is_safe(lines, mask2, start=1, end=1) is False

    unsafe = ["# slop: disable-file=A03\n"]
    mask3 = _CommentMask(is_comment=(False, True), in_block_comment=(False, False))
    assert _range_is_safe(unsafe, mask3, start=1, end=1) is False


def test_is_safe_any_comment_deletion_handles_slop_directive_and_block_boundaries() -> None:
    line = "# slop: disable-next-line=A03\n"
    mask = _CommentMask(is_comment=(False, True), in_block_comment=(False, False))
    assert _is_safe_any_comment_deletion(1, line, mask) is False

    block = "/*\n"
    mask2 = _CommentMask(is_comment=(False, True), in_block_comment=(False, True))
    assert _is_safe_any_comment_deletion(1, block, mask2) is False

    single = "/* ok */\n"
    assert _is_safe_any_comment_deletion(1, single, mask2) is True


def test_merge_removals_keeps_separate_ranges() -> None:
    merged = _merge_removals(
        [
            LineRemoval(rule_ids=("A03",), start_line=1, end_line=1),
            LineRemoval(rule_ids=("A10",), start_line=10, end_line=10),
        ]
    )
    assert len(merged) == 2


def test_unified_diff_returns_empty_when_no_change(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    assert _unified_diff("x = 1\n", "x = 1\n", path=path) == ""


def test_python_token_helpers_cover_fstring_and_constant_name_collision() -> None:
    assert _python_token_is_fstring('f"hi"') is True
    assert _python_token_is_fstring('"hi"') is False

    assert _python_constant_name("hello world", source="HELLO_WORLD = 'x'\n") is None


def test_python_plan_constant_extraction_covers_early_returns(tmp_path: Path) -> None:
    path = tmp_path / "x.py"

    # No E06 candidates.
    lines = ["print('hello world')\n"]
    other = _v("A03", path=path, start_line=1, message="x")
    assert _python_plan_constant_extraction(lines, [other], replaced_lines=set()) == []

    # Message doesn't match the expected pattern.
    bad_msg = _v("E06", path=path, start_line=1, message="nope")
    assert _python_plan_constant_extraction(lines, [bad_msg], replaced_lines=set()) == []

    # Invalid literal.
    invalid_lit = _v("E06", path=path, start_line=1, message='String literal repeats 4 times: "unterminated')
    assert _python_plan_constant_extraction(lines, [invalid_lit], replaced_lines=set()) == []

    # Too short.
    short = _v("E06", path=path, start_line=1, message='String literal repeats 4 times: "short"')
    assert _python_plan_constant_extraction(lines, [short], replaced_lines=set()) == []

    # SyntaxError in file source.
    bad_source = ["def f(:\n"]
    good_msg = _v("E06", path=path, start_line=1, message='String literal repeats 4 times: "hello world"')
    assert _python_plan_constant_extraction(bad_source, [good_msg], replaced_lines=set()) == []

    # match statements are blocked.
    match_source = [
        "def f(x):\n",
        "    match x:\n",
        "        case \"hello world\":\n",
        "            return 1\n",
        "    print(\"hello world\")\n",
        "    print(\"hello world\")\n",
        "    print(\"hello world\")\n",
        "    print(\"hello world\")\n",
    ]
    assert _python_plan_constant_extraction(match_source, [good_msg], replaced_lines=set()) == []

    # Annotation uses the value -> blocked.
    ann_source = [
        "from typing import Literal\n",
        "x: Literal[\"hello world\"] = \"hello world\"\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
    ]
    assert _python_plan_constant_extraction(ann_source, [good_msg], replaced_lines=set()) == []

    # f-strings using the value -> blocked.
    fstring_source = [
        "x = f\"hello world\"\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
    ]
    assert _python_plan_constant_extraction(fstring_source, [good_msg], replaced_lines=set()) == []

    # Not enough hits -> no extraction.
    three_hits = [
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
    ]
    msg3 = _v("E06", path=path, start_line=1, message='String literal repeats 3 times: "hello world"')
    assert _python_plan_constant_extraction(three_hits, [msg3], replaced_lines=set())

    # replaced_lines can block insertion.
    four_hits = [
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
    ]
    assert _python_plan_constant_extraction(four_hits, [good_msg], replaced_lines={1}) == []


def test_python_plan_constant_extraction_skips_replacement_on_replaced_lines(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    lines = [
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"hello world\")\n",
        "print(\"other\")\n",
    ]
    msg = _v("E06", path=path, start_line=1, message='String literal repeats 4 times: "hello world"')
    planned = _python_plan_constant_extraction(lines, [msg], replaced_lines={2})
    assert planned
    # One of the print lines should remain untouched due to replaced_lines.
    touched = {r.line for r in planned}
    assert 2 not in touched
