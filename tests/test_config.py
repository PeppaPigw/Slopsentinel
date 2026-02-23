from __future__ import annotations

from pathlib import Path

import pytest

from slopsentinel.config import (
    ConfigError,
    SlopSentinelConfig,
    compute_enabled_rule_ids,
    load_config,
    path_is_ignored,
)


def test_load_config_defaults_when_no_pyproject(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert isinstance(config, SlopSentinelConfig)
    assert config.threshold == 60
    assert config.fail_on_slop is False
    assert "python" in config.languages


def test_load_config_reads_tool_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
threshold = 42
fail-on-slop = true
languages = ["python"]

baseline = ".slopsentinel-baseline.json"
plugins = ["my_rules:rules"]

[tool.slopsentinel.cache]
enabled = true
path = ".slopsentinel/cache.json"

[tool.slopsentinel.history]
enabled = true
path = ".slopsentinel/history.json"
max-entries = 123

[tool.slopsentinel.rules]
enable = ["claude", "generic"]
disable = ["A02"]

[tool.slopsentinel.rules.A03]
severity = "info"

[tool.slopsentinel.ignore]
paths = ["tests/"]
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(tmp_path)
    assert config.threshold == 42
    assert config.fail_on_slop is True
    assert config.languages == ("python",)
    assert config.cache.enabled is True
    assert config.cache.path == ".slopsentinel/cache.json"
    assert config.history.enabled is True
    assert config.history.path == ".slopsentinel/history.json"
    assert config.history.max_entries == 123
    assert config.baseline == ".slopsentinel-baseline.json"
    assert config.plugins == ("my_rules:rules",)
    assert config.rules.disable == ("A02",)
    assert config.rules.overrides["A03"].severity == "info"
    assert config.ignore.paths == ("tests/",)


def test_load_config_rejects_invalid_threshold_type(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]
threshold = "60"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_compute_enabled_rule_ids_enable_groups_disable_id(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.rules]
enable = ["claude", "generic"]
disable = ["A02"]
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(tmp_path)
    enabled = compute_enabled_rule_ids(config)
    assert "A01" in enabled
    assert "A02" not in enabled
    assert "E01" in enabled
    assert "C01" not in enabled  # copilot not enabled here


def test_rule_ids_are_case_insensitive_in_config(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.rules]
enable = ["claude"]
disable = ["a02"]

[tool.slopsentinel.rules.a03]
severity = "info"
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(tmp_path)
    enabled = compute_enabled_rule_ids(config)
    assert "A02" not in enabled
    assert config.rules.overrides["A03"].severity == "info"


def test_load_config_rejects_unknown_rule_group_token(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.rules]
enable = ["claud"]
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_load_config_reads_scoring_profile_and_penalties(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.scoring]
profile = "strict"

[tool.slopsentinel.scoring.penalties.quality]
warn = 9
error = 12
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(tmp_path)
    assert config.scoring.profile == "strict"
    assert config.scoring.penalties["quality"]["warn"] == 9
    assert config.scoring.penalties["quality"]["error"] == 12


def test_load_config_allows_comma_separated_rule_enable_string(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.rules]
enable = "claude,generic"
""".lstrip(),
        encoding="utf-8",
    )

    config = load_config(tmp_path)
    enabled = compute_enabled_rule_ids(config)
    assert "A01" in enabled
    assert "E01" in enabled


def test_path_is_ignored_directory_prefix(tmp_path: Path) -> None:
    root = tmp_path
    file_path = tmp_path / "tests" / "unit" / "test_something.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("pass\n", encoding="utf-8")

    assert path_is_ignored(file_path, project_root=root, ignore_patterns=["tests/"]) is True
    assert path_is_ignored(file_path, project_root=root, ignore_patterns=["scripts/"]) is False


def test_path_is_ignored_glob_basename(tmp_path: Path) -> None:
    root = tmp_path
    file_path = tmp_path / "src" / "module.generated.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("pass\n", encoding="utf-8")

    assert path_is_ignored(file_path, project_root=root, ignore_patterns=["*.generated.*"]) is True


def test_default_rule_groups_only_reference_existing_builtin_rules() -> None:
    from slopsentinel.config import DEFAULT_RULE_GROUPS
    from slopsentinel.rules.registry import builtin_rules

    builtin_ids = {rule.meta.rule_id for rule in builtin_rules()}

    seen: set[str] = set()
    for group, ids in DEFAULT_RULE_GROUPS.items():
        for rule_id in ids:
            assert rule_id in builtin_ids, f"{group} references unknown rule id: {rule_id}"
            seen.add(rule_id)

    # "all" should be the union of all other groups.
    union_others: set[str] = set()
    for group, ids in DEFAULT_RULE_GROUPS.items():
        if group == "all":
            continue
        union_others.update(ids)
    assert set(DEFAULT_RULE_GROUPS["all"]) == union_others
