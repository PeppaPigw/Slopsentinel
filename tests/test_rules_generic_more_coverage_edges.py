from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.generic import (
    E08IsinstanceChain,
    E09HardcodedCredential,
    E12FunctionTooLong,
)


def test_e08_isinstance_chain_handles_not_isinstance(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            "    if not isinstance(x, int) or isinstance(x, str) or isinstance(x, bytes):\n"
            "        return 1\n"
        ),
    )
    violations = E08IsinstanceChain().check_file(ctx)
    assert any(v.rule_id == "E08" for v in violations)


def test_e08_isinstance_chain_ignores_non_isinstance_values_but_counts_real_checks(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example2.py",
        content=(
            "def f(x):\n"
            "    if isinstance(x, int) or foo(x) or x or isinstance(x) or isinstance(x[0], int) or isinstance(x, str) or isinstance(x, bytes):\n"
            "        return 1\n"
        ),
    )
    violations = E08IsinstanceChain().check_file(ctx)
    assert any(v.rule_id == "E08" for v in violations)


def test_e09_hardcoded_credential_python_annassign_and_namedexpr(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/creds.py",
        content=(
            'token: str = "abc123"\n'
            "def f() -> None:\n"
            '    if (api_key := "secret"):\n'
            "        print(api_key)\n"
        ),
    )
    violations = E09HardcodedCredential().check_file(ctx)
    assert [v.rule_id for v in violations] == ["E09", "E09"]
    assert {v.location.start_line for v in violations if v.location is not None} == {1, 3}


def test_e12_function_too_long_excludes_docstring_and_comment_lines(project_ctx) -> None:
    # 81 code lines + docstring + comments still counts as >80 code lines.
    body = []
    body.append('    """Doc.\n')
    body.append("    More.\n")
    body.append('    """\n')
    body.append("    # comment\n")
    body.append("    x = 0\n")
    body.extend(["    x += 1\n"] * 80)

    ctx = make_file_ctx(project_ctx, relpath="src/big.py", content="def big():\n" + "".join(body))
    violations = E12FunctionTooLong().check_file(ctx)
    assert any(v.rule_id == "E12" for v in violations)
