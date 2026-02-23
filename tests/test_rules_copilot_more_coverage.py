from __future__ import annotations

import ast
from pathlib import Path

from helpers import make_file_ctx

from slopsentinel.rules.copilot import (
    C01RedundantCommentRestatesCode,
    C02ExampleUsageDoctestBlock,
    C03HallucinatedImport,
    C07DebugPrintStatements,
    _declared_dependency_modules,
    _looks_like_trivial_init_pair,
    _names_from_dependency_list,
    _names_from_dependency_table,
    _normalize_dist_to_modules,
    _optional_import_lines,
    _strip_comment_prefix,
)


def test_strip_comment_prefix_supports_multiple_styles() -> None:
    assert _strip_comment_prefix("# hello") == " hello"
    assert _strip_comment_prefix("  // hi") == " hi"
    assert _strip_comment_prefix("/* block") == " block"
    assert _strip_comment_prefix("* line") == " line"
    # Unknown prefix falls back to lstrip().
    assert _strip_comment_prefix("  no prefix") == "no prefix"


def test_looks_like_trivial_init_pair_covers_branches() -> None:
    assert _looks_like_trivial_init_pair(comment_text="Initialize empty list results", code_line="results = []") is True
    assert _looks_like_trivial_init_pair(comment_text="Initialize empty list", code_line="x = 1") is False
    assert _looks_like_trivial_init_pair(comment_text="Set up list", code_line="results = []") is False
    assert _looks_like_trivial_init_pair(comment_text="Initialize empty list myList", code_line="myList = []") is True
    # No assignment -> no variable name -> use fallback phrasing match.
    assert _looks_like_trivial_init_pair(comment_text="Initialize empty", code_line="[]") is True


def test_c01_comment_at_end_of_file_is_ignored(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="# Initialize an empty list for results\n")
    assert C01RedundantCommentRestatesCode().check_file(ctx) == []


def test_c02_structured_docstring_with_param_suppresses_example_usage(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x: int) -> int:\n"
            '    """\n'
            "    Example Usage:\n"
            "        f(1)\n"
            "\n"
            "    :param x: Input.\n"
            '    """\n'
            "    return x\n"
        ),
    )
    assert C02ExampleUsageDoctestBlock().check_file(ctx) == []


def test_c02_structured_docstring_with_google_style_sections_suppresses_example_usage(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x: int) -> int:\n"
            '    """\n'
            "    Example Usage:\n"
            "        f(1)\n"
            "\n"
            "    Args:\n"
            "        x: Input.\n"
            '    """\n'
            "    return x\n"
        ),
    )
    assert C02ExampleUsageDoctestBlock().check_file(ctx) == []


def test_c02_indented_example_usage_comment_is_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            "    # Example Usage:\n"
            "    #   f()\n"
            "    return 1\n"
        ),
    )
    violations = C02ExampleUsageDoctestBlock().check_file(ctx)
    assert any(v.rule_id == "C02" for v in violations)


def test_c02_indented_example_usage_in_string_assignment_is_ignored(project_ctx) -> None:
    # Indented but not a comment and not inside a docstring -> docstring_for_line returns None.
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            '    x = "Example Usage:"\n'
            "    return 1\n"
        ),
    )
    assert C02ExampleUsageDoctestBlock().check_file(ctx) == []


def test_c02_other_languages_only_considers_indented_comments(project_ctx) -> None:
    js = make_file_ctx(
        project_ctx,
        relpath="src/example.js",
        content=(
            "// Example Usage:\n"
            "// f()\n"
            "  // Example Usage:\n"
            "  // f()\n"
        ),
    )
    violations = C02ExampleUsageDoctestBlock().check_file(js)
    assert any(v.rule_id == "C02" for v in violations)


def test_optional_import_lines_handles_multiple_except_shapes() -> None:
    tree1 = ast.parse(
        "try:\n"
        "    import maybe\n"
        "except:\n"
        "    maybe = None\n"
    )
    assert _optional_import_lines(tree1) == {2}

    tree2 = ast.parse(
        "try:\n"
        "    from no_such_pkg import thing\n"
        "except (ValueError, ImportError):\n"
        "    thing = None\n"
    )
    assert _optional_import_lines(tree2) == {2}

    tree3 = ast.parse(
        "try:\n"
        "    import not_optional\n"
        "except ValueError:\n"
        "    pass\n"
    )
    assert _optional_import_lines(tree3) == set()

    assert _optional_import_lines(None) == set()


def test_c03_hallucinated_import_from_is_flagged(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content="from definitely_not_a_real_module_12345 import x\n",
    )
    violations = C03HallucinatedImport().check_file(ctx)
    assert any(v.rule_id == "C03" for v in violations)


def test_c03_optional_import_from_in_try_is_ignored(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "try:\n"
            "    from definitely_not_a_real_module_12345 import x\n"
            "except ImportError:\n"
            "    x = None\n"
        ),
    )
    assert C03HallucinatedImport().check_file(ctx) == []


def test_c03_relative_import_is_ignored(project_ctx) -> None:
    make_file_ctx(project_ctx, relpath="src/pkg/__init__.py", content="")
    make_file_ctx(project_ctx, relpath="src/pkg/local_mod.py", content="x = 1\n")
    ctx = make_file_ctx(project_ctx, relpath="src/pkg/example.py", content="from . import local_mod\n")
    assert C03HallucinatedImport().check_file(ctx) == []


def test_c07_debug_print_detects_fstring_and_exact_debug_prefix(project_ctx) -> None:
    ctx_f = make_file_ctx(project_ctx, relpath="src/example.py", content='print(f"DEBUG: {1}")\n')
    assert any(v.rule_id == "C07" for v in C07DebugPrintStatements().check_file(ctx_f))

    ctx_exact = make_file_ctx(project_ctx, relpath="src/example2.py", content='print("DEBUG")\n')
    assert any(v.rule_id == "C07" for v in C07DebugPrintStatements().check_file(ctx_exact))

    ctx_no_args = make_file_ctx(project_ctx, relpath="src/example3.py", content="print()\n")
    assert C07DebugPrintStatements().check_file(ctx_no_args) == []


def test_dependency_helpers_cover_edge_cases(tmp_path: Path) -> None:
    # Non-strings and non-name requirements are ignored.
    assert _names_from_dependency_list([123, " ", "-e .", "@invalid"]) == set()
    assert _names_from_dependency_table({123: "x", "python": "^3.11", "requests": "^2.0"}) >= {"requests"}
    assert _normalize_dist_to_modules("") == set()
    assert _normalize_dist_to_modules("foo-bar") >= {"foo_bar", "foo"}


def test_declared_dependency_modules_parses_pyproject_and_requirements(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["requests>=2.0", 123]

[project.optional-dependencies]
dev = ["foo-bar>=1.0"]

[tool.poetry.dependencies]
python = "^3.11"
numpy = "^1.0"

[tool.poetry.dev-dependencies]
pytest = "^8.0"

[tool.poetry.group.docs.dependencies]
mkdocs-material = "^9.0"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text(
        """
# comment
some-pkg>=1.0
-e .
""".lstrip(),
        encoding="utf-8",
    )

    mods = _declared_dependency_modules(tmp_path)
    assert "requests" in mods
    assert "foo_bar" in mods
    assert "numpy" in mods
    assert "mkdocs_material" in mods
    assert "mkdocs" in mods
    assert "some_pkg" in mods


def test_declared_dependency_modules_tolerates_invalid_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("this is not toml = [\n", encoding="utf-8")
    assert _declared_dependency_modules(tmp_path) == frozenset()
