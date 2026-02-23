from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from slopsentinel.languages.registry import tree_sitter_language_for_path
from slopsentinel.rules.plugins import load_plugin_rules
from slopsentinel.rules.utils import is_comment_line


def test_tree_sitter_language_for_tsx() -> None:
    assert tree_sitter_language_for_path(Path("x.tsx"), detected_language="typescript") == "tsx"
    assert tree_sitter_language_for_path(Path("x.ts"), detected_language="typescript") == "typescript"


def test_load_plugin_rules_ignores_blank_specs() -> None:
    assert load_plugin_rules(("", "   ", "\n")) == []


def test_is_comment_line_recognizes_supported_prefixes() -> None:
    assert is_comment_line("   ") is False
    assert is_comment_line("# comment") is True
    assert is_comment_line("  // comment") is True
    assert is_comment_line(" /* comment */") is True


def test_module_entrypoint_help_runs() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "slopsentinel", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "SlopSentinel" in (res.stdout + res.stderr)
