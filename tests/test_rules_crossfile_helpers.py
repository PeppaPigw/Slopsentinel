from __future__ import annotations

from pathlib import Path

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.rules.crossfile import (
    X01CrossFileDuplicateCode,
    _expected_test_for_src_module,
    _filename_style,
    _find_cycle_path,
    _normalize_code_lines,
    _src_py_to_module,
)


def test_normalize_code_lines_strips_block_comments_and_line_comments() -> None:
    normalized = _normalize_code_lines(
        "\n".join(
            [
                "/*",
                " comment",
                "*/",
                "x   =   1",
                "// trailing comment-only line",
                "y=2",
                "",
            ]
        )
        + "\n"
    )
    assert normalized == ("x = 1", "y=2")


def test_filename_style_detects_multiple_conventions() -> None:
    assert _filename_style("foo_bar") == "snake"
    assert _filename_style("foo-bar") == "kebab"
    assert _filename_style("fooBar") == "camel"
    assert _filename_style("FooBar") == "pascal"
    assert _filename_style("123") == "other"


def test_src_py_to_module_handles_packages_and_non_src() -> None:
    assert _src_py_to_module("lib/a.py") is None
    assert _src_py_to_module("src/a.txt") is None
    assert _src_py_to_module("src/__init__.py") is None
    assert _src_py_to_module("src/pkg/__init__.py") == ("pkg", True)
    assert _src_py_to_module("src/pkg/mod.py") == ("pkg.mod", False)


def test_find_cycle_path_skips_edges_outside_component_and_handles_visited() -> None:
    # No cycle, but DFS from "a" visits "b" so the outer loop should skip "b"
    # as already visited. Also includes an edge to "c" (not in nodes) to cover
    # the "v not in nodes" branch.
    nodes = {"a", "b"}
    graph = {"a": {"b", "c"}, "b": set(), "c": {"a"}}
    assert _find_cycle_path(nodes, graph) is None


def test_expected_test_for_src_module_exemptions_and_mapping() -> None:
    assert _expected_test_for_src_module("src/__init__.py") is None
    assert _expected_test_for_src_module("src/__main__.py") is None
    assert _expected_test_for_src_module("src/test_something.py") is None
    assert _expected_test_for_src_module("src/_internal.py") is None
    assert _expected_test_for_src_module("src/generated/foo.py") is None
    assert _expected_test_for_src_module("src/foo_pb2.py") is None
    assert _expected_test_for_src_module("src/foo/bar.py") == "tests/test_foo_bar.py"


def test_x01_duplicate_code_ignores_missing_files_and_small_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    a = src / "a.py"
    b = src / "b.py"
    missing = src / "missing.py"

    # Small files (<20 normalized lines) must not trigger.
    small_body = "\n".join([f"x{i} = {i}" for i in range(5)]) + "\n"
    a.write_text(small_body, encoding="utf-8")
    b.write_text(small_body, encoding="utf-8")

    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(a, b, missing), config=SlopSentinelConfig())
    assert X01CrossFileDuplicateCode().check_project(project) == []

