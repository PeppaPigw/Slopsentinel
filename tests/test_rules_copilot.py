from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.copilot import (
    C01RedundantCommentRestatesCode,
    C02ExampleUsageDoctestBlock,
    C03HallucinatedImport,
    C05OverlyGenericVariableNames,
    C07DebugPrintStatements,
    C09TrainingCutoffReference,
    C10ExceptionSwallowing,
)


def test_c01_redundant_comment_restates_code(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "# Initialize an empty list for results\n"
            "results = []\n"
        ),
    )
    violations = C01RedundantCommentRestatesCode().check_file(ctx)
    assert any(v.rule_id == "C01" for v in violations)


def test_c01_redundant_comment_negative(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "# Results container\n"
            "results = []\n"
        ),
    )
    assert C01RedundantCommentRestatesCode().check_file(ctx) == []


def test_c01_redundant_comment_ignores_noqa_and_type_ignore(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "# Initialize an empty list for results  # noqa: E501\n"
            "results = []\n"
            "# Initialize cache  # type: ignore\n"
            "cache = {}\n"
        ),
    )
    assert C01RedundantCommentRestatesCode().check_file(ctx) == []


def test_c02_example_usage_doctest(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            '    """\n'
            "    Example Usage:\n"
            "      f()\n"
            '    """\n'
            "    return 1\n"
        ),
    )
    violations = C02ExampleUsageDoctestBlock().check_file(ctx)
    assert any(v.rule_id == "C02" for v in violations)


def test_c02_example_usage_ignores_structured_docstrings(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            '    """\n'
            "    Parameters\n"
            "    ----------\n"
            "    x : int\n"
            "        Value.\n"
            "\n"
            "    Example Usage:\n"
            "      f(1)\n"
            '    """\n'
            "    return x\n"
        ),
    )
    assert C02ExampleUsageDoctestBlock().check_file(ctx) == []


def test_c03_hallucinated_import(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content="import definitely_not_a_real_module_12345\n",
    )
    violations = C03HallucinatedImport().check_file(ctx)
    assert any(v.rule_id == "C03" for v in violations)


def test_c03_hallucinated_import_ignores_declared_dependencies(project_ctx) -> None:
    (project_ctx.project_root / "pyproject.toml").write_text(
        """
[project]
dependencies = ["requests>=2.0"]
""".lstrip(),
        encoding="utf-8",
    )
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="import requests\n")
    assert C03HallucinatedImport().check_file(ctx) == []


def test_c03_hallucinated_import_ignores_optional_imports_in_try(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "try:\n"
            "    import definitely_not_a_real_module_12345\n"
            "except ImportError:\n"
            "    definitely_not_a_real_module_12345 = None\n"
        ),
    )
    assert C03HallucinatedImport().check_file(ctx) == []


def test_c03_hallucinated_import_negative_stdlib(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="import sys\n")
    assert C03HallucinatedImport().check_file(ctx) == []


def test_c03_hallucinated_import_ignores_local_src_modules(project_ctx) -> None:
    make_file_ctx(project_ctx, relpath="src/local_mod.py", content="x = 1\n")
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="import local_mod\n")
    assert C03HallucinatedImport().check_file(ctx) == []


def test_c03_hallucinated_import_ignores_local_root_modules(project_ctx) -> None:
    make_file_ctx(project_ctx, relpath="local_root_mod.py", content="x = 1\n")
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="import local_root_mod\n")
    assert C03HallucinatedImport().check_file(ctx) == []


def test_c05_generic_variable_names(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            "    data = 1\n"
            "    print(data)\n"
            "    data = data + 1\n"
            "    return data\n"
        ),
    )
    violations = C05OverlyGenericVariableNames().check_file(ctx)
    assert any(v.rule_id == "C05" for v in violations)


def test_c07_debug_print(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content='print("DEBUG: here")\n')
    violations = C07DebugPrintStatements().check_file(ctx)
    assert any(v.rule_id == "C07" for v in violations)


def test_c07_debug_print_detects_logging_debug_prefix(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content='import logging\nlogging.debug("DEBUG: here")\n')
    violations = C07DebugPrintStatements().check_file(ctx)
    assert any(v.rule_id == "C07" for v in violations)


def test_c07_debug_print_does_not_flag_normal_logging(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content='import logging\nlogging.debug("hello")\n')
    assert C07DebugPrintStatements().check_file(ctx) == []


def test_c07_debug_print_detects_console_debug_in_js(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.js", content='console.debug("x")\n')
    violations = C07DebugPrintStatements().check_file(ctx)
    assert any(v.rule_id == "C07" for v in violations)


def test_c07_debug_print_detects_console_warn_debug_prefix_in_ts(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.ts", content='console.warn("DEBUG: x")\n')
    violations = C07DebugPrintStatements().check_file(ctx)
    assert any(v.rule_id == "C07" for v in violations)


def test_c07_debug_print_ignores_comments(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content='# print("DEBUG: here")\n')
    assert C07DebugPrintStatements().check_file(ctx) == []


def test_c07_debug_print_ignores_docstrings(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            '"""Example:\n'
            'print("DEBUG: here")\n'
            '"""\n'
            "x = 1\n"
        ),
    )
    assert C07DebugPrintStatements().check_file(ctx) == []


def test_c09_training_cutoff_reference(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="# As of my last update, this works.\n")
    violations = C09TrainingCutoffReference().check_file(ctx)
    assert any(v.rule_id == "C09" for v in violations)


def test_c10_exception_swallowing(project_ctx) -> None:
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
    violations = C10ExceptionSwallowing().check_file(ctx)
    assert any(v.rule_id == "C10" for v in violations)
