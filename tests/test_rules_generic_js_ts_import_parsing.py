from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.generic import E03UnusedImports


def test_e03_unused_imports_typescript_parses_comma_clauses_and_ignores_inline_comments(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.ts",
        content=(
            "import Default, {\n"
            "  Foo /* block comment */,\n"
            "  type Bar,\n"
            "  Baz as B, // line comment\n"
            "  Qux,\n"
            "} from 'm'\n"
            "const x = 1\n"
        ),
    )
    violations = E03UnusedImports().check_file(ctx)
    assert [v.message for v in violations] == [
        "Imported name `B` is never used.",
        "Imported name `Bar` is never used.",
        "Imported name `Default` is never used.",
        "Imported name `Foo` is never used.",
        "Imported name `Qux` is never used.",
    ]

