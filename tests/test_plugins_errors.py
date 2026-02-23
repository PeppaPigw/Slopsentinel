from __future__ import annotations

import pytest

from slopsentinel.rules.plugins import PluginLoadError, load_plugin_rules


def test_load_plugin_rules_missing_module_raises() -> None:
    with pytest.raises(PluginLoadError):
        load_plugin_rules(("this_module_should_not_exist_12345",))


def test_load_plugin_rules_missing_exports_raises(tmp_path, monkeypatch) -> None:
    plugin = tmp_path / "no_exports.py"
    plugin.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(PluginLoadError):
        load_plugin_rules(("no_exports",))


def test_load_plugin_rules_missing_attr_raises(tmp_path, monkeypatch) -> None:
    plugin = tmp_path / "simple_plugin.py"
    plugin.write_text("RULES = []\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(PluginLoadError):
        load_plugin_rules(("simple_plugin:missing_attr",))


def test_load_plugin_rules_rejects_non_rule_items(tmp_path, monkeypatch) -> None:
    plugin = tmp_path / "bad_rules.py"
    plugin.write_text("RULES = [1, 2, 3]\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(PluginLoadError):
        load_plugin_rules(("bad_rules",))


def test_load_plugin_rules_rejects_unsupported_export_type(tmp_path, monkeypatch) -> None:
    plugin = tmp_path / "bad_export.py"
    plugin.write_text("slopsentinel_rules = 123\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(PluginLoadError):
        load_plugin_rules(("bad_export",))
