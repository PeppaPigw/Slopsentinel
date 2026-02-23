from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.copilot import (
    C04OptionalOveruse,
    C06MissingReturnTypeAnnotation,
    C08AnyOveruse,
    C11LongLambdaExpression,
)


def test_c04_optional_overuse(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "from typing import Optional\n\n"
            "def f(a: Optional[int], b: Optional[int], c: Optional[int], d: Optional[int], e: Optional[int]) -> Optional[int]:\n"
            "    return a or b or c or d or e\n"
        ),
    )
    violations = C04OptionalOveruse().check_file(ctx)
    assert any(v.rule_id == "C04" for v in violations)


def test_c04_optional_overuse_negative(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content="from typing import Optional\n\ndef f(a: Optional[int], b: Optional[int], c: Optional[int], d: Optional[int]) -> int | None:\n    return a\n",
    )
    assert C04OptionalOveruse().check_file(ctx) == []


def test_c06_missing_return_type_annotation(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="def add(x: int, y: int):\n    return x + y\n")
    violations = C06MissingReturnTypeAnnotation().check_file(ctx)
    assert any(v.rule_id == "C06" for v in violations)


def test_c06_missing_return_type_annotation_negative_when_no_annotations(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="def add(x, y):\n    return x + y\n")
    assert C06MissingReturnTypeAnnotation().check_file(ctx) == []


def test_c08_any_overuse(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "from typing import Any\n\n"
            "def f(x: Any) -> Any:\n"
            "    y: Any = x\n"
            "    z: Any = y\n"
            "    a: Any = z\n"
            "    return a\n"
        ),
    )
    violations = C08AnyOveruse().check_file(ctx)
    assert any(v.rule_id == "C08" for v in violations)


def test_c08_any_overuse_negative(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="from typing import Any\n\ndef f(x: Any) -> Any:\n    return x\n")
    assert C08AnyOveruse().check_file(ctx) == []


def test_c11_long_lambda_expression(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content='handler = lambda x: do_something_really_long_name(x, option_one=True, option_two=False, option_three="abc")\n',
    )
    violations = C11LongLambdaExpression().check_file(ctx)
    assert any(v.rule_id == "C11" for v in violations)


def test_c11_long_lambda_expression_negative(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="handler = lambda x: x + 1\n")
    assert C11LongLambdaExpression().check_file(ctx) == []

