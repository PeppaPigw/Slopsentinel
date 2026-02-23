from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.generic import (
    E08IsinstanceChain,
    E09HardcodedCredential,
    E12FunctionTooLong,
)


def test_e08_isinstance_chain_flags_three_or_more(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            "    if isinstance(x, int) or isinstance(x, str) or isinstance(x, bytes):\n"
            "        return 1\n"
        ),
    )
    violations = E08IsinstanceChain().check_file(ctx)
    assert any(v.rule_id == "E08" for v in violations)


def test_e08_isinstance_chain_does_not_flag_tuple_form(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            "    if isinstance(x, (int, str, bytes)):\n"
            "        return 1\n"
        ),
    )
    assert E08IsinstanceChain().check_file(ctx) == []


def test_e09_hardcoded_credential_python_flags_and_ignores_empty(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/creds.py",
        content=(
            "password = 'hunter2'\n"
            "token = ''\n"
            "secretary = 'not-a-secret'\n"
        ),
    )
    violations = E09HardcodedCredential().check_file(ctx)
    assert [v.rule_id for v in violations] == ["E09"]
    assert violations[0].location is not None
    assert violations[0].location.start_line == 1


def test_e09_hardcoded_credential_typescript_flags_and_ignores_comments(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/creds.ts",
        content=(
            "const token = ''\n"
            "// const password = 'nope'\n"
            "export const apiKey: string = \"abc123\";\n"
        ),
    )
    violations = E09HardcodedCredential().check_file(ctx)
    assert [v.rule_id for v in violations] == ["E09"]
    assert violations[0].location is not None
    assert violations[0].location.start_line == 3


def test_e09_hardcoded_credential_ignores_tests_directory(project_ctx) -> None:
    py = make_file_ctx(project_ctx, relpath="tests/test_creds.py", content="password = 'hunter2'\n")
    assert E09HardcodedCredential().check_file(py) == []

    ts = make_file_ctx(project_ctx, relpath="tests/test_creds.ts", content='export const apiKey = "abc123";\n')
    assert E09HardcodedCredential().check_file(ts) == []


def test_e12_function_too_long_flags_over_80_code_lines(project_ctx) -> None:
    body = ["    x = 0\n"] + ["    x += 1\n"] * 80
    ctx = make_file_ctx(project_ctx, relpath="src/big.py", content="def big():\n" + "".join(body))
    violations = E12FunctionTooLong().check_file(ctx)
    assert any(v.rule_id == "E12" for v in violations)


def test_e12_function_too_long_does_not_flag_at_80_code_lines(project_ctx) -> None:
    body = ["    x = 0\n"] + ["    x += 1\n"] * 79
    ctx = make_file_ctx(project_ctx, relpath="src/big.py", content="def big():\n" + "".join(body))
    assert E12FunctionTooLong().check_file(ctx) == []
