from __future__ import annotations

from pathlib import Path

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.rules.crossfile import (
    X02CrossFileNamingConsistency,
    X03PythonStructureFingerprintClusters,
    X04PythonCircularImportRisk,
    _expected_test_for_src_module,
)


def test_expected_test_for_src_module_returns_none_for_non_py_files() -> None:
    assert _expected_test_for_src_module("src/a.txt") is None


def test_x02_continues_when_only_one_style_is_common(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    paths = [src / "a_a.py", src / "b_b.py", src / "c_c.py", src / "d_d.py"]
    for p in paths:
        p.write_text("x = 1\n", encoding="utf-8")

    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=tuple(paths), config=SlopSentinelConfig())
    assert X02CrossFileNamingConsistency().check_project(project) == []


def _structure_only(prefix: str) -> str:
    parts: list[str] = []
    for i in range(10):
        parts.append(f"def {prefix}{i}():")
        parts.append(f"    x{i} = {i}")
        parts.append(f"    return x{i}")
        parts.append("")
    return "\n".join(parts) + "\n"


def test_x03_skips_syntax_error_file_after_size_threshold(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    bad = src / "bad.py"
    bad.write_text("\n".join([f"x{i} = {i}" for i in range(30)]) + "\n" + "def f(:\n", encoding="utf-8")

    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(bad,), config=SlopSentinelConfig())
    assert X03PythonStructureFingerprintClusters().check_project(project) == []


def test_x03_does_not_report_when_only_two_files_share_structure(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    a = src / "a.py"
    b = src / "b.py"
    a.write_text(_structure_only("a"), encoding="utf-8")
    b.write_text(_structure_only("b"), encoding="utf-8")

    project = ProjectContext(project_root=tmp_path, scan_path=tmp_path, files=(a, b), config=SlopSentinelConfig())
    assert X03PythonStructureFingerprintClusters().check_project(project) == []


def test_x04_detects_absolute_from_import_cycle_and_skips_unreadable_or_invalid_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)

    a = src / "a.py"
    b = src / "b.py"
    a.write_text("from b import x\n", encoding="utf-8")
    b.write_text("from a import y\n", encoding="utf-8")

    missing = src / "missing.py"
    bad = src / "bad.py"
    bad.write_text("def f(:\n", encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(a, b, missing, bad),
        config=SlopSentinelConfig(),
    )
    violations = X04PythonCircularImportRisk().check_project(project)
    assert any(v.rule_id == "X04" and "a -> b -> a" in v.message for v in violations)

