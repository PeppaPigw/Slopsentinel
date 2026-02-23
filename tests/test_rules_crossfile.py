from __future__ import annotations

from pathlib import Path

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.rules.crossfile import (
    X01CrossFileDuplicateCode,
    X02CrossFileNamingConsistency,
    X03PythonStructureFingerprintClusters,
)


def test_x01_cross_file_duplicate_code_detected(tmp_path: Path) -> None:
    a = tmp_path / "src" / "a.py"
    b = tmp_path / "src" / "b.py"
    a.parent.mkdir(parents=True, exist_ok=True)

    body = "\n".join([f"x{i} = {i}" for i in range(25)]) + "\n"
    a.write_text(body, encoding="utf-8")
    b.write_text(body, encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(a, b),
        config=SlopSentinelConfig(),
    )
    violations = X01CrossFileDuplicateCode().check_project(project)
    assert any(v.rule_id == "X01" for v in violations)


def test_x02_cross_file_naming_consistency_detected(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    paths = [
        src / "foo_bar.py",
        src / "baz_qux.py",
        src / "fooBar.py",
        src / "bazQux.py",
    ]
    for path in paths:
        path.write_text("x = 1\n", encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=tuple(paths),
        config=SlopSentinelConfig(),
    )
    violations = X02CrossFileNamingConsistency().check_project(project)
    assert any(v.rule_id == "X02" for v in violations)


def test_x03_python_structure_fingerprint_clusters_detected(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)

    def file_body(prefix: str) -> str:
        parts = []
        for i in range(10):
            parts.append(f"def {prefix}{i}():")
            parts.append(f"    x{i} = {i}")
            parts.append(f"    return x{i}")
            parts.append("")
        return "\n".join(parts) + "\n"

    paths = [
        src / "a.py",
        src / "b.py",
        src / "c.py",
    ]
    for idx, path in enumerate(paths):
        path.write_text(file_body(prefix=chr(ord('a') + idx)), encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=tuple(paths),
        config=SlopSentinelConfig(),
    )
    violations = X03PythonStructureFingerprintClusters().check_project(project)
    assert any(v.rule_id == "X03" for v in violations)
