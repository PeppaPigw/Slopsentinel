from __future__ import annotations

from pathlib import Path

import pytest

from slopsentinel.config import (
    ConfigError,
    SlopSentinelConfig,
    _validate_str_list,
    compute_enabled_rule_ids,
    load_config,
    path_is_ignored,
)


def test_validate_str_list_accepts_none_and_rejects_invalid_values() -> None:
    assert _validate_str_list(None, field_name="x") == ()
    with pytest.raises(ConfigError):
        _validate_str_list("not-a-list", field_name="x")
    with pytest.raises(ConfigError):
        _validate_str_list([123], field_name="x")


def test_load_config_defaults_when_tool_table_is_not_a_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("tool = 123\n", encoding="utf-8")
    assert load_config(tmp_path) == SlopSentinelConfig()


@pytest.mark.parametrize(
    "snippet",
    [
        "[tool.slopsentinel]\nthreshold = 101\n",
        '[tool.slopsentinel]\nfail-on-slop = "true"\n',
        '[tool.slopsentinel]\nlanguages = "python"\n',
        '[tool.slopsentinel]\nplugins = "not a list"\n',
    ],
)
def test_load_config_rejects_invalid_slopsentinel_fields(tmp_path: Path, snippet: str) -> None:
    (tmp_path / "pyproject.toml").write_text(snippet, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "snippet",
    [
        '[tool.slopsentinel]\nrules = "all"\n',
        "[tool.slopsentinel]\n\n[tool.slopsentinel.rules]\nenable = 123\n",
        "[tool.slopsentinel]\n\n[tool.slopsentinel.rules]\nseverity_overrides = \"warn\"\n",
        "[tool.slopsentinel]\n\n[tool.slopsentinel.rules]\nseverity_overrides = { A03 = 123 }\n",
        "[tool.slopsentinel]\n\n[tool.slopsentinel.rules]\nseverity_overrides = { A03 = \"fatal\" }\n",
    ],
)
def test_load_config_rejects_invalid_rules_variants(tmp_path: Path, snippet: str) -> None:
    (tmp_path / "pyproject.toml").write_text(snippet, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "snippet",
    [
        """
[tool.slopsentinel]

[tool.slopsentinel.overrides."tests"]
rules.disable = ["A03"]

[tool.slopsentinel.overrides."tests/"]
rules.disable = ["A03"]
""",
        """
[tool.slopsentinel]

[tool.slopsentinel.overrides."/tests/"]
rules.disable = ["A03"]
""",
        """
[tool.slopsentinel]

[tool.slopsentinel.overrides."../tests/"]
rules.disable = ["A03"]
""",
    ],
)
def test_load_config_rejects_invalid_directory_override_prefixes(tmp_path: Path, snippet: str) -> None:
    (tmp_path / "pyproject.toml").write_text(snippet.lstrip(), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_load_config_skips_directory_overrides_without_rules_patch(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.overrides."docs/"]
note = "no rules patch here"
""".lstrip(),
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.directory_overrides == {}


@pytest.mark.parametrize(
    "snippet",
    [
        '[tool.slopsentinel]\nignore = "x"\n',
        "[tool.slopsentinel]\nbaseline = 123\n",
        "[tool.slopsentinel]\n\n[tool.slopsentinel.cache]\nenabled = 1\n",
        "[tool.slopsentinel]\n\n[tool.slopsentinel.history]\nmax-entries = 0\n",
    ],
)
def test_load_config_rejects_invalid_subtables(tmp_path: Path, snippet: str) -> None:
    (tmp_path / "pyproject.toml").write_text(snippet, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


@pytest.mark.parametrize(
    "snippet",
    [
        """
[tool.slopsentinel]

[tool.slopsentinel.scoring]
profile = "nope"
""",
        """
[tool.slopsentinel]

[tool.slopsentinel.scoring.penalties.nope]
warn = 1
""",
        """
[tool.slopsentinel]

[tool.slopsentinel.scoring.penalties.quality]
nope = 1
""",
        """
[tool.slopsentinel]

[tool.slopsentinel.scoring.penalties.quality]
warn = -1
""",
    ],
)
def test_load_config_rejects_invalid_scoring_config(tmp_path: Path, snippet: str) -> None:
    (tmp_path / "pyproject.toml").write_text(snippet.lstrip(), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_compute_enabled_rule_ids_allows_disabling_entire_group(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.rules]
enable = "all"
disable = ["claude"]
""".lstrip(),
        encoding="utf-8",
    )
    enabled = compute_enabled_rule_ids(load_config(tmp_path))
    assert "A01" not in enabled
    assert "C01" in enabled


def test_path_is_ignored_handles_dot_slash_empty_patterns_and_slash_globs(tmp_path: Path) -> None:
    root = tmp_path
    (tmp_path / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    test_path = tmp_path / "tests" / "unit" / "test_something.py"
    test_path.write_text("pass\n", encoding="utf-8")

    (tmp_path / "src" / "x" / "generated").mkdir(parents=True, exist_ok=True)
    gen_path = tmp_path / "src" / "x" / "generated" / "out.py"
    gen_path.write_text("pass\n", encoding="utf-8")

    assert path_is_ignored(test_path, project_root=root, ignore_patterns=["", "./tests/"]) is True
    assert path_is_ignored(gen_path, project_root=root, ignore_patterns=["src/**/generated/*.py"]) is True

    outside = tmp_path.parent / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    assert path_is_ignored(outside, project_root=root, ignore_patterns=["*.py"]) is False

