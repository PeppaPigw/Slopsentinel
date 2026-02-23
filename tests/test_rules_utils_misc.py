from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.utils import (
    consecutive_runs,
    iter_code_lines,
    iter_comment_lines,
    normalize_words,
)


def test_normalize_words_lowercases_and_filters_short_tokens() -> None:
    assert normalize_words("Hi, Robust World! a1b2c3") == ["robust", "world"]


def test_consecutive_runs_groups_consecutive_integers() -> None:
    assert consecutive_runs([]) == []
    assert consecutive_runs([1]) == [(1, 1)]
    assert consecutive_runs([1, 2, 3, 7, 8, 10]) == [(1, 3), (7, 2), (10, 1)]


def test_iter_comment_and_code_lines_handle_single_line_block_comment(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "/* one-line block */\n"
            "// line comment\n"
            "const x = 1\n"
        ),
    )

    comment_lines = [ln for ln, _line in iter_comment_lines(ctx)]
    assert comment_lines == [1, 2]

    code_lines = [ln for ln, _line in iter_code_lines(ctx)]
    assert code_lines == [3]
