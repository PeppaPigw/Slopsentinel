from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from slopsentinel.cli import app

pytestmark = pytest.mark.integration


def test_cache_invalidation_on_file_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    (repo / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.cache]
enabled = true
path = ".slopsentinel/cache.json"
""".lstrip(),
        encoding="utf-8",
    )

    source = repo / "src" / "example.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# We need to ensure this is safe\nx = 1\n", encoding="utf-8")

    runner = CliRunner()

    res1 = runner.invoke(app, ["scan", str(repo), "--format", "json", "--threshold", "60"])
    assert res1.exit_code == 0

    cache_path = repo / ".slopsentinel" / "cache.json"
    assert cache_path.exists()
    cache1 = json.loads(cache_path.read_text(encoding="utf-8"))
    hash1 = cache1["files"]["src/example.py"]["hash"]

    # Second scan should read the same cached hash for unchanged content.
    res2 = runner.invoke(app, ["scan", str(repo), "--format", "json", "--threshold", "60"])
    assert res2.exit_code == 0
    cache2 = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache2["files"]["src/example.py"]["hash"] == hash1

    # Mutate file content; cache entry hash should change after scan.
    source.write_text("# We need to ensure this is safe\nx = 2\n", encoding="utf-8")
    res3 = runner.invoke(app, ["scan", str(repo), "--format", "json", "--threshold", "60"])
    assert res3.exit_code == 0
    cache3 = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache3["files"]["src/example.py"]["hash"] != hash1
