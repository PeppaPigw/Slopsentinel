from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.cursor import (
    B01CursorRulesExists,
    B02TodoSpray,
    B04ImportThenStub,
    B05TypeAssertionAbuse,
    B08TabCompletionRepeatLines,
)


def test_b01_cursorrules_exists(project_ctx) -> None:
    (project_ctx.project_root / ".cursorrules").write_text("rules\n", encoding="utf-8")
    violations = B01CursorRulesExists().check_project(project_ctx)
    assert any(v.rule_id == "B01" for v in violations)


def test_b02_todo_spray(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "// TODO: one\n"
            "// TODO: two\n"
            "// TODO: three\n"
            "export const x = 1;\n"
        ),
    )
    violations = B02TodoSpray().check_file(ctx)
    assert any(v.rule_id == "B02" for v in violations)


def test_b02_todo_spray_negative(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=("// TODO: one\n" "// TODO: two\n" "export const x = 1;\n"),
    )
    assert B02TodoSpray().check_file(ctx) == []


def test_b02_todo_spray_allows_ticketed_todos(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "// TODO(#123): one\n"
            "// TODO(#124): two\n"
            "// TODO(#125): three\n"
            "export const x = 1;\n"
        ),
    )
    assert B02TodoSpray().check_file(ctx) == []


def test_b02_todo_spray_file_directive_allows_todos(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "// slop: allow-todo\n"
            "// TODO: one\n"
            "// TODO: two\n"
            "// TODO: three\n"
            "export const x = 1;\n"
        ),
    )
    assert B02TodoSpray().check_file(ctx) == []


def test_b04_import_then_stub(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "import Foo from 'foo';\n"
            "// TODO: implement\n"
            "export function f() { throw new Error('not implemented'); }\n"
        ),
    )
    violations = B04ImportThenStub().check_file(ctx)
    assert any(v.rule_id == "B04" for v in violations)


def test_b04_import_then_stub_negative_when_used(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "import Foo from 'foo';\n"
            "export const x = Foo;\n"
        ),
    )
    assert B04ImportThenStub().check_file(ctx) == []


def test_b04_import_then_stub_counts_block_comments_as_comments(project_ctx) -> None:
    block = "\n".join([f" * line {i}" for i in range(40)])
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "import Foo from 'foo';\n"
            "/*\n"
            f"{block}\n"
            " */\n"
            "export const x = 1;\n"
        ),
    )
    violations = B04ImportThenStub().check_file(ctx)
    assert any(v.rule_id == "B04" for v in violations)


def test_b05_type_assertion_abuse(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.ts", content="const x = value as any;\n")
    violations = B05TypeAssertionAbuse().check_file(ctx)
    assert any(v.rule_id == "B05" for v in violations)


def test_b08_tab_completion_repeat_lines(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "const veryLongLineA = someReallyLongFunctionCall(123, 456, 789);\n"
            "const veryLongLineB = someReallyLongFunctionCall(123, 456, 789);\n"
            "const veryLongLineC = someReallyLongFunctionCall(123, 456, 789);\n"
        ),
    )
    violations = B08TabCompletionRepeatLines().check_file(ctx)
    assert any(v.rule_id == "B08" for v in violations)
