from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.generic import (
    E01CommentCodeRatioAnomalous,
    E02OverlyDefensiveProgramming,
    E03UnusedImports,
    E06RepeatedStringLiteral,
    E07ExcessiveNesting,
    E09HardcodedCredential,
    E10ExcessiveGuardClauses,
)


def test_e01_comment_code_ratio_skips_small_files(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "# c1\n# c2\n# c3\n# c4\n# c5\n# c6\n# c7\n# c8\n"
            "x = 1\n"
        ),
    )
    assert E01CommentCodeRatioAnomalous().check_file(ctx) == []


def test_e02_overly_defensive_programming_skips_non_python(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.js", content="if (x) { return 1 }\n")
    assert E02OverlyDefensiveProgramming().check_file(ctx) == []


def test_e03_unused_imports_handles_type_and_namespace_imports(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "import type { Foo } from 'm'\n"
            "import * as NS from 'm'\n"
            "const x = 1\n"
        ),
    )
    violations = E03UnusedImports().check_file(ctx)
    assert [v.message for v in violations] == [
        "Imported name `Foo` is never used.",
        "Imported name `NS` is never used.",
    ]


def test_e03_unused_imports_ignores_side_effect_imports(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "import 'm'\n"
            "import \"n\";\n"
            "const x = 1\n"
        ),
    )
    assert E03UnusedImports().check_file(ctx) == []


def test_e06_repeated_string_literal_ignores_templates_and_module_specifiers(project_ctx) -> None:
    # Backtick templates are ignored.
    ctx_templates = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "const a = `hello world`\n"
            "const b = `hello world`\n"
            "const c = `hello world`\n"
            "const x = 1\n"
        ),
    )
    assert E06RepeatedStringLiteral().check_file(ctx_templates) == []

    # require() module specifiers are blanked out.
    ctx_require = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "const a = require('react-dom')\n"
            "const b = require('react-dom')\n"
            "const c = require('react-dom')\n"
            "const x = 1\n"
        ),
    )
    assert E06RepeatedStringLiteral().check_file(ctx_require) == []

    # export ... from module specifiers are also blanked out.
    ctx_export_from = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "export { a } from 'react-dom'\n"
            "export { b } from 'react-dom'\n"
            "export { c } from 'react-dom'\n"
            "const x = 1\n"
        ),
    )
    assert E06RepeatedStringLiteral().check_file(ctx_export_from) == []


def test_e07_excessive_nesting_counts_tabs_as_indentation(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            "\tif x:\n"
            "\t\tif x:\n"
            "\t\t\tif x:\n"
            "\t\t\t\tif x:\n"
            "\t\t\t\t\tif x:\n"
            "\t\t\t\t\t\tif x:\n"
            "\t\t\t\t\t\t\treturn 1\n"
        ),
    )
    violations = E07ExcessiveNesting().check_file(ctx)
    assert any(v.rule_id == "E07" for v in violations)


def test_e10_excessive_guard_clauses_skips_docstring(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f(x):\n"
            "    \"\"\"Docstring.\"\"\"\n"
            "    if x == 0: return 0\n"
            "    if x == 1: return 1\n"
            "    if x == 2: return 2\n"
            "    if x == 3: return 3\n"
            "    if x == 4: return 4\n"
            "    if x == 5: return 5\n"
            "    return x\n"
        ),
    )
    violations = E10ExcessiveGuardClauses().check_file(ctx)
    assert any(v.rule_id == "E10" for v in violations)


def test_e09_hardcoded_credential_typescript_covers_more_branches(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/creds.ts",
        content=(
            "// comment\n"
            "const apiKey: string = \"abc123\", token = \"def456\";\n"
            "config.apiKey = \"nope\";\n"
            "if (apiKey == \"nope\") { /* ignore */ }\n"
            "apiKey = \"still_bad\";\n"
            "const template = `token = \"not parsed\"`;\n"
        ),
    )
    violations = E09HardcodedCredential().check_file(ctx)
    assert [v.rule_id for v in violations] == ["E09", "E09", "E09"]
    assert {v.location.start_line for v in violations if v.location is not None} == {2, 5}
