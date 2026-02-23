from __future__ import annotations

from pathlib import Path

from slopsentinel_plugin_security.rules import (
    S01PythonShellTrue,
    S02YamlLoadUnsafe,
    S03JavaScriptEval,
)

from slopsentinel.engine.context import FileContext
from slopsentinel.suppressions import parse_suppressions


def _ctx(*, language: str, text: str) -> FileContext:
    if not text.endswith("\n"):
        text += "\n"
    lines = tuple(text.splitlines(keepends=True))
    suffix = {
        "python": "py",
        "javascript": "js",
        "typescript": "ts",
    }[language]
    return FileContext(
        project_root=Path("."),
        path=Path(f"example.{suffix}"),
        relative_path=f"example.{suffix}",
        language=language,
        text=text,
        lines=lines,
        suppressions=parse_suppressions(lines),
    )


def test_s01_shell_true_triggers() -> None:
    ctx = _ctx(language="python", text="import subprocess\nsubprocess.run('echo hi', shell=True)\n")
    violations = S01PythonShellTrue().check_file(ctx)
    assert [v.rule_id for v in violations] == ["S01"]


def test_s02_yaml_load_triggers() -> None:
    ctx = _ctx(language="python", text="import yaml\nyaml.load(data)\n")
    violations = S02YamlLoadUnsafe().check_file(ctx)
    assert [v.rule_id for v in violations] == ["S02"]


def test_s03_eval_triggers() -> None:
    ctx = _ctx(language="javascript", text="const x = eval('1+1')\n")
    violations = S03JavaScriptEval().check_file(ctx)
    assert [v.rule_id for v in violations] == ["S03"]
