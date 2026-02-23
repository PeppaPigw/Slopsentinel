from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.generic import (
    E01CommentCodeRatioAnomalous,
    E02OverlyDefensiveProgramming,
    E03UnusedImports,
    E04EmptyExceptBlock,
    E05LongFunctionSignature,
    E06RepeatedStringLiteral,
    E07ExcessiveNesting,
    E10ExcessiveGuardClauses,
)


def test_e01_comment_code_ratio(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "# c1\n# c2\n# c3\n# c4\n# c5\n# c6\n# c7\n# c8\n"
            "x = 1\n"
            "y = 2\n"
        ),
    )
    violations = E01CommentCodeRatioAnomalous().check_file(ctx)
    assert any(v.rule_id == "E01" for v in violations)


def test_e02_overly_defensive_programming(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            "    total = 0\n"
            "    if x == 0: return 0\n"
            "    total += 1\n"
            "    if x == 1: return 1\n"
            "    total += 1\n"
            "    if x == 2: return 2\n"
            "    total += 1\n"
            "    if x == 3: return 3\n"
            "    total += 1\n"
            "    if x == 4: return 4\n"
            "    total += 1\n"
            "    if x == 5: return 5\n"
            "    return total\n"
        ),
    )
    violations_e02 = E02OverlyDefensiveProgramming().check_file(ctx)
    assert any(v.rule_id == "E02" for v in violations_e02)

    violations_e10 = E10ExcessiveGuardClauses().check_file(ctx)
    assert not any(v.rule_id == "E10" for v in violations_e10)


def test_e03_unused_imports(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="import math\nx = 1\n")
    violations = E03UnusedImports().check_file(ctx)
    assert any(v.rule_id == "E03" for v in violations)


def test_e03_unused_imports_treats_dunder_all_as_usage(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "from m import Foo\n"
            "__all__ = ['Foo']\n"
        ),
    )
    assert E03UnusedImports().check_file(ctx) == []


def test_e03_unused_imports_ignores_type_checking_imports(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from pkg import Foo\n"
            "\n"
            "def f(x: \"Foo\"):\n"
            "    return 1\n"
        ),
    )
    assert E03UnusedImports().check_file(ctx) == []


def test_e03_unused_imports_ignores_init_py_reexports(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/pkg/__init__.py",
        content="from .foo import Bar\n",
    )
    assert E03UnusedImports().check_file(ctx) == []


def test_e03_unused_imports_javascript(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.js",
        content=("import foo from 'foo'\n" "const x = 1\n"),
    )
    violations = E03UnusedImports().check_file(ctx)
    assert any(v.rule_id == "E03" for v in violations)


def test_e03_unused_imports_javascript_react_jsx_ignored(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.jsx",
        content=(
            "import React from 'react'\n"
            "export function App() { return <div /> }\n"
        ),
    )
    violations = E03UnusedImports().check_file(ctx)
    assert not violations


def test_e03_unused_imports_typescript_deterministic_order(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=("import { Foo, Bar as Baz } from 'm'\n" "const x = 1\n"),
    )
    violations = E03UnusedImports().check_file(ctx)
    assert [v.message for v in violations] == [
        "Imported name `Baz` is never used.",
        "Imported name `Foo` is never used.",
    ]


def test_e04_empty_except_block(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            "    try:\n"
            "        1 / 0\n"
            "    except:\n"
            "        pass\n"
        ),
    )
    violations = E04EmptyExceptBlock().check_file(ctx)
    assert any(v.rule_id == "E04" for v in violations)


def test_e04_empty_except_block_catches_exception(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            "    try:\n"
            "        1 / 0\n"
            "    except Exception:\n"
            "        pass\n"
        ),
    )
    violations = E04EmptyExceptBlock().check_file(ctx)
    assert any(v.rule_id == "E04" for v in violations)


def test_e04_empty_except_block_flags_continue(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(xs):\n"
            "    out = []\n"
            "    for x in xs:\n"
            "        try:\n"
            "            out.append(1 / x)\n"
            "        except Exception:\n"
            "            continue\n"
            "    return out\n"
        ),
    )
    violations = E04EmptyExceptBlock().check_file(ctx)
    assert any(v.rule_id == "E04" for v in violations)


def test_e04_empty_except_block_flags_return_none(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            "    try:\n"
            "        1 / 0\n"
            "    except Exception:\n"
            "        return None\n"
        ),
    )
    violations = E04EmptyExceptBlock().check_file(ctx)
    assert any(v.rule_id == "E04" for v in violations)


def test_e04_empty_except_block_does_not_flag_specific_exception(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            "    try:\n"
            "        1 / 0\n"
            "    except ValueError:\n"
            "        pass\n"
        ),
    )
    assert E04EmptyExceptBlock().check_file(ctx) == []


def test_e05_long_function_signature(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content="def f(a, b, c, d, e, f, g, h):\n    return 1\n",
    )
    violations = E05LongFunctionSignature().check_file(ctx)
    assert any(v.rule_id == "E05" for v in violations)


def test_e06_repeated_string_literal(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "a = 'hello world'\n"
            "b = 'hello world'\n"
            "c = 'hello world'\n"
            "x = 'goodbye!'\n"
            "y = 'goodbye!'\n"
            "z = 'goodbye!'\n"
        ),
    )
    violations = E06RepeatedStringLiteral().check_file(ctx)
    assert [v.rule_id for v in violations] == ["E06", "E06"]
    assert any("'hello world'" in v.message for v in violations)
    assert any("'goodbye!'" in v.message for v in violations)


def test_e06_repeated_string_literal_ignores_python_docstrings(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            '    """hello world"""\n'
            "    pass\n\n"
            "def g():\n"
            '    """hello world"""\n'
            "    pass\n\n"
            "def h():\n"
            '    """hello world"""\n'
            "    pass\n\n"
            "def i():\n"
            '    """hello world"""\n'
            "    pass\n\n"
            "def j():\n"
            '    """hello world"""\n'
            "    pass\n"
        ),
    )
    violations = E06RepeatedStringLiteral().check_file(ctx)
    assert not violations


def test_e06_repeated_string_literal_typescript(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "const a = 'hello world'\n"
            "const b = 'hello world'\n"
            "const c = 'hello world'\n"
            "const x = \"goodbye!\"\n"
            "const y = \"goodbye!\"\n"
            "const z = \"goodbye!\"\n"
        ),
    )
    violations = E06RepeatedStringLiteral().check_file(ctx)
    assert [v.rule_id for v in violations] == ["E06", "E06"]
    assert any("hello" in v.message for v in violations)
    assert any("goodbye" in v.message for v in violations)


def test_e06_repeated_string_literal_ignores_js_ts_import_module_specifiers(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "import a from 'react-dom'\n"
            "import b from 'react-dom'\n"
            "import c from 'react-dom'\n"
            "const x = 1\n"
        ),
    )
    violations = E06RepeatedStringLiteral().check_file(ctx)
    assert not violations


def test_e06_repeated_string_literal_requires_three_hits(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "a = 'hello world'\n"
            "b = 'hello world'\n"
        ),
    )
    assert not E06RepeatedStringLiteral().check_file(ctx)


def test_e07_excessive_nesting(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            "    if x:\n"
            "        if x:\n"
            "            if x:\n"
            "                if x:\n"
            "                    if x:\n"
            "                        if x:\n"
            "                            return 1\n"
        ),
    )
    violations = E07ExcessiveNesting().check_file(ctx)
    assert any(v.rule_id == "E07" for v in violations)


def test_e10_excessive_guard_clauses(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            "    if x == 0: return 0\n"
            "    if x == 1: return 1\n"
            "    if x == 2: return 2\n"
            "    if x == 3: return 3\n"
            "    if x == 4: return 4\n"
            "    if x == 5: return 5\n"
            "    return x\n"
        ),
    )
    violations_e10 = E10ExcessiveGuardClauses().check_file(ctx)
    assert any(v.rule_id == "E10" for v in violations_e10)

    violations_e02 = E02OverlyDefensiveProgramming().check_file(ctx)
    assert not any(v.rule_id == "E02" for v in violations_e02)
