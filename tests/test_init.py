from __future__ import annotations

from pathlib import Path

from slopsentinel.init import InitOptions, init_project


def test_init_creates_pyproject_when_missing(tmp_path: Path) -> None:
    result = init_project(InitOptions(project_dir=tmp_path))
    assert (tmp_path / "pyproject.toml").exists()
    assert result.changed_files

    # Second run should be idempotent
    before = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    result2 = init_project(InitOptions(project_dir=tmp_path))
    after = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert before == after
    assert not result2.changed_files


def test_init_appends_config_to_existing_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.black]
line-length = 88
""".lstrip(),
        encoding="utf-8",
    )

    init_project(InitOptions(project_dir=tmp_path))
    content = pyproject.read_text(encoding="utf-8")
    assert "[tool.black]" in content
    assert "[tool.slopsentinel]" in content

    # Second run should not append again
    before = content
    init_project(InitOptions(project_dir=tmp_path))
    after = pyproject.read_text(encoding="utf-8")
    assert before == after


def test_init_creates_github_workflow_when_requested(tmp_path: Path) -> None:
    init_project(InitOptions(project_dir=tmp_path, ci="github"))
    wf = tmp_path / ".github" / "workflows" / "slopsentinel.yml"
    assert wf.exists()
    before = wf.read_text(encoding="utf-8")
    init_project(InitOptions(project_dir=tmp_path, ci="github"))
    after = wf.read_text(encoding="utf-8")
    assert before == after


def test_init_precommit_creates_when_missing(tmp_path: Path) -> None:
    init_project(InitOptions(project_dir=tmp_path, pre_commit=True))
    pc = tmp_path / ".pre-commit-config.yaml"
    assert pc.exists()
    before = pc.read_text(encoding="utf-8")
    init_project(InitOptions(project_dir=tmp_path, pre_commit=True))
    after = pc.read_text(encoding="utf-8")
    assert before == after


def test_init_precommit_inserts_into_existing_repos(tmp_path: Path) -> None:
    pc = tmp_path / ".pre-commit-config.yaml"
    pc.write_text(
        """
repos:
  - repo: https://github.com/psf/black
    rev: 24.8.0
    hooks:
      - id: black

default_stages: [commit]
""".lstrip(),
        encoding="utf-8",
    )

    init_project(InitOptions(project_dir=tmp_path, pre_commit=True))
    updated = pc.read_text(encoding="utf-8")
    assert "id: slopsentinel" in updated

    # idempotent: should not insert again
    before = updated
    init_project(InitOptions(project_dir=tmp_path, pre_commit=True))
    after = pc.read_text(encoding="utf-8")
    assert before == after

