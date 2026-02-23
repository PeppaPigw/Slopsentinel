from __future__ import annotations

from pathlib import Path

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.rules.crossfile import (
    X02CrossFileNamingConsistency,
    X03PythonStructureFingerprintClusters,
    X04PythonCircularImportRisk,
    _module_package,
)


def test_module_package_handles_packages_and_modules() -> None:
    assert _module_package("pkg", is_package=True) == "pkg"
    assert _module_package("pkg.mod", is_package=False) == "pkg"
    assert _module_package("mod", is_package=False) == ""


def test_x02_ignores_unknown_language_and_small_groups(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)

    # Unknown extension should be ignored (detect_language returns None).
    unknown = src / "weird.xyz"
    unknown.write_text("x = 1\n", encoding="utf-8")

    # Only 3 Python stems -> below the threshold (<4) so no violation.
    a = src / "foo_bar.py"
    b = src / "baz_qux.py"
    c = src / "fooBar.py"
    for p in (a, b, c):
        p.write_text("x = 1\n", encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(unknown, a, b, c),
        config=SlopSentinelConfig(),
    )
    assert X02CrossFileNamingConsistency().check_project(project) == []


def _structure_rich_python(prefix: str) -> str:
    # Ensure >30 normalized lines and include: ClassDef, AsyncFunctionDef,
    # arg, Attribute, Name, Constant.
    lines: list[str] = []
    lines.append(f"class {prefix}C:")
    lines.append("    def __init__(self, x: int) -> None:")
    lines.append("        self.value = x")
    lines.append("")
    lines.append("    def add(self, y: int) -> int:")
    lines.append("        total = self.value + y")
    lines.append("        return total")
    lines.append("")
    lines.append("async def afunc(z: int) -> int:")
    lines.append("    return z + 1")
    lines.append("")
    # Pad with additional defs to exceed the normalization threshold.
    for i in range(10):
        lines.append(f"def {prefix}f{i}(x: int) -> int:")
        lines.append("    value = x + 1")
        lines.append("    return value")
        lines.append("")
    return "\n".join(lines) + "\n"


def test_x03_skeletonize_skips_test_paths_and_tolerates_errors(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    a = src / "a.py"
    b = src / "b.py"
    c = src / "c.py"
    a.write_text(_structure_rich_python("a"), encoding="utf-8")
    b.write_text(_structure_rich_python("b"), encoding="utf-8")
    c.write_text(_structure_rich_python("c"), encoding="utf-8")

    # Should be skipped by is_test_path().
    ignored = tests_dir / "test_ignored.py"
    ignored.write_text(_structure_rich_python("t"), encoding="utf-8")

    # Should be skipped due to SyntaxError.
    bad = src / "bad.py"
    bad.write_text("def f(:\n", encoding="utf-8")

    # Should be skipped due to OSError (missing file).
    missing = src / "missing.py"

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(a, b, c, ignored, bad, missing),
        config=SlopSentinelConfig(),
    )
    violations = X03PythonStructureFingerprintClusters().check_project(project)
    assert any(v.rule_id == "X03" for v in violations)


def test_x04_resolves_relative_import_from_and_detects_self_cycle(tmp_path: Path) -> None:
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True, exist_ok=True)

    init = src / "__init__.py"
    init.write_text("", encoding="utf-8")

    a = src / "a.py"
    b = src / "b.py"
    a.write_text("from . import b\n", encoding="utf-8")
    b.write_text("from .a import f\n\ndef f() -> None:\n    return None\n", encoding="utf-8")

    # base_depth < 0 for node.level > package depth: should not crash.
    too_deep = src / "too_deep.py"
    too_deep.write_text("from ... import b\n", encoding="utf-8")

    # Star imports should skip adding the candidate edge for the alias itself.
    star = src / "star.py"
    star.write_text("from .a import *\n", encoding="utf-8")

    # Self-cycle via plain import.
    self_mod = src / "self.py"
    self_mod.write_text("import pkg.self\n", encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(init, a, b, too_deep, star, self_mod),
        config=SlopSentinelConfig(),
    )

    violations = X04PythonCircularImportRisk().check_project(project)
    messages = [v.message for v in violations if v.rule_id == "X04"]
    assert any("pkg.a" in m and "pkg.b" in m for m in messages)
    assert any("pkg.self" in m for m in messages)

