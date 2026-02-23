from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.cursor import B02TodoSpray
from slopsentinel.rules.utils import is_comment_line, iter_code_lines, iter_comment_lines


def test_is_comment_line_does_not_classify_star_prefixed_code_as_comment() -> None:
    # `*args` is valid Python syntax in multiline signatures and should not be
    # treated as a comment line.
    assert is_comment_line("    *args,") is False


def test_iter_comment_lines_handles_block_comment_interior(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.js",
        content=(
            "/*\n"
            " * TODO: one\n"
            " * TODO: two\n"
            " */\n"
            "const x = 1\n"
        ),
    )

    comment_lines = list(iter_comment_lines(ctx))
    assert [ln for ln, _line in comment_lines] == [1, 2, 3, 4]

    code_lines = list(iter_code_lines(ctx))
    assert [ln for ln, _line in code_lines] == [5]


def test_cursor_todo_spray_detects_todos_in_block_comment(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.js",
        content=(
            "/*\n"
            " * TODO: one\n"
            " * TODO: two\n"
            " * TODO: three\n"
            " */\n"
            "const x = 1\n"
        ),
    )

    violations = B02TodoSpray().check_file(ctx)
    assert any(v.rule_id == "B02" for v in violations)

