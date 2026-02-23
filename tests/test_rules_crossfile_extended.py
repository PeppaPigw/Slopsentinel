from __future__ import annotations

from pathlib import Path

from slopsentinel.config import SlopSentinelConfig
from slopsentinel.engine.context import ProjectContext
from slopsentinel.rules.crossfile import X04PythonCircularImportRisk, X05MissingTestFile


def test_x04_circular_import_cycle_reported_once(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)

    a = src / "a.py"
    b = src / "b.py"
    c = src / "c.py"
    a.write_text("import b\n", encoding="utf-8")
    b.write_text("import c\n", encoding="utf-8")
    c.write_text("import a\n", encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(a, b, c),
        config=SlopSentinelConfig(),
    )

    violations = X04PythonCircularImportRisk().check_project(project)
    x04 = [v for v in violations if v.rule_id == "X04"]
    assert len(x04) == 1
    assert "a -> b -> c -> a" in x04[0].message


def test_x04_multiple_cycles_reported_per_cycle(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)

    a = src / "a.py"
    b = src / "b.py"
    c = src / "c.py"
    d = src / "d.py"
    a.write_text("import b\n", encoding="utf-8")
    b.write_text("import a\n", encoding="utf-8")
    c.write_text("import d\n", encoding="utf-8")
    d.write_text("import c\n", encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(a, b, c, d),
        config=SlopSentinelConfig(),
    )

    violations = X04PythonCircularImportRisk().check_project(project)
    x04 = [v for v in violations if v.rule_id == "X04"]
    assert len(x04) == 2


def test_x05_missing_test_file_detected(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)

    foo = src / "foo.py"
    foo.write_text("x = 1\n", encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(foo,),
        config=SlopSentinelConfig(),
    )

    violations = X05MissingTestFile().check_project(project)
    x05 = [v for v in violations if v.rule_id == "X05"]
    assert len(x05) == 1
    assert "src/foo.py -> tests/test_foo.py" in x05[0].message


def test_x05_exempts_init_and_accepts_present_test(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)

    init = src / "__init__.py"
    init.write_text("", encoding="utf-8")

    foo = src / "foo.py"
    foo.write_text("x = 1\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_foo.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")

    project = ProjectContext(
        project_root=tmp_path,
        scan_path=tmp_path,
        files=(init, foo),
        config=SlopSentinelConfig(),
    )

    violations = X05MissingTestFile().check_project(project)
    assert not any(v.rule_id == "X05" for v in violations)

