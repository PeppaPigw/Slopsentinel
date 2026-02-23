from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.cursor import B03ConsoleLogSpray, B06EmptyInterfaceOrType, B07AsAnyOveruse


def test_b03_console_log_spray(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            'console.log("a");\n'
            'console.log("b");\n'
            'console.log("c");\n'
            'console.log("d");\n'
            'console.log("e");\n'
        ),
    )
    violations = B03ConsoleLogSpray().check_file(ctx)
    assert any(v.rule_id == "B03" for v in violations)


def test_b03_console_log_spray_skips_test_files(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.test.ts",
        content="\n".join(['console.log(\"x\");' for _ in range(5)]) + "\n",
    )
    assert B03ConsoleLogSpray().check_file(ctx) == []


def test_b06_empty_interface_or_type(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.ts", content="interface Foo {}\n")
    violations = B06EmptyInterfaceOrType().check_file(ctx)
    assert any(v.rule_id == "B06" for v in violations)


def test_b06_empty_interface_or_type_negative(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.ts", content="interface Foo { id: string }\n")
    assert B06EmptyInterfaceOrType().check_file(ctx) == []


def test_b07_as_any_overuse(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content="const a = value as any;\nconst b = other as any;\nconst c = third as any;\n",
    )
    violations = B07AsAnyOveruse().check_file(ctx)
    assert any(v.rule_id == "B07" for v in violations)


def test_b07_as_any_overuse_negative(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.ts", content="const a = value as any;\nconst b = other as any;\n")
    assert B07AsAnyOveruse().check_file(ctx) == []

